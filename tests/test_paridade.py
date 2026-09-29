"""Paridade com a saída de referência capturada do código anterior à refatoração.

Precisa dos insumos em exemplo_input/ e da referência em
OUTROS/referencia/saida/ (ambos fora do Git); sem eles, é pulado.

    pytest -m lento tests/test_paridade.py
"""
import logging
import shutil

import pytest
from comparacao import comparar
from conftest import INSUMOS, RAIZ

from censo_etl.edicao import detectar_ano_em_cascata
from censo_etl.insumos import localizar_insumos
from censo_etl.logs import registrar_saida, remover_saida
from censo_etl.pipeline import gerar_metadados

REFERENCIA = RAIZ / "OUTROS" / "referencia" / "saida"

pytestmark = [
    pytest.mark.lento,
    pytest.mark.insumos,
    pytest.mark.skipif(not (INSUMOS.is_dir() and REFERENCIA.is_dir()),
                       reason="insumos ou referência ausentes"),
]


def _cenarios():
    ins = localizar_insumos(INSUMOS)
    q, c = ins.pasta_questionarios, ins.caderno
    ano = detectar_ano_em_cascata(ins.dicionario, [c, *sorted(q.glob("*.pdf"))])
    completo = dict(pasta_questionarios=q, caminho_caderno=c, ano=ano)
    return ins.dicionario, {
        "completo": completo,
        "so_dicionario": dict(ano=None),
        "sem_caderno": dict(pasta_questionarios=q, ano=ano),
        "sem_questionarios": dict(caminho_caderno=c, ano=ano),
        "recorte_2_tabelas": {**completo, "tabelas_alvo": ["gestor", "curso_tecnico"]},
        "sem_html": {**completo, "gerar_html": False},
        "html_sem_questionarios": {**completo, "incluir_questionarios": False},
    }


def _rodar(dicionario, destino, vezes=1, **kwargs):
    shutil.rmtree(destino, ignore_errors=True)
    destino.mkdir(parents=True)
    with open(destino / "_log.txt", "w", encoding="utf-8") as log:
        handler = registrar_saida(logging.StreamHandler(log))
        try:
            for _ in range(vezes):
                gerar_metadados(dicionario, destino, **kwargs)
        finally:
            remover_saida(handler)


@pytest.mark.parametrize("cenario", [
    "completo", "so_dicionario", "sem_caderno", "sem_questionarios",
    "recorte_2_tabelas", "sem_html", "html_sem_questionarios", "completo_cache",
])
def test_paridade(cenario, tmp_path):
    dicionario, cenarios = _cenarios()
    if cenario == "completo_cache":   # 2ª execução na mesma pasta reaproveita os caches
        _rodar(dicionario, tmp_path / cenario, vezes=2, **cenarios["completo"])
    else:
        _rodar(dicionario, tmp_path / cenario, **cenarios[cenario])
    assert comparar(REFERENCIA, tmp_path, somente={cenario}) == []
