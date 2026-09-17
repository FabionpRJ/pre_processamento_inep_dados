#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
popular_sav.py
============================================================================
Lê os CSVs do Censo Escolar e grava .sav populados com os dados,
preservando todos os metadados dos JSONs do dicionário.

Dois modos de geração:

  [1] TODAS as colunas — o .sav inclui todas as variáveis do dicionário;
      colunas ausentes no CSV ficam vazias (NaN para numéricas, "" para texto).

  [2] Apenas disponíveis — o .sav inclui somente as colunas presentes no CSV
      (mantém a ordem do dicionário; colunas extras do CSV vêm ao final).

FERRAMENTA STANDALONE. A interface (app.py) produz apenas metadados e não
chama mais este módulo. Como consequência, o `case_count` dos JSONs sai 0
do serviço: só quem lê os dados conhece o número de linhas, e é este módulo
que o regrava (ver `censo_lib.atualizar_case_count`).

USO (standalone)
----------------
    python popular_sav.py [pasta_csv] [pasta_sav] [--modo {1,2}] [--tabelas ...]

    pasta_csv   pasta com os .csv  (padrão: ./dados)
    pasta_sav   pasta com os .json e onde os .sav serão gravados (padrão: ./sav)

EXEMPLOS
--------
    python popular_sav.py
    python popular_sav.py --modo 2
    python popular_sav.py dados sav --modo 1 --tabelas escola turma

REQUISITOS
----------
    pip install pandas pyreadstat
============================================================================
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

import pandas as pd

from censo_lib import (
    TABELAS,
    atualizar_case_count, ler_csv, encontrar_json, carregar_metadados,
    gravar_sav, nome_sav_do_json, resolver_csvs,
)

# ---------------------------------------------------------------------------
# Montagem do DataFrame
# ---------------------------------------------------------------------------

def _coerce_coluna(serie: pd.Series, tipo: str) -> pd.Series:
    if tipo == "Num":
        return pd.to_numeric(serie, errors="coerce")
    return serie.fillna("").astype(str).replace("nan", "").replace("None", "")


def _inferir_coluna_extra(serie: pd.Series) -> pd.Series:
    """Para colunas do CSV sem metadado: tenta numérico; se falhar, mantém string."""
    num = pd.to_numeric(serie, errors="coerce")
    if num.notna().mean() >= 0.5:
        return num
    return serie.fillna("").astype(str).replace("nan", "").replace("None", "")


def montar_df_todos(df_csv: pd.DataFrame, variaveis: list[dict]) -> pd.DataFrame:
    """Modo 1: todas as variáveis do dicionário, na ordem do dicionário."""
    csv_cols = set(df_csv.columns)
    n = len(df_csv)
    df = pd.DataFrame(index=range(n))
    for var in variaveis:
        nome = var["nome_variavel"]
        tipo = var["tipo"]
        if nome in csv_cols:
            df[nome] = _coerce_coluna(df_csv[nome], tipo).values
        else:
            df[nome] = "" if tipo in ("Char", "Data") else float("nan")
    return df


def montar_df_disponivel(df_csv: pd.DataFrame, variaveis: list[dict]) -> pd.DataFrame:
    """Modo 2: apenas colunas presentes no CSV, respeitando a ordem do dicionário."""
    csv_cols      = set(df_csv.columns)
    meta_nomes    = [v["nome_variavel"] for v in variaveis]
    meta_por_nome = {v["nome_variavel"]: v for v in variaveis}
    em_comum      = [c for c in meta_nomes if c in csv_cols]
    set_meta      = set(meta_nomes)
    extras        = [c for c in df_csv.columns if c not in set_meta]

    n = len(df_csv)
    df = pd.DataFrame(index=range(n))
    for nome in em_comum:
        tipo = meta_por_nome[nome]["tipo"]
        df[nome] = _coerce_coluna(df_csv[nome], tipo).values
    for nome in extras:
        df[nome] = _inferir_coluna_extra(df_csv[nome]).values
    return df


# ---------------------------------------------------------------------------
# Relatório e processamento por tabela
# ---------------------------------------------------------------------------

