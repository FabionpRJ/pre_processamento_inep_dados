"""Códigos especiais do dicionário: o RÓTULO decide, nunca o número.

O caso crítico é o par 8/9 de largura 1 no dicionário de 2025: o 8 é categoria
real e o 9 é "Não informado".
"""
import pytest

from censo_etl.valores_especiais import (
    IMPUTACAO,
    NAO_RESPOSTA,
    classificar_codigo_especial,
    descrever_imputacao,
    parece_sentinela,
    separar_codigos_especiais,
)

REAIS_2025 = {
    "registro com marcação de valor extremo (valor superior ao limite máximo de "
    "4 equipamentos para cada 3 salas existentes - foram marcados apenas valores>3)": IMPUTACAO,
    "registro com marcação de valor extremo (valor superior ao limite máximo* "
    "definido com base na distribuição da razão de profissionais por matrícula)": IMPUTACAO,
    "Sem declaração": NAO_RESPOSTA,
    "Não informado": NAO_RESPOSTA,
    # categorias reais que convivem com as de cima
    "Área onde se localizam povos e comunidades tradicionais": None,
    "Federal": None,
    "Estadual e Municipal": None,
    "A escola não está em área de localização diferenciada": None,
    "Não": None,
    "Não oferece": None,
    "Não exclusivamente": None,
    "Não há rede local interligando computadores": None,
    "A escola não possui projeto político pedagógico/proposta pedagógica": None,
}

OUTRAS_REDACOES = {
    "Valor extremo": IMPUTACAO,
    "VALORES EXTREMOS TRATADOS": IMPUTACAO,
    "valor imputado pelo Inep": IMPUTACAO,
    "Registro submetido a imputação": IMPUTACAO,
    "marcado com o código 8888": IMPUTACAO,
    "outlier identificado na crítica de consistência": IMPUTACAO,
    "valor substituído por marcação de consistência": IMPUTACAO,
    "Não declarado": NAO_RESPOSTA,
    "Não respondeu": NAO_RESPOSTA,
    "Sem informação": NAO_RESPOSTA,
    "Sem resposta": NAO_RESPOSTA,
    "Não aplicável": NAO_RESPOSTA,
    "Não se aplica": NAO_RESPOSTA,
    "Ignorado": NAO_RESPOSTA,
    "NÃO INFORMADA": NAO_RESPOSTA,
    "Não consta": NAO_RESPOSTA,
    "Ensino Regular": None,
    "Urbana": None,
    "Sim": None,
    "Não possui": None,
    "Extinta em Anos Anteriores": None,
    "": None,
}


@pytest.mark.parametrize("rotulo, esperado", {**REAIS_2025, **OUTRAS_REDACOES}.items())
def test_classificacao_pelo_rotulo(rotulo, esperado):
    assert classificar_codigo_especial(rotulo) == esperado


@pytest.mark.parametrize("variante", ["Não informado", "NAO INFORMADO", "nao informado", "  Não   informado  "])
def test_insensivel_a_caixa_acento_e_espaco(variante):
    assert classificar_codigo_especial(variante) == NAO_RESPOSTA


def test_imputacao_tem_precedencia():
    assert classificar_codigo_especial("valor extremo, sem informação do valor original") == IMPUTACAO


def test_separacao_qt_so_com_valor_extremo():
    rotulo = "registro com marcação de valor extremo (...)"
    assert separar_codigos_especiais({88888: rotulo}) == ({}, {88888: (IMPUTACAO, rotulo)})


def test_separacao_tp_com_nao_informado():
    reais, especiais = separar_codigos_especiais(
        {1: "Federal", 2: "Estadual", 3: "Municipal", 8: "Área tradicional", 9: "Não informado"})
    assert sorted(reais) == [1, 2, 3, 8]
    assert especiais == {9: (NAO_RESPOSTA, "Não informado")}


def test_separacao_vazia():
    assert separar_codigos_especiais({}) == ({}, {})
    assert separar_codigos_especiais(None) == ({}, {})


def test_var_imputation_descreve_todos_os_tipos():
    texto = descrever_imputacao({
        88888: (IMPUTACAO, "registro com marcação de valor extremo"),
        9: (NAO_RESPOSTA, "Não informado"),
    })
    assert texto == (
        "Código 9: marca de ausência de declaração atribuída pelo produtor; "
        "no dicionário de variáveis, “Não informado”. "
        "Código 88888: marca de tratamento de consistência aplicada pelo produtor; "
        "no dicionário de variáveis, “registro com marcação de valor extremo”."
    )
    assert "var_invalrng" not in texto


def test_var_imputation_so_nao_resposta_e_vazio():
    assert descrever_imputacao({9: (NAO_RESPOSTA, "Não informado")}).startswith("Código 9: ")
    assert descrever_imputacao({}) == ""
    assert descrever_imputacao(None) == ""


@pytest.mark.parametrize("codigo", [88, 99, 888, 999, 8888, 88888, 99999999999999, -99, "8888"])
def test_parece_sentinela(codigo):
    assert parece_sentinela(codigo)


@pytest.mark.parametrize("codigo", [0, 1, 8, 9, -8, 12, 89, 98, 980, 899, 100, 2025])
def test_nao_parece_sentinela(codigo):
    assert not parece_sentinela(codigo)
