"""Quadros de referência do anexo do Caderno de Conceitos (tabelas do PDF).

    [{"id", "titulo", "cols", "labels", "rows": [{col: valor}]}]

Cada quadro começa numa página cujo texto abre com o seu `cabecalho` e tem um
leitor de linhas próprio, porque o layout das tabelas difere entre eles.
Alguns quadros herdam a área/subárea da linha anterior (`estado`).
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

_CODIGO_RE = re.compile(r"^\d+[A-Za-z]?\d*$")
_CODIGO_4D_RE = re.compile(r"^\d{4}$")
_CODIGO_CURSO_SUP_RE = re.compile(r"^\d{4}[A-Za-z]\d{3}$")
_CODIGO_AREA_RE = re.compile(r"^\d{1,2}$")

Linhas = list[dict]
LeitorLinhas = Callable[[list, dict], Linhas]


def _celula(valor) -> str:
    return "" if valor is None else re.sub(r"\s+", " ", str(valor)).strip()


def _linhas(tabelas: list):
    for tabela in tabelas:
        yield from tabela


def _lingua(tabelas: list, estado: dict) -> Linhas:
    # Três pares (código, nome) lado a lado.
    saida = []
    for row in _linhas(tabelas):
        for j in (0, 2, 4):
            if j + 1 < len(row):
                codigo, nome = _celula(row[j]), _celula(row[j + 1])
                if codigo and nome and codigo.isdigit():
                    saida.append({"codigo": codigo, "nome": nome})
    return saida


def _tecnicos(tabelas: list, estado: dict) -> Linhas:
    saida = []
    for row in _linhas(tabelas):
        if len(row) >= 3:
            codigo, nome = _celula(row[1]), _celula(row[2])
            if codigo and nome and _CODIGO_4D_RE.match(codigo):
                saida.append({"codigo": codigo, "nome": nome})
    return saida


def _areas_conhecimento(tabelas: list, estado: dict) -> Linhas:
    saida = []
    for row in _linhas(tabelas):
        if len(row) < 2:
            continue
        c0, c1 = _celula(row[0]), _celula(row[1])
        if c0 and not c1 and not _CODIGO_RE.match(c0):
            estado["area"] = c0
        elif c0 and c1 and _CODIGO_RE.match(c0):
            saida.append({"area": estado.get("area", ""), "codigo": c0, "nome": c1})
    return saida


def _atividade(tabelas: list, estado: dict) -> Linhas:
    saida = []
    for row in _linhas(tabelas):
        if len(row) < 4:
            continue
        area, subarea, codigo, nome = (_celula(x) for x in row[:4])
        if area:
            estado["area"] = area
        if subarea:
            estado["subarea"] = subarea
        if codigo and nome and _CODIGO_RE.match(codigo):
            saida.append({"area": estado.get("area", ""), "subarea": estado.get("subarea", ""),
                          "codigo": codigo, "nome": nome})
    return saida


def _cursos_superiores(tabelas: list, estado: dict) -> Linhas:
    saida = []
    for row in _linhas(tabelas):
        if len(row) < 4:
            continue
        cod_area, nome_area, curso_cod, nome_grau = (_celula(x) for x in row[:4])
        if nome_area and _CODIGO_AREA_RE.match(cod_area):
            estado["area_nome"] = nome_area
        if curso_cod and nome_grau and _CODIGO_CURSO_SUP_RE.match(curso_cod):
            saida.append({"area_nome": estado.get("area_nome", ""),
                          "curso_cod": curso_cod, "nome_grau": nome_grau})
    return saida


def _pos_graduacao(tabelas: list, estado: dict) -> Linhas:
    saida = []
    for row in _linhas(tabelas):
        if len(row) >= 2:
            codigo, nome = _celula(row[0]), _celula(row[1])
            if codigo and nome and _CODIGO_RE.match(codigo):
                saida.append({"codigo": codigo, "nome": nome})
    return saida


@dataclass(frozen=True)
class Quadro:
    id: str
    titulo: str
    cols: tuple[str, ...]
    labels: tuple[str, ...]
    cabecalho: str
    ler_linhas: LeitorLinhas


QUADROS: tuple[Quadro, ...] = (
    Quadro("lingua", "Língua Indígena", ("codigo", "nome"), ("Código", "Língua"),
           "QUADRO DE LÍNGUA INDÍGENA", _lingua),
    Quadro("tecnicos", "Cursos Técnicos", ("codigo", "nome"), ("Código", "Curso Técnico"),
           "QUADRO DE CURSOS TÉCNICOS", _tecnicos),
    Quadro("areas_conhec", "Áreas do Conhecimento / Componentes Curriculares",
           ("area", "codigo", "nome"), ("Área Geral", "Código", "Componente Curricular"),
           "QUADRO DE ÁREAS DO CONHECIMENTO", _areas_conhecimento),
    Quadro("atividade", "Tipos de Atividade Complementar",
           ("area", "subarea", "codigo", "nome"), ("Área", "Subárea", "Código", "Atividade"),
           "QUADRO DE TIPOS DE ATIVIDADE COMPLEMENTAR", _atividade),
    Quadro("cursos_sup", "Cursos de Formação Superior",
           ("area_nome", "curso_cod", "nome_grau"), ("Área", "Código", "Curso / Grau"),
           "QUADRO DE CURSOS DE FORMAÇÃO SUPERIOR", _cursos_superiores),
    Quadro("pos_grad", "Áreas de Pós-Graduação", ("codigo", "nome"), ("Código", "Área"),
           "QUADRO DE ÁREAS DE PÓS-GRADUAÇÃO", _pos_graduacao),
)


def extrair_quadros(caminho_pdf: Path) -> list[dict]:
    import pdfplumber

    paginas: dict[str, list] = {q.id: [] for q in QUADROS}
    with pdfplumber.open(caminho_pdf) as pdf:
        for page in pdf.pages:
            texto = (page.extract_text() or "").lstrip()
            if quadro := next((q for q in QUADROS if texto.startswith(q.cabecalho)), None):
                paginas[quadro.id].append(page.extract_tables())

    resultado = []
    for q in QUADROS:
        estado: dict = {}
        linhas = [linha for tabelas in paginas[q.id] for linha in q.ler_linhas(tabelas, estado)]
        resultado.append({"id": q.id, "titulo": q.titulo, "cols": list(q.cols),
                          "labels": list(q.labels), "rows": linhas})
    return resultado