def imprimir_resumo(nome: str, df_csv: pd.DataFrame, variaveis: list[dict]) -> None:
    meta_nomes = {v["nome_variavel"] for v in variaveis}
    csv_nomes  = set(df_csv.columns)
    ausentes   = sorted(meta_nomes - csv_nomes)
    extras     = sorted(csv_nomes - meta_nomes)
    em_ambos   = len(meta_nomes & csv_nomes)

    def lista(items: list[str], max_n: int = 6) -> str:
        amostra = ", ".join(items[:max_n])
        return amostra + (" ..." if len(items) > max_n else "")

    print(f"\n{'─'*60}")
    print(f"  {nome.upper()}")
    print(f"{'─'*60}")
    print(f"  Linhas no CSV           : {len(df_csv):>10,}")
    print(f"  Variáveis no dicionário : {len(variaveis):>10,}")
    print(f"  Colunas no CSV          : {len(df_csv.columns):>10,}")
    print(f"  Em comum                : {em_ambos:>10,}")
    if ausentes:
        print(f"  Ausentes no CSV ({len(ausentes):>3})    : {lista(ausentes)}")
    if extras:
        print(f"  Extras no CSV   ({len(extras):>3})    : {lista(extras)}")


def processar_tabela(
    nome: str,
    caminho_csv: Path,
    caminho_json: Path,
    caminho_sav: Path,
    modo: int,
) -> int:
    """Grava o .sav da tabela. Retorna o número de linhas gravadas."""
    print(f"\n[{nome}] Lendo CSV ... ", end="", flush=True)
    df_csv = ler_csv(caminho_csv)
    print(f"{len(df_csv):,} linhas · {len(df_csv.columns)} colunas")

    variaveis = carregar_metadados(caminho_json)
    imprimir_resumo(nome, df_csv, variaveis)

    if modo == 1:
        print(f"\n  Modo: TODAS as colunas ({len(variaveis)} variáveis)")
        df_final = montar_df_todos(df_csv, variaveis)
    else:
        meta_presentes = sum(1 for v in variaveis if v["nome_variavel"] in df_csv.columns)
        extras = len(df_csv.columns) - meta_presentes
        total  = meta_presentes + extras
        print(f"\n  Modo: apenas disponíveis ({meta_presentes} do dict + {extras} extras = {total} colunas)")
        df_final = montar_df_disponivel(df_csv, variaveis)

    print(f"  Gravando {caminho_sav} ... ", end="", flush=True)
    mb = gravar_sav(df_final, caminho_sav, variaveis)
    print(f"OK ({mb:.1f} MB)")

    # O JSON de importação nasce no passo 1, antes de existir qualquer linha,
    # com case_count = 0. Só aqui o total é conhecido.
    if atualizar_case_count(caminho_json, len(df_final)):
        print(f"  case_count atualizado para {len(df_final):,} em {caminho_json.name}")
    return len(df_final)


# ---------------------------------------------------------------------------
# API pública (usada por main.py)
# ---------------------------------------------------------------------------

def perguntar_modo() -> int:
    print("\n" + "="*60)
    print("  Como deseja gerar os arquivos .sav?")
    print("="*60)
    print("  [1] TODAS as colunas do dicionário")
    print("      (colunas ausentes no CSV ficam com valores vazios)")
    print()
    print("  [2] Apenas colunas disponíveis no CSV")
    print("      (colunas ausentes no dicionário ficam sem metadados)")
    print()
    while True:
        resp = input("  Escolha [1/2]: ").strip()
        if resp in ("1", "2"):
            return int(resp)
        print("  Digite 1 ou 2.")


