"""Relatório de casamento: uma linha por variável, para revisão antes de publicar.

Boa parte dos metadados semânticos vem de casamento por similaridade; o
relatório mostra o que foi atribuído a cada variável e com que pontuação, e
quais códigos saíram de categoria (`88888=imputacao`).
"""
from __future__ import annotations

import csv
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from censo_etl.edicao import nome_relatorio

log = logging.getLogger(__name__)


@dataclass
class LinhaRelatorio:
    tabela: str
    variavel: str
    descricao: str
    conceito: str
    tem_var_txt: str          # "sim" ou ""
    questao: str
    score_questao: str        # 3 casas, vazio sem questão
    valores_especiais: str    # "88888=imputacao 9=nao_resposta"


COLUNAS = list(LinhaRelatorio.__dataclass_fields__)


def gravar_relatorio(linhas: list[LinhaRelatorio], pasta_saida: Path, ano: str | None) -> Path | None:
    """CSV `;` em utf-8-sig (abre direto no Excel pt-BR)."""
    if not linhas:
        return None
    caminho = pasta_saida / nome_relatorio(ano)
    try:
        with open(caminho, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=COLUNAS, delimiter=";")
            writer.writeheader()
            writer.writerows(asdict(linha) for linha in linhas)
    except OSError as exc:
        log.warning("Não foi possível gravar o relatório de casamento: %s", exc)
        return None
    return caminho
