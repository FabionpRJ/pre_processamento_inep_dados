"""Caderno de Conceitos em blocos por seção — fonte de `var_txt` e `var_qstn_ivuinstr`.

    {"escola" | "turma" | "pessoa_fisica": {
        "conceitos":   [(titulo, definicao, destaque)],
        "orientacoes": [(titulo, texto)]}}

Lê o texto corrido: seções pelos cabeçalhos "QUESTIONÁRIO DE ...", blocos
pelos marcadores CONCEITOS/ORIENTAÇÕES e títulos pelas linhas em caixa alta.
Os destaques ("Importante!", "Você sabia?") ficam separados da definição.
"""
from __future__ import annotations

import re
from pathlib import Path

SECOES = ("escola", "turma", "pessoa_fisica")

# Boilerplate de página (CONCEITOS/ORIENTAÇÕES não entram: têm papel funcional).
_BOILERPLATE = re.compile(r"^(\d{1,3}|CADERNO DE CONCEITOS.*|1ª ETAPA DA COLETA|MENU)$")
_MARCADORES_BLOCO = {"CONCEITOS": "conceito", "ORIENTAÇÕES": "orientacao"}


def _eh_caixa_alta(linha: str) -> bool:
    s = linha.strip()
    if len(s) < 5:
        return False
    letras = [c for c in s if c.isalpha()]
    return bool(letras) and all(c == c.upper() for c in letras)


def _secao_do_cabecalho(linha: str) -> str | None:
    if "QUESTIONÁRIO DE ESCOLA" in linha and "PESSOA" not in linha:
        return "escola"
    if "QUESTIONÁRIO DE TURMA" in linha:
        return "turma"
    if "QUESTIONÁRIOS DE PESSOA" in linha or "QUESTIONÁRIO DE PESSOA" in linha:
        return "pessoa_fisica"
    return None


def _linhas_do_pdf(caminho_pdf: Path) -> list[str]:
    import pdfplumber

    with pdfplumber.open(caminho_pdf) as pdf:
        return [s for page in pdf.pages
                for bruta in (page.extract_text() or "").split("\n")
                if (s := bruta.strip())]


def extrair_secoes(caminho_pdf: Path) -> dict[str, dict[str, list]]:
    resultado: dict[str, dict[str, list]] = {s: {"conceitos": [], "orientacoes": []} for s in SECOES}
    linhas = _linhas_do_pdf(caminho_pdf)

    secao = modo = titulo = None
    texto: list[str] = []
    destaque: list[str] = []
    em_destaque = False

    def fechar_bloco() -> None:
        if not (titulo and secao and modo):
            return
        corpo = " ".join(texto).strip()
        if not corpo:
            return
        if modo == "conceito":
            resultado[secao]["conceitos"].append((titulo, corpo, " ".join(destaque).strip()))
        else:
            resultado[secao]["orientacoes"].append((titulo, corpo))

    i = 0
    while i < len(linhas):
        linha = linhas[i]
        i += 1
        if _BOILERPLATE.match(linha):
            continue
        if nova_secao := _secao_do_cabecalho(linha):
            fechar_bloco()
            secao, modo, titulo = nova_secao, None, None
            texto, destaque = [], []
            continue
        if linha in _MARCADORES_BLOCO:
            fechar_bloco()
            modo, titulo = _MARCADORES_BLOCO[linha], None
            texto, destaque, em_destaque = [], [], False
            continue
        if secao is None or modo is None:
            continue

        if _eh_caixa_alta(linha):
            # Título pode ocupar várias linhas; linha repetida é eco de layout.
            partes = [linha]
            while (
                i < len(linhas)
                and _eh_caixa_alta(linhas[i])
                and not _BOILERPLATE.match(linhas[i])
                and "QUESTIONÁRIO" not in linhas[i]
                and linhas[i] not in _MARCADORES_BLOCO
                and linhas[i] not in partes
            ):
                partes.append(linhas[i])
                i += 1
            fechar_bloco()
            titulo = " ".join(partes)
            texto, destaque, em_destaque = [], [], False
            continue

        if titulo:
            if linha.startswith(("Importante!", "Você sabia?")):
                em_destaque = True
            (destaque if em_destaque else texto).append(linha)

    fechar_bloco()
    return resultado