def executar(
    tabelas_alvo: list[str],
    pasta_csv: Path,
    pasta_sav: Path,
    modo: int,
    progresso: Callable[[int, int, str], None] | None = None,
) -> list[str]:
    """Popula .sav com dados dos CSVs. Retorna lista de tabelas com erro.

    `progresso`, se informado, é chamado como (indice, total, tabela) antes de
    cada tabela. Este é o passo mais lento do pipeline (lê o CSV inteiro), por
    isso a interface acompanha tabela a tabela em vez de estimar o avanço.
    """
    pastas_json = [pasta_sav]
    pasta_alt = Path("saida_censo_escolar")
    if pasta_alt.is_dir():
        pastas_json.append(pasta_alt)

    # Os JSONs do passo 1 já trazem, por tabela, as variáveis que o dicionário
    # declara. Passá-las ao resolvedor habilita a identificação por CONTEÚDO:
    # se o nome do CSV não for reconhecível, o cabeçalho decide qual tabela é.
    jsons_por_tabela = {
        nome: caminho
        for nome in tabelas_alvo
        if (caminho := encontrar_json(nome, pastas_json)) is not None
    }
    variaveis_por_tabela: dict[str, set[str]] = {}
    for nome, caminho in jsons_por_tabela.items():
        try:
            variaveis_por_tabela[nome] = {
                v["nome_variavel"].strip().upper()
                for v in carregar_metadados(caminho) if v.get("nome_variavel")
            }
        except Exception as exc:
            print(f"[aviso] não foi possível ler as variáveis de {caminho.name}: {exc}")

    resolucao = resolver_csvs(pasta_csv, variaveis_por_tabela)
    csvs_por_tabela = resolucao["por_tabela"]
    for det in resolucao["detalhes"]:
        if det["camada"] == "conteudo" and det["conflito"]:
            print(f"[aviso] {det['arquivo']}: nome e cabeçalho discordam; "
                  f"vale o cabeçalho → {det['tabela']} ({det['pontos']:.2f}).")
    for p in resolucao["nao_resolvidos"]:
        print(f"[aviso] CSV não identificado, ignorado: {p.name}")

    fila: list[tuple[str, Path, Path]] = []
    for nome in tabelas_alvo:
        csv_path  = csvs_por_tabela.get(nome)
        json_path = jsons_por_tabela.get(nome)
        if csv_path is None:
            print(f"[aviso] CSV não encontrado — pulando {nome} (procurado em: {pasta_csv})")
            continue
        if json_path is None:
            print(f"[aviso] JSON não encontrado — pulando {nome} "
                  f"(buscado em: {', '.join(str(p) for p in pastas_json)})")
            continue
        fila.append((nome, csv_path, json_path))

    if not fila:
        print("Nenhum par CSV + JSON encontrado. Verifique os caminhos.")
        return tabelas_alvo

    erros: list[str] = []
    for i, (nome, csv_path, json_path) in enumerate(fila):
        if progresso:
            progresso(i, len(fila), nome)
        # Mesmo nome que o passo 2 gravou: vem do `datafile.file_name` do JSON.
        sav_path = pasta_sav / nome_sav_do_json(json_path, nome)
        try:
            processar_tabela(nome, csv_path, json_path, sav_path, modo)
        except Exception as exc:
            import traceback
            print(f"\n[ERRO] {nome}: {exc}")
            traceback.print_exc()
            erros.append(nome)

    return erros


# ---------------------------------------------------------------------------
# Ponto de entrada standalone
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Popula .sav do Censo Escolar com dados dos CSVs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "pasta_csv", nargs="?", default="dados",
        help="Pasta com os arquivos CSV (padrão: ./dados)",
    )
    parser.add_argument(
        "pasta_sav", nargs="?", default="sav",
        help="Pasta com os JSONs e destino dos .sav (padrão: ./sav)",
    )
    parser.add_argument(
        "--modo", type=int, choices=[1, 2],
        help="1 = todas as colunas; 2 = apenas disponíveis (omitir para escolher interativamente)",
    )
    parser.add_argument(
        "--tabelas", nargs="+", choices=list(TABELAS.keys()), metavar="TABELA",
        help="Processar apenas as tabelas indicadas. Opções: " + ", ".join(TABELAS),
    )
    args = parser.parse_args()

    pasta_csv = Path(args.pasta_csv)
    pasta_sav = Path(args.pasta_sav)

    if not pasta_csv.is_dir():
        sys.exit(f'Pasta CSV não encontrada: "{pasta_csv.resolve()}"')
    if not pasta_sav.is_dir():
        sys.exit(f'Pasta SAV/JSON não encontrada: "{pasta_sav.resolve()}"')

    tabelas_alvo = args.tabelas or list(TABELAS.keys())
    modo = args.modo if args.modo else perguntar_modo()
    descricao_modo = "TODAS as colunas" if modo == 1 else "Apenas disponíveis"
    print(f"\nModo selecionado: [{modo}] {descricao_modo}")
    print(f"CSV : {pasta_csv.resolve()}")
    print(f"SAV : {pasta_sav.resolve()}\n")

    erros = executar(tabelas_alvo, pasta_csv, pasta_sav, modo)

    print(f"\n{'='*60}")
    concluidos = len(tabelas_alvo) - len(erros)
    print(f"Concluído: {concluidos}/{len(tabelas_alvo)} tabela(s) gravada(s).")
    if erros:
        print(f"Com erro : {', '.join(erros)}")
    print(f"Destino  : {pasta_sav.resolve()}")


if __name__ == "__main__":
    main()
