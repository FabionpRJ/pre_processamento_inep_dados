"""Caderno de Conceitos estruturado por CONCEITO — fonte do censo.html e de `var_concept`.

    [{"conceito", "secao", "definicao", "categorias": [{"nome", "descricao"}],
      "destaques": [{"tipo", "texto"}]}]

O texto corrido não preserva a estrutura, então a leitura é pela tipografia
do Caderno: Gotham-Black/Bold para títulos e cabeçalhos, Gotham-Medium para
nome de categoria, Gotham-Book para o corpo. Só os blocos CONCEITOS entram;
a leitura para antes dos quadros de referência do anexo.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from censo_etl.texto import normalizar, title_case

_ROTULO_SECAO = {"escola": "Escola", "turma": "Turma", "pessoa_fisica": "Pessoa Física"}
_TIPOS_DESTAQUE = {"importante": "Importante", "voce sabia": "Você sabia", "atencao": "Atenção"}
_NUMERO_PAGINA_RE = re.compile(r"^\d{1,3}$")
_NUMERO_FINAL_RE = re.compile(r"\s+\d{1,3}$")
_CABECALHO_PAGINA_RE = re.compile(r"^CADERNO DE CONCEITOS E ORIENTAÇÕES DO CENSO ESCOLAR \d{4}$")
_RUIDO_PAGINA = {"1ª ETAPA DA COLETA", "MENU"}
_SECAO_TOPO_RE = re.compile(r"^QUESTIONÁRIOS?\s+DE\s+(ESCOLA|TURMA|PESSOA)\b\s*(FÍSICA\b)?\.?")
_MARCADORES_BLOCO = ("CONCEITOS", "ORIENTAÇÕES")

# Cabeçalhos cujo título principal traz um complemento que a aba lateral não
# tem — mantém o rótulo curto e estável entre edições.
_SECAO_SUB_OVERRIDES = {
    "DADOS DE VÍNCULO DO PROFISSIONAL ESCOLAR EM SALA DE AULA": "DADOS DE VÍNCULO DO PROFISSIONAL ESCOLAR",
}


def _classe_fonte(fontname: str) -> str:
    for marca, classe in (("Black", "black"), ("Bold", "bold"), ("Medium", "medium")):
        if marca in fontname:
            return classe
    return "book"


def _tipo_destaque(texto: str) -> str | None:
    return _TIPOS_DESTAQUE.get(normalizar(texto.rstrip("!:?")))


def _linhas_visuais(page) -> list[list[dict]]:
    """Palavras agrupadas em linhas (tolerância de 2,5 pt no topo entre fontes)."""
    palavras = sorted(page.extract_words(extra_attrs=["fontname", "size"]),
                      key=lambda w: (w["top"], w["x0"]))
    linhas: list[list[dict]] = []
    atual: list[dict] = []
    topo = None
    for w in palavras:
        if topo is None or abs(w["top"] - topo) <= 2.5:
            atual.append(w)
            topo = w["top"] if topo is None else topo
        else:
            linhas.append(sorted(atual, key=lambda x: x["x0"]))
            atual, topo = [w], w["top"]
    if atual:
        linhas.append(sorted(atual, key=lambda x: x["x0"]))
    return linhas


def _runs(page) -> list[dict]:
    """Trechos consecutivos de mesma classe de fonte, na ordem de leitura.

    O tamanho é o da 1ª palavra do trecho (estável mesmo com nº de página colado).
    """
    runs = []
    for linha in _linhas_visuais(page):
        palavras: list[str] = []
        classe = tamanho = None
        for w in linha:
            classe_w = _classe_fonte(w["fontname"])
            if classe_w != classe:
                if palavras:
                    runs.append({"texto": " ".join(palavras), "classe": classe, "size": tamanho})
                palavras, tamanho = [], w["size"]
            palavras.append(w["text"])
            classe = classe_w
        if palavras:
            runs.append({"texto": " ".join(palavras), "classe": classe, "size": tamanho})
    return runs


@dataclass
class _Conceito:
    titulo: str
    secao_topo: str | None
    secao_sub: str | None
    definicao: str = ""
    categorias: list[dict] = field(default_factory=list)
    destaques: list[dict] = field(default_factory=list)

    def vazio(self) -> bool:
        return not (self.definicao or self.categorias or self.destaques)


def _acrescentar(atual: str, texto: str) -> str:
    return atual + (" " if atual else "") + texto


class _Leitor:
    """Máquina de estados sobre os runs das páginas de conceitos."""

    def __init__(self) -> None:
        self.conceitos: list[_Conceito] = []
        self.secao_topo: str | None = None
        self.secao_sub: str | None = None
        self.modo: str | None = None          # "conceitos" | "orientacoes"
        self.atual: _Conceito | None = None
        self.titulo_pendente: list[str] = []
        self.secao_pendente: list[str] = []

    def fechar(self) -> None:
        c = self.atual
        if not (c and self.modo == "conceitos" and c.titulo):
            return
        c.definicao = c.definicao.strip()
        for d in c.destaques:
            d["texto"] = d["texto"].strip()
        for cat in c.categorias:
            cat["descricao"] = cat["descricao"].strip()
        # Negativas ("Não há X") não viram categoria própria.
        c.categorias = [cat for cat in c.categorias
                        if not re.match(r"^n[aã]o\b", cat["nome"], re.IGNORECASE)]
        if not c.vazio():
            self.conceitos.append(c)

    def resolver_titulo(self) -> None:
        if not self.titulo_pendente:
            return
        titulo = _NUMERO_FINAL_RE.sub("", " ".join(self.titulo_pendente))
        self.titulo_pendente.clear()
        c = self.atual
        if c is not None and c.vazio():
            c.titulo = (c.titulo + " " + titulo).strip()   # título em várias linhas
            return
        if (c is not None and c.titulo == titulo
                and (c.secao_topo, c.secao_sub) == (self.secao_topo, self.secao_sub)):
            return   # eco do título após quebra de página
        self.fechar()
        self.atual = _Conceito(titulo, self.secao_topo, self.secao_sub)

    def resolver_secao(self) -> None:
        if not self.secao_pendente:
            return
        self.resolver_titulo()
        texto = _NUMERO_FINAL_RE.sub("", " ".join(self.secao_pendente))
        self.secao_pendente.clear()
        self.fechar()
        if m := _SECAO_TOPO_RE.match(texto.upper()):
            self.secao_topo = {"ESCOLA": "escola", "TURMA": "turma", "PESSOA": "pessoa_fisica"}[m.group(1)]
            resto = texto[m.end():].strip(" -—.")
            if resto.startswith("("):
                fim = resto.find(")")
                resto = resto[fim + 1:].strip(" -—.") if fim != -1 else ""
            self.secao_sub = resto or None
        else:
            self.secao_sub = _SECAO_SUB_OVERRIDES.get(texto, texto)
        self.atual = None
        self.modo = None

    def consumir(self, run: dict) -> None:
        texto = run["texto"].strip()
        if not texto:
            return
        classe, tamanho = run["classe"], run["size"] or 0
        negrito = classe in ("bold", "black")
        if _NUMERO_PAGINA_RE.match(texto) and negrito:
            return
        if _CABECALHO_PAGINA_RE.match(texto) or texto in _RUIDO_PAGINA:
            return

        destaque = _tipo_destaque(texto) if negrito else None
        marcador = texto.upper() in _MARCADORES_BLOCO
        if negrito and 7.5 <= tamanho <= 9.5 and texto.isupper() and not destaque and not marcador:
            self.titulo_pendente.append(texto)
            return
        if classe == "black" and tamanho >= 13 and not destaque and not marcador:
            self.secao_pendente.append(texto)
            return

        self.resolver_secao()
        self.resolver_titulo()

        if marcador and classe == "black":
            modo = "conceitos" if texto.upper() == "CONCEITOS" else "orientacoes"
            if modo != self.modo:
                self.fechar()
                self.atual = None
                self.modo = modo
            return
        if self.modo != "conceitos" or self.atual is None:
            return
        c = self.atual
        if destaque:
            c.destaques.append({"tipo": destaque, "texto": ""})
        elif classe == "medium":
            c.categorias.append({"nome": texto, "descricao": ""})
        elif c.destaques:
            c.destaques[-1]["texto"] = _acrescentar(c.destaques[-1]["texto"], texto)
        elif c.categorias:
            c.categorias[-1]["descricao"] = _acrescentar(c.categorias[-1]["descricao"], texto)
        else:
            c.definicao = _acrescentar(c.definicao, texto)

    def terminar(self) -> None:
        self.resolver_secao()
        self.resolver_titulo()
        self.fechar()


def extrair_conceitos(caminho_pdf: Path) -> list[dict]:
    import pdfplumber

    leitor = _Leitor()
    with pdfplumber.open(caminho_pdf) as pdf:
        # Páginas de conceitos: da 1ª com "QUESTIONÁRIO DE ESCOLA" até antes do
        # 1º quadro. O texto é extraído sob demanda — os quadros são dezenas de páginas.
        paginas = pdf.pages
        texto = [None] * len(paginas)

        def texto_da(i: int) -> str:
            if texto[i] is None:
                texto[i] = paginas[i].extract_text() or ""
            return texto[i]

        inicio = next((i for i in range(len(paginas)) if "QUESTIONÁRIO DE ESCOLA" in texto_da(i).upper()), 0)
        fim = next((i for i in range(inicio, len(paginas)) if texto_da(i).lstrip().startswith("QUADRO DE")),
                   len(paginas))
        for i in range(inicio, fim):
            for run in _runs(paginas[i]):
                leitor.consumir(run)
    leitor.terminar()

    resultado = []
    for c in leitor.conceitos:
        secao = f"Questionário de {_ROTULO_SECAO[c.secao_topo]}"
        if c.secao_sub:
            secao += f" — {title_case(c.secao_sub)}"
        resultado.append({
            "conceito": c.titulo, "secao": secao, "definicao": c.definicao,
            "categorias": c.categorias, "destaques": c.destaques,
        })
    return resultado
