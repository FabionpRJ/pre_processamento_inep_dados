#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gerar_caderno_html.py
============================================================================
Gera o `censo.html` navegável injetando no template estático derivado do
golden file (`templates/censo_template.html`) as fontes de metadados do
pipeline: dicionário de variáveis, conceitos e quadros do Caderno e
questionários.

Este módulo não reprocessa PDF nem xlsx — apenas serializa as estruturas
já produzidas por censo_lib (ver `extrair_conceitos_html`, `extrair_quadros_pdf`,
`extrair_questionario_html`) e por gerar_json_metadata_editor (ver
`montar_dicionario_html`) no bloco `<script id="app-data">` do template.
============================================================================
"""
from __future__ import annotations

import json
from pathlib import Path

TEMPLATE_PATH = Path(__file__).parent / "templates" / "censo_template.html"
MARCADOR = "__APP_DATA__"


def _escapar_fechamento_script(json_texto: str) -> str:
    """Evita que '</script' dentro do JSON encerre o bloco <script> prematuramente."""
    return json_texto.replace("</", "<\\/")


def gerar_censo_html(
    conceitos: list[dict],
    quadros: list[dict],
    saida_path: str | Path,
    questionarios: list[dict] | None = None,
    titulo: str = "Caderno de Conceitos — Censo Escolar 2025",
    dicionario: list[dict] | None = None,
) -> str:
    """Monta o censo.html injetando os dados no template e grava em saida_path.

    Reúne as três fontes de metadados do pipeline: `conceitos`/`quadros` (do
    Caderno de Conceitos), `questionarios` (dos PDFs) e `dicionario` (das abas
    do .xlsx — lista de {id, titulo, fonte, variaveis}, ver
    gerar_json_metadata_editor.montar_dicionario_html).

    Todos os três são opcionais: cada aba correspondente fica oculta no HTML
    gerado quando a lista vem vazia.
    `titulo` é aceito por compatibilidade de assinatura; o template golden
    tem o título fixo no shell HTML (não é substituído aqui).
    """
    if not TEMPLATE_PATH.is_file():
        raise FileNotFoundError(f"Template não encontrado: {TEMPLATE_PATH}")

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    if MARCADOR not in template:
        raise ValueError(f"Marcador {MARCADOR!r} não encontrado no template.")

    dados = {
        "conceitos":     conceitos,
        "quadros":       quadros,
        "questionarios": questionarios or [],
        "dicionario":    dicionario or [],
    }
    json_texto = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
    json_texto = _escapar_fechamento_script(json_texto)

    html = template.replace(MARCADOR, json_texto)

    saida_path = Path(saida_path)
    saida_path.parent.mkdir(parents=True, exist_ok=True)
    saida_path.write_text(html, encoding="utf-8")

    return str(saida_path)
