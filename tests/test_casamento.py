from censo_etl.casamento import (
    mapear_conceitos_por_variavel,
    mapear_secoes_por_variavel,
    melhor_questao,
    pontuar_conceito,
    rotulo_conceito,
)
from censo_etl.dicionario import Variavel


def v(nome, descricao):
    return Variavel(1, nome, descricao, "Num", 1)


def test_melhor_questao():
    questoes = ["Nome completo da escola", "Dependência administrativa da escola", "Possui biblioteca"]
    assert melhor_questao("Dependência administrativa", questoes)[0] == "Dependência administrativa da escola"
    assert melhor_questao("Quantidade de computadores", questoes) == ("", 0.0)
    assert melhor_questao("", questoes) == ("", 0.0)


def test_pontuar_conceito_prefixo_igual():
    assert pontuar_conceito("Localização diferenciada - área de assentamento", "LOCALIZAÇÃO DIFERENCIADA") >= 0.85
    assert pontuar_conceito("Quantidade de salas", "MANTENEDORA") == 0.0


def test_rotulo_conceito():
    assert rotulo_conceito("DEPENDÊNCIA ADMINISTRATIVA DA ESCOLA") == "Dependência Administrativa da Escola"
    assert rotulo_conceito(" Já formatado ") == "Já formatado"


def test_mapas():
    secoes = {"escola": {"conceitos": [("DEPENDÊNCIA ADMINISTRATIVA", "Definição", "Importante! x")],
                         "orientacoes": [("DEPENDÊNCIA ADMINISTRATIVA", "Orientação")]}}
    variaveis = {"escola": [v("TP_DEPENDENCIA", "Dependência administrativa")],
                 "matricula": [v("QT_MAT", "Dependência administrativa")]}
    assert mapear_secoes_por_variavel(secoes, variaveis) == {"escola": {"TP_DEPENDENCIA": {
        "var_txt": "Definição", "var_destaque": "Importante! x", "var_qstn_ivuinstr": "Orientação"}}}
    conceito = {"conceito": "DEPENDÊNCIA ADMINISTRATIVA"}
    assert mapear_conceitos_por_variavel([conceito], variaveis) == {
        "escola": {"TP_DEPENDENCIA": conceito}, "matricula": {"QT_MAT": conceito}}
    assert mapear_conceitos_por_variavel([], variaveis) == {}
