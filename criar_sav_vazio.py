#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
criar_sav_vazio.py
============================================================================
Cria arquivos .sav vazios (0 linhas) com todas as variáveis e metadados
do dicionário: rótulos de variável/valor, tipos e formatos.

Útil para registrar a estrutura completa no Metadata Editor antes de
popular os arquivos com dados.

USO (standalone)
----------------
    python criar_sav_vazio.py                        # JSONs e .sav em ./sav
    python criar_sav_vazio.py pasta_json
    python criar_sav_vazio.py pasta_json pasta_saida
    python criar_sav_vazio.py sav --tabelas escola turma

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
    TABELAS, NOME_TABELA,
    encontrar_json, carregar_metadados, gravar_sav,
)

# ---------------------------------------------------------------------------
# Lógica principal
# ---------------------------------------------------------------------------

def montar_df_vazio(variaveis: list[dict]) -> pd.DataFrame:
    colunas = {
        var["nome_variavel"]: pd.Series(dtype="object" if var["tipo"] in ("Char", "Data") else "float64")
        for var in variaveis
    }
    return pd.concat(colunas, axis=1)


def criar_sav_vazio_tabela(nome: str, caminho_json: Path, pasta_saida: Path) -> Path:
    variaveis = carregar_metadados(caminho_json)
    df = montar_df_vazio(variaveis)
    pasta_saida.mkdir(parents=True, exist_ok=True)
    caminho_sav = pasta_saida / f"{NOME_TABELA[nome]}.sav"
    print(f"  [{nome}] Gravando {caminho_sav} ... ", end="", flush=True)
    mb = gravar_sav(df, caminho_sav, variaveis)
    print(f"OK ({mb:.1f} MB, {len(variaveis)} variáveis, 0 linhas)")
    return caminho_sav


# ---------------------------------------------------------------------------
# API pública (usada por main.py)
# ---------------------------------------------------------------------------

def executar(
    tabelas_alvo: list[str],
    pasta_json: Path,
    pasta_saida: Path,
    progresso: Callable[[int, int, str], None] | None = None,
) -> list[str]:
    """Cria .sav vazios para cada tabela. Retorna lista de tabelas com erro.

    `progresso`, se informado, é chamado como (indice, total, tabela) antes de
    cada tabela — usado pela interface para mostrar avanço real, e não estimado.
    """
    pastas_json = [pasta_json]
    pasta_alt = Path("saida_censo_escolar")
    if pasta_alt.is_dir():
        pastas_json.append(pasta_alt)

    erros: list[str] = []
    total = len(tabelas_alvo)
    for i, nome in enumerate(tabelas_alvo):
        if progresso:
            progresso(i, total, nome)
        json_path = encontrar_json(nome, pastas_json)
        if json_path is None:
            print(f"[aviso] JSON não encontrado para {nome} — pulando.")
            erros.append(nome)
            continue
        try:
            criar_sav_vazio_tabela(nome, json_path, pasta_saida)
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
        description="Cria .sav vazios com metadados do dicionário.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "pasta_json", nargs="?", default="sav",
        help="Pasta com os JSONs de metadados (padrão: ./sav)",
    )
    parser.add_argument(
        "pasta_saida", nargs="?", default=None,
        help="Destino dos .sav (padrão: mesma que pasta_json)",
    )
    parser.add_argument(
        "--tabelas", nargs="+", choices=list(TABELAS.keys()), metavar="TABELA",
        help="Processar apenas as tabelas indicadas. Opções: " + ", ".join(TABELAS),
    )
    args = parser.parse_args()

    pasta_json  = Path(args.pasta_json)
    pasta_saida = Path(args.pasta_saida) if args.pasta_saida else pasta_json
    tabelas_alvo = args.tabelas or list(TABELAS.keys())

    print(f"JSON : {pasta_json.resolve()}")
    print(f"SAV  : {pasta_saida.resolve()}")

    erros = executar(tabelas_alvo, pasta_json, pasta_saida)

    print(f"\nConcluído: {len(tabelas_alvo) - len(erros)}/{len(tabelas_alvo)} tabela(s).")
    if erros:
        print(f"Com erro: {', '.join(erros)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
