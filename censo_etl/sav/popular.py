"""`.sav` com os dados dos CSVs e os metadados dos JSONs; regrava `case_count`.

Modos de coluna:
  1 (TODAS)       — todas as variáveis do dicionário; ausentes no CSV ficam vazias.
  2 (DISPONIVEIS) — só as colunas do CSV, na ordem do dicionário; extras no fim.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import pandas as pd

from censo_etl.dicionario import Variavel
from censo_etl.leitura_csv import detectar_delimitador, detectar_encoding, resolver_csvs
from censo_etl.sav.gravacao import gravar_sav
from censo_etl.sav.metadados_json import (
    atualizar_case_count,
    carregar_variaveis,
    encontrar_json,
    nome_sav_do_json,
)

log = logging.getLogger(__name__)
Progresso = Callable[[int, int, str], None]

TODAS, DISPONIVEIS = 1, 2
MODOS = {TODAS: "TODAS as colunas", DISPONIVEIS: "Apenas disponíveis"}


def ler_csv(caminho: Path) -> pd.DataFrame:
    """Tudo como texto: a tipagem vem do dicionário."""
    encoding = detectar_encoding(caminho)
    return pd.read_csv(caminho, sep=detectar_delimitador(caminho, encoding), encoding=encoding,
                       low_memory=False, dtype=str)


def _como_texto(serie: pd.Series) -> pd.Series:
    return serie.fillna("").astype(str).replace("nan", "").replace("None", "")


def _converter(serie: pd.Series, tipo: str) -> pd.Series:
    return pd.to_numeric(serie, errors="coerce") if tipo == "Num" else _como_texto(serie)


def _inferir(serie: pd.Series) -> pd.Series:
    """Coluna do CSV sem metadado: numérica se ao menos metade converter."""
    numerica = pd.to_numeric(serie, errors="coerce")
    return numerica if numerica.notna().mean() >= 0.5 else _como_texto(serie)


def montar_dataframe(df_csv: pd.DataFrame, variaveis: list[Variavel], modo: int) -> pd.DataFrame:
    colunas_csv = set(df_csv.columns)
    df = pd.DataFrame(index=range(len(df_csv)))
    if modo == TODAS:
        for v in variaveis:
            if v.nome in colunas_csv:
                df[v.nome] = _converter(df_csv[v.nome], v.tipo).values
            else:
                df[v.nome] = "" if v.tipo in ("Char", "Data") else float("nan")
        return df
    nomes = {v.nome for v in variaveis}
    for v in variaveis:
        if v.nome in colunas_csv:
            df[v.nome] = _converter(df_csv[v.nome], v.tipo).values
    for nome in df_csv.columns:
        if nome not in nomes:
            df[nome] = _inferir(df_csv[nome]).values
    return df


def _resumo(tabela: str, df_csv: pd.DataFrame, variaveis: list[Variavel]) -> None:
    nomes_dic = {v.nome for v in variaveis}
    nomes_csv = set(df_csv.columns)

    def amostra(itens: list[str]) -> str:
        return ", ".join(itens[:6]) + (" ..." if len(itens) > 6 else "")

    log.info("  %s: %s linhas no CSV · %d variáveis no dicionário · %d colunas no CSV · %d em comum",
             tabela.upper(), f"{len(df_csv):,}", len(variaveis), len(nomes_csv), len(nomes_dic & nomes_csv))
    if ausentes := sorted(nomes_dic - nomes_csv):
        log.info("    Ausentes no CSV (%d): %s", len(ausentes), amostra(ausentes))
    if extras := sorted(nomes_csv - nomes_dic):
        log.info("    Extras no CSV (%d): %s", len(extras), amostra(extras))


def popular_tabela(tabela: str, caminho_csv: Path, caminho_json: Path, caminho_sav: Path, modo: int) -> int:
    """Grava o `.sav` da tabela e devolve o número de linhas."""
    log.info("[%s] Lendo %s ...", tabela, caminho_csv.name)
    df_csv = ler_csv(caminho_csv)
    variaveis = carregar_variaveis(caminho_json)
    _resumo(tabela, df_csv, variaveis)
    df = montar_dataframe(df_csv, variaveis, modo)
    log.info("  Modo %d (%s): %d colunas", modo, MODOS[modo], len(df.columns))
    mb = gravar_sav(df, caminho_sav, variaveis)
    log.info("  %s OK (%.1f MB)", caminho_sav, mb)
    if atualizar_case_count(caminho_json, len(df)):
        log.info("  case_count atualizado para %s em %s", f"{len(df):,}", caminho_json.name)
    return len(df)


def executar(tabelas: list[str], pasta_csv: Path, pasta_sav: Path, modo: int,
             progresso: Progresso | None = None) -> list[str]:
    """Popula um `.sav` por tabela a partir dos JSONs em `pasta_sav`. Devolve as
    tabelas com erro. Os CSVs são identificados por nome e, se preciso, pelo
    cabeçalho comparado às variáveis de cada JSON."""
    jsons = {t: c for t in tabelas if (c := encontrar_json(t, pasta_sav)) is not None}
    variaveis_por_tabela: dict[str, set[str]] = {}
    for tabela, caminho in jsons.items():
        try:
            variaveis_por_tabela[tabela] = {v.nome.strip().upper() for v in carregar_variaveis(caminho) if v.nome}
        except Exception as exc:
            log.warning("Não foi possível ler as variáveis de %s: %s", caminho.name, exc)

    resolucao = resolver_csvs(pasta_csv, variaveis_por_tabela)
    for det in resolucao.detalhes:
        if det.conflito:
            log.warning("%s: nome e cabeçalho discordam; vale o cabeçalho → %s (%.2f).",
                        det.arquivo.name, det.tabela, det.pontos)
    for caminho in resolucao.nao_resolvidos:
        log.warning("CSV não identificado, ignorado: %s", caminho.name)

    fila: list[tuple[str, Path, Path]] = []
    for tabela in tabelas:
        if (csv := resolucao.por_tabela.get(tabela)) is None:
            log.warning("CSV não encontrado — pulando %s (procurado em: %s)", tabela, pasta_csv)
        elif (caminho_json := jsons.get(tabela)) is None:
            log.warning("JSON não encontrado — pulando %s (procurado em: %s)", tabela, pasta_sav)
        else:
            fila.append((tabela, csv, caminho_json))
    if not fila:
        log.error("Nenhum par CSV + JSON encontrado. Verifique os caminhos.")
        return list(tabelas)

    erros: list[str] = []
    for i, (tabela, csv, caminho_json) in enumerate(fila):
        if progresso:
            progresso(i, len(fila), tabela)
        try:
            popular_tabela(tabela, csv, caminho_json, pasta_sav / nome_sav_do_json(caminho_json, tabela), modo)
        except Exception:
            log.exception("Falha ao gravar %s", tabela)
            erros.append(tabela)
    return erros
