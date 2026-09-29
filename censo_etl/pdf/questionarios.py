"""Questões dos questionários PDF: `[{"numero", "texto"}]`.

Dois formatos: o comum numera as perguntas ("1 - Nome completo"); o de Turma
é um formulário sem numeração, cujos rótulos de campo aparecem num corpo de
fonte maior que o das alternativas (`extrair_por_layout`).
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from pathlib import Path

log = logging.getLogger(__name__)

_QUESTAO_RE = re.compile(r"^\s*(\d+[a-z]?)\s*[-–]\s+(.+)", re.IGNORECASE)
# Linhas com várias questões mescladas ("CEP 10 – UF 11 – Município").
_MULTI_QUESTAO_RE = re.compile(r"\s\d{1,2}[a-z]?\s*[-–]", re.IGNORECASE)


def texto_garbled(texto: str) -> bool:
    """Texto com letras duplicadas, típico de PDF mal renderizado."""
    letras = [c for c in texto if c.isalpha()]
    if len(letras) < 6:
        return False
    pares = sum(1 for a, b in zip(letras, letras[1:], strict=False) if a == b)
    return pares / len(letras) > 0.25


def extrair_questionario(pdf_path: Path) -> list[dict]:
    """Questões numeradas; se não houver nenhuma, rótulos de campo por layout."""
    import pdfplumber

    perguntas: list[dict] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                for linha in (page.extract_text() or "").split("\n"):
                    m = _QUESTAO_RE.match(linha)
                    if not m:
                        continue
                    texto = m.group(2).strip()
                    if texto_garbled(texto) or _MULTI_QUESTAO_RE.search(texto):
                        continue
                    perguntas.append({"numero": m.group(1), "texto": texto})
    except Exception as exc:
        log.warning("Erro ao ler %s: %s", pdf_path.name, exc)

    if perguntas:
        return perguntas
    perguntas = extrair_por_layout(pdf_path)
    if perguntas:
        log.info("%s: sem questões numeradas; %d rótulo(s) de campo extraído(s) por layout.",
                 pdf_path.name, len(perguntas))
    else:
        log.warning("%s: nenhuma questão extraída (nem numerada, nem por layout) — "
                    "var_qstn_qstnlit ficará vazio para as tabelas que dependem deste "
                    "questionário.", pdf_path.name)
    return perguntas


def _linha_substantiva(texto: str) -> bool:
    """Pode ser rótulo de campo: descarta título de seção em caixa alta e ruído."""
    return (
        len(texto) >= 8
        and not texto.isupper()
        and any(c.isalpha() for c in texto)
        and not texto_garbled(texto)
    )


def extrair_por_layout(pdf_path: Path) -> list[dict]:
    """Rótulos de campo de um questionário NÃO numerado.

    O corpo dos rótulos é descoberto por estatística: entre os tamanhos maiores
    que o mais frequente, vence o que rende mais linhas substantivas. (Fixar o
    tamanho não funciona: o PDF de Turma tem ":" em Times 8,6 sobre Arial 8,0.)
    `numero` fica vazio — o documento não numera, e inventar seria enganoso.
    """
    import pdfplumber

    linhas: list[tuple[float, str]] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                for linha in page.extract_text_lines():
                    texto = " ".join(linha["text"].split())
                    chars = linha.get("chars") or []
                    if texto and chars:
                        tamanho = Counter(round(c["size"], 1) for c in chars).most_common(1)[0][0]
                        linhas.append((tamanho, texto))
    except Exception as exc:
        log.warning("Erro ao ler layout de %s: %s", pdf_path.name, exc)
        return []
    if not linhas:
        return []

    corpo = Counter(t for t, _ in linhas).most_common(1)[0][0]
    por_nivel: dict[float, list[str]] = {}
    for tamanho, texto in linhas:
        if tamanho > corpo and _linha_substantiva(texto):
            por_nivel.setdefault(tamanho, []).append(texto)
    if not por_nivel:
        return []

    nivel = max(sorted(por_nivel), key=lambda t: len(por_nivel[t]))
    perguntas, vistos = [], set()
    for texto in por_nivel[nivel]:
        if texto.lower() not in vistos:
            vistos.add(texto.lower())
            perguntas.append({"numero": "", "texto": texto})
    return perguntas


class LeitorQuestionarios:
    """Memoriza a extração por caminho: o PDF de Turma serve turma,
    curso_tecnico e o censo.html."""

    def __init__(self) -> None:
        self._cache: dict[Path, list[dict]] = {}

    def perguntas(self, pdf_path: Path) -> list[dict]:
        if pdf_path not in self._cache:
            self._cache[pdf_path] = extrair_questionario(pdf_path)
        return self._cache[pdf_path]
