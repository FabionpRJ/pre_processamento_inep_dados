"""`.sav` vazios (0 linhas) com a estrutura e os metadados de cada JSON."""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import pandas as pd

from censo_etl.dicionario import Variavel
from censo_etl.sav.gravacao import gravar_sav
from censo_etl.sav.metadados_json import carregar_variaveis, encontrar_json, nome_sav_do_json

log = logging.getLogger(__name__)
Progresso = Callable[[int, int, str], None]


def dataframe_vazio(variaveis: list[Variavel]) -> pd.DataFrame:
    return pd.concat({
        v.nome: pd.Series(dtype="object" if v.tipo in ("Char", "Data") else "float64")
        for v in variaveis
    }, axis=1)


def criar_tabela(tabela: str, caminho_json: Path, pasta_saida: Path) -> Path:
    variaveis = carregar_variaveis(caminho_json)
    pasta_saida.mkdir(parents=True, exist_ok=True)
    caminho_sav = pasta_saida / nome_sav_do_json(caminho_json, tabela)
    mb = gravar_sav(dataframe_vazio(variaveis), caminho_sav, variaveis)
    log.info("  [%s] %s OK (%.1f MB, %d variáveis, 0 linhas)", tabela, caminho_sav, mb, len(variaveis))
    return caminho_sav


def executar(tabelas: list[str], pasta_json: Path, pasta_saida: Path,
             progresso: Progresso | None = None) -> list[str]:
    """Cria um `.sav` vazio por tabela. Devolve as tabelas com erro.

    `progresso(indice, total, tabela)` é chamado antes de cada tabela.
    """
    erros: list[str] = []
    for i, tabela in enumerate(tabelas):
        if progresso:
            progresso(i, len(tabelas), tabela)
        caminho_json = encontrar_json(tabela, pasta_json)
        if caminho_json is None:
            log.warning("JSON não encontrado para %s — pulando.", tabela)
            erros.append(tabela)
            continue
        try:
            criar_tabela(tabela, caminho_json, pasta_saida)
        except Exception:
            log.exception("Falha ao gravar %s", tabela)
            erros.append(tabela)
    return erros
