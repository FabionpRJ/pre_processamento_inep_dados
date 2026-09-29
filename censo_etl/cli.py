"""Linha de comando.

    python -m censo_etl gerar [dicionario.xlsx] [pasta_saida] [pasta_questionarios] [caderno.pdf]
    python -m censo_etl criar-sav-vazio [pasta_json] [pasta_saida] [--tabelas ...]
    python -m censo_etl popular-sav [pasta_csv] [pasta_sav] [--modo {1,2}] [--tabelas ...]

Os scripts da raiz (gerar_json_metadata_editor.py, criar_sav_vazio.py,
popular_sav.py) repassam para cá, com os mesmos argumentos de antes.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from censo_etl.edicao import detectar_ano_em_cascata
from censo_etl.erros import EntradaInvalida
from censo_etl.insumos import classificar_nomes
from censo_etl.logs import registrar_saida
from censo_etl.tabelas import CHAVES


def _dicionario_no_diretorio_atual() -> Path | None:
    nome = classificar_nomes(p.name for p in Path(".").iterdir() if p.is_file()).dicionario
    return Path(nome) if nome else None


def _caderno_no_diretorio_atual() -> Path | None:
    nome = classificar_nomes(p.name for p in Path(".").glob("*.pdf")).caderno
    return Path(nome) if nome else None


def _gerar(args: argparse.Namespace) -> int:
    from censo_etl.pipeline import gerar_metadados

    dicionario = Path(args.dicionario) if args.dicionario else _dicionario_no_diretorio_atual()
    if dicionario is None:
        sys.exit("Informe o caminho do dicionário .xlsx:\n"
                 "    python -m censo_etl gerar dicionario.xlsx [pasta_saida] [pasta_questionarios] [caderno.pdf]")
    questionarios = Path(args.pasta_questionarios) if args.pasta_questionarios else None
    caderno = Path(args.caderno) if args.caderno else _caderno_no_diretorio_atual()
    pdfs = sorted(questionarios.glob("*.pdf")) if questionarios and questionarios.is_dir() else []
    ano = args.ano or detectar_ano_em_cascata(dicionario, [caderno, *pdfs])

    resultado = gerar_metadados(
        dicionario, Path(args.pasta_saida), questionarios, caderno, ano=ano,
        tabelas_alvo=args.tabelas, gerar_html=not args.sem_html,
        incluir_questionarios=not args.sem_questionarios_no_html,
    )
    print(f"\nConcluído: {len(resultado.jsons)} JSON(s), {len(resultado.avisos)} aviso(s).")
    return 0


def _criar_sav_vazio(args: argparse.Namespace) -> int:
    from censo_etl.sav.criar_vazio import executar

    pasta_json = Path(args.pasta_json)
    pasta_saida = Path(args.pasta_saida) if args.pasta_saida else pasta_json
    tabelas = args.tabelas or list(CHAVES)
    erros = executar(tabelas, pasta_json, pasta_saida)
    print(f"\nConcluído: {len(tabelas) - len(erros)}/{len(tabelas)} tabela(s).")
    if erros:
        print(f"Com erro: {', '.join(erros)}")
    return 1 if erros else 0


def _perguntar_modo() -> int:
    print("\nComo gerar os arquivos .sav?\n"
          "  [1] TODAS as colunas do dicionário (ausentes no CSV ficam vazias)\n"
          "  [2] Apenas as colunas disponíveis no CSV")
    while (resposta := input("Escolha [1/2]: ").strip()) not in ("1", "2"):
        print("Digite 1 ou 2.")
    return int(resposta)


def _popular_sav(args: argparse.Namespace) -> int:
    from censo_etl.sav.popular import MODOS, executar

    pasta_csv, pasta_sav = Path(args.pasta_csv), Path(args.pasta_sav)
    if not pasta_csv.is_dir():
        sys.exit(f'Pasta CSV não encontrada: "{pasta_csv.resolve()}"')
    if not pasta_sav.is_dir():
        sys.exit(f'Pasta SAV/JSON não encontrada: "{pasta_sav.resolve()}"')
    tabelas = args.tabelas or list(CHAVES)
    modo = args.modo or _perguntar_modo()
    print(f"Modo [{modo}] {MODOS[modo]}\nCSV : {pasta_csv.resolve()}\nSAV : {pasta_sav.resolve()}\n")
    erros = executar(tabelas, pasta_csv, pasta_sav, modo)
    print(f"\nConcluído: {len(tabelas) - len(erros)}/{len(tabelas)} tabela(s) gravada(s).")
    if erros:
        print(f"Com erro : {', '.join(erros)}")
    return 1 if erros else 0


def _argumento_tabelas(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tabelas", nargs="+", choices=CHAVES, metavar="TABELA",
                        help="Só estas tabelas. Opções: " + ", ".join(CHAVES))


def criar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m censo_etl",
                                     description="ETL de metadados do Censo Escolar (INEP).")
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("gerar", help="JSONs do Metadata Editor + censo.html + relatório")
    p.add_argument("dicionario", nargs="?", help="Dicionário .xlsx (padrão: o do diretório atual)")
    p.add_argument("pasta_saida", nargs="?", default="sav", help="Destino (padrão: ./sav)")
    p.add_argument("pasta_questionarios", nargs="?", help="Pasta com os questionários PDF")
    p.add_argument("caderno", nargs="?", help="Caderno de Conceitos PDF (padrão: o do diretório atual)")
    p.add_argument("--ano", help="Ano da edição (padrão: detectado pelos nomes dos insumos)")
    p.add_argument("--sem-html", action="store_true", help="Não gerar o censo.html")
    p.add_argument("--sem-questionarios-no-html", action="store_true",
                   help="Não incluir os questionários no censo.html")
    _argumento_tabelas(p)
    p.set_defaults(executar=_gerar)

    p = sub.add_parser("criar-sav-vazio", help=".sav vazios a partir dos JSONs")
    p.add_argument("pasta_json", nargs="?", default="sav", help="Pasta dos JSONs (padrão: ./sav)")
    p.add_argument("pasta_saida", nargs="?", help="Destino (padrão: a pasta dos JSONs)")
    _argumento_tabelas(p)
    p.set_defaults(executar=_criar_sav_vazio)

    p = sub.add_parser("popular-sav", help=".sav com os dados dos CSVs; regrava case_count")
    p.add_argument("pasta_csv", nargs="?", default="dados", help="Pasta dos CSVs (padrão: ./dados)")
    p.add_argument("pasta_sav", nargs="?", default="sav", help="Pasta dos JSONs e destino (padrão: ./sav)")
    p.add_argument("--modo", type=int, choices=[1, 2],
                   help="1 = todas as colunas; 2 = só as do CSV (sem a opção, pergunta)")
    _argumento_tabelas(p)
    p.set_defaults(executar=_popular_sav)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = criar_parser().parse_args(argv)
    registrar_saida(logging.StreamHandler(sys.stdout))
    try:
        return args.executar(args)
    except EntradaInvalida as exc:
        sys.exit(str(exc))
