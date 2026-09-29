"""Gravação de .sav: larguras e rótulos medidos em BYTES (docs/operacao.md)."""
import json
import random

import pandas as pd
import pyreadstat
import pytest

from censo_etl.dicionario import Variavel
from censo_etl.sav.criar_vazio import executar as criar_vazios
from censo_etl.sav.gravacao import (
    LIMITE_ROTULO_VALOR,
    LIMITE_ROTULO_VARIAVEL,
    construir_meta_sav,
    gravar_sav,
    largura_bytes_colunas,
    truncar,
)
from censo_etl.sav.metadados_json import atualizar_case_count, carregar_variaveis, nome_sav_do_json
from censo_etl.sav.popular import DISPONIVEIS, TODAS, montar_dataframe


@pytest.mark.parametrize("limite", [LIMITE_ROTULO_VARIAVEL, LIMITE_ROTULO_VALOR])
def test_truncar_por_bytes(limite):
    random.seed(0)
    alfabeto = "aeiouáéíóúãõçª…  "
    for _ in range(800):
        texto = "".join(random.choice(alfabeto) for _ in range(random.randint(0, 400)))
        cortado = truncar(texto, limite)
        assert len(cortado.encode("utf-8")) <= limite
        cortado.encode("utf-8").decode("utf-8")   # UTF-8 válido
        if len(texto.encode("utf-8")) <= limite:
            assert cortado == texto
        else:
            assert cortado.endswith("…")


def test_largura_declarada_nunca_menor_que_o_dado():
    df = pd.DataFrame({"NU_ENDERECO": ["2115 ET 4ª", None], "QT": [1.0, 2.0]})
    assert largura_bytes_colunas(df) == {"NU_ENDERECO": 11}
    var = Variavel(1, "NU_ENDERECO", "Número", "Char", 10)
    meta = construir_meta_sav([var], ["NU_ENDERECO", "QT"], largura_bytes_colunas(df))
    assert meta["variable_format"] == {"NU_ENDERECO": "A11"}
    assert meta["variable_measure"] == {"NU_ENDERECO": "unknown", "QT": "unknown"}


def _json(pasta, nome="ceb2025_microdados_tabela_gestor_escolar"):
    variaveis = [
        {"name": "CO_ENTIDADE", "labl": "Código", "loc_width": 8,
         "var_format": {"type": "numeric"}, "var_catgry_labels": []},
        {"name": "TP_SEXO", "labl": "Sexo " + "ã" * 200, "loc_width": 1,
         "var_format": {"type": "numeric"},
         "var_catgry_labels": [{"value": "1", "labl": "Masculino"}, {"value": "9", "labl": "Não informado"}]},
        {"name": "NO_X", "labl": "Nome", "loc_width": 5,
         "var_format": {"type": "character"}, "var_catgry_labels": []},
    ]
    caminho = pasta / f"{nome}_import_metadata_editor.json"
    caminho.write_text(json.dumps({"datafile": {"file_name": f"{nome}.sav", "case_count": 0},
                                   "variables": variaveis}))
    return caminho


def test_round_trip(tmp_path):
    caminho_json = _json(tmp_path)
    variaveis = carregar_variaveis(caminho_json)
    assert [v.tipo for v in variaveis] == ["Num", "Num", "Char"]
    assert variaveis[1].rotulos_valor == {1: "Masculino", 9: "Não informado"}
    df_csv = pd.DataFrame({"CO_ENTIDADE": ["1", "2"], "TP_SEXO": ["1", "9"], "EXTRA": ["a", "b"]})
    assert list(montar_dataframe(df_csv, variaveis, TODAS).columns) == ["CO_ENTIDADE", "TP_SEXO", "NO_X"]
    df = montar_dataframe(df_csv, variaveis, DISPONIVEIS)
    assert list(df.columns) == ["CO_ENTIDADE", "TP_SEXO", "EXTRA"]

    sav = tmp_path / nome_sav_do_json(caminho_json, "gestor")
    gravar_sav(df, sav, variaveis)
    lido, meta = pyreadstat.read_sav(str(sav))
    assert lido["TP_SEXO"].tolist() == [1.0, 9.0]
    assert meta.variable_value_labels["TP_SEXO"] == {1.0: "Masculino", 9.0: "Não informado"}
    assert meta.original_variable_types["CO_ENTIDADE"] == "F8.0"
    assert len(meta.column_labels[1].encode("utf-8")) <= LIMITE_ROTULO_VARIAVEL

    assert atualizar_case_count(caminho_json, 2)
    assert json.loads(caminho_json.read_text())["datafile"]["case_count"] == 2
    assert not atualizar_case_count(caminho_json, 2)


def test_criar_vazios(tmp_path):
    _json(tmp_path)
    assert criar_vazios(["gestor", "escola"], tmp_path, tmp_path) == ["escola"]   # escola sem JSON
    _, meta = pyreadstat.read_sav(str(tmp_path / "ceb2025_microdados_tabela_gestor_escolar.sav"))
    assert meta.number_rows == 0 and meta.column_names == ["CO_ENTIDADE", "TP_SEXO", "NO_X"]
