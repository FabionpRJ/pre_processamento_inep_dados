"""censo.html: página autocontida com dicionário, Caderno e questionários.

Os dados vão como JSON no marcador `__APP_DATA__` do template, dentro de
`<script id="app-data" type="application/json">`, com quatro chaves:
`conceitos`, `quadros`, `questionarios`, `dicionario`. Cada modo da página só
aparece se a sua fonte veio preenchida.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from censo_etl.dicionario import TabelaDicionario
from censo_etl.metadata_editor import anos_coletados, nota_descontinuada
from censo_etl.tabelas import rotulo

TEMPLATE = Path(__file__).parent / "templates" / "censo_template.html"
MARCADOR = "__APP_DATA__"


def montar_dicionario(tabelas: dict[str, TabelaDicionario]) -> list[dict]:
    """Bloco `dicionario`: uma entrada por aba, com as variáveis como estão na planilha."""
    return [
        {
            "id": chave,
            "titulo": rotulo(chave),
            "fonte": tabela.titulo,
            "variaveis": [
                {
                    "ordem": v.ordem,
                    "nome": v.nome,
                    "descricao": v.descricao,
                    "tipo": v.tipo,
                    "tamanho": v.tamanho,
                    "universo": anos_coletados(v),
                    "notas": "\n".join(t for t in (
                        v.notas or "", nota_descontinuada(v, tabela.ano_dicionario)) if t),
                    "categorias": [{"valor": str(c), "rotulo": t}
                                   for c, t in sorted(v.rotulos_valor.items())],
                    "aplicabilidade": v.notas_aplicabilidade,
                }
                for v in tabela.variaveis
            ],
        }
        for chave, tabela in tabelas.items()
    ]


def montar_questionario(tabela: str, pdf: Path, perguntas: list[dict]) -> dict:
    """Título = nome do arquivo sem o ano final ("Turma 2025" → "Turma")."""
    titulo = re.sub(r"\s*\d{4}$", "", pdf.stem).strip() or pdf.stem
    return {"id": tabela, "titulo": titulo, "perguntas": perguntas}


def gerar_censo_html(
    destino: Path,
    conceitos: list[dict],
    quadros: list[dict],
    questionarios: list[dict],
    dicionario: list[dict],
) -> Path:
    template = TEMPLATE.read_text(encoding="utf-8")
    if MARCADOR not in template:
        raise ValueError(f"Marcador {MARCADOR!r} não encontrado em {TEMPLATE}.")
    dados = {"conceitos": conceitos, "quadros": quadros,
             "questionarios": questionarios, "dicionario": dicionario}
    # "</" escapado para o JSON não fechar o <script> antes da hora.
    texto = json.dumps(dados, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(template.replace(MARCADOR, texto), encoding="utf-8")
    return destino
