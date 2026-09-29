"""Ano da edição e nomes dos artefatos de saída.

A saída segue a convenção da publicação do INEP, qualquer que seja o formato
do insumo:

    ceb2025_microdados_tabela_gestor_escolar_import_metadata_editor.json
    └┬┘└─┬┘ └────┬───┘ └────────┬──────────┘
     │   │       │              └─ Tabela.base_saida
     │   │       └─ fixo
     │   └─ ano da edição (vazio se não determinado — nunca inventado)
     └─ PREFIXO_EDICAO
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from censo_etl.leitura_csv import primeiras_linhas
from censo_etl.tabelas import POR_CHAVE

PREFIXO_EDICAO = "ceb"
ANO_VALIDO = range(1990, 2101)


def prefixo_edicao(ano: str | int | None) -> str:
    """`ceb2025_`, ou `ceb_` sem ano."""
    return f"{PREFIXO_EDICAO}{ano}_" if ano else f"{PREFIXO_EDICAO}_"


def nome_saida(tabela: str, ano: str | int | None) -> str:
    """Nome-base do artefato de uma tabela, ex. `ceb2025_microdados_tabela_gestor_escolar`."""
    base = POR_CHAVE[tabela].base_saida if tabela in POR_CHAVE else f"tabela_{tabela}"
    return f"{prefixo_edicao(ano)}microdados_{base}"


def nome_saida_json(tabela: str, ano: str | int | None) -> str:
    return f"{nome_saida(tabela, ano)}_import_metadata_editor.json"


def nome_saida_sav(tabela: str, ano: str | int | None) -> str:
    return f"{nome_saida(tabela, ano)}.sav"


def nome_censo_html(ano: str | int | None) -> str:
    return f"{prefixo_edicao(ano)}censo.html"


def nome_relatorio(ano: str | int | None) -> str:
    return f"{prefixo_edicao(ano)}relatorio_casamento.csv"


def ano_de_texto(texto: str) -> str | None:
    """Último ano plausível no texto."""
    achados = [a for a in re.findall(r"(?:19|20)\d{2}", str(texto)) if int(a) in ANO_VALIDO]
    return achados[-1] if achados else None


def ano_do_csv(caminho: Path) -> str | None:
    """Valor de `NU_ANO_CENSO` (ou coluna com `ANO_CENSO`) na 1ª linha de dados."""
    try:
        colunas, valores = primeiras_linhas(caminho)
    except OSError:
        return None
    for i, coluna in enumerate(colunas):
        if "ANO_CENSO" in coluna and i < len(valores):
            valor = valores[i]
            if valor.isdigit() and int(valor) in ANO_VALIDO:
                return valor
    return None


def detectar_ano_censo(pasta_csv: Path | None = None, nomes_extra=None) -> str | None:
    """Ano da edição, na ordem: `NU_ANO_CENSO` nos dados → nome dos CSVs →
    `nomes_extra`. Entre vários candidatos vence o mais frequente; sem nenhum,
    None."""
    candidatos: list[str] = []
    if pasta_csv and pasta_csv.is_dir():
        csvs = sorted(pasta_csv.rglob("*.csv"))
        candidatos = [a for c in csvs if (a := ano_do_csv(c))]
        if not candidatos:
            candidatos = [a for c in csvs if (a := ano_de_texto(c.stem))]
    if not candidatos:
        candidatos = [a for n in (nomes_extra or [])
                      if n and (a := ano_de_texto(Path(str(n)).stem))]
    if not candidatos:
        return None
    return Counter(candidatos).most_common(1)[0][0]


def detectar_ano_em_cascata(dicionario: Path, outros_nomes) -> str | None:
    """O dicionário decide sozinho; os demais insumos só entram se ele não tiver ano.

    Por maioria simples, um dicionário de 2026 com Caderno e questionários de
    2025 sairia carimbado 2025.
    """
    return (detectar_ano_censo(nomes_extra=[dicionario])
            or detectar_ano_censo(nomes_extra=list(outros_nomes)))
