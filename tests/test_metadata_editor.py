from censo_etl.dicionario import TabelaDicionario, Variavel
from censo_etl.metadata_editor import (
    UNIVERSO_SEM_ANO,
    EnriquecimentoVariavel,
    anos_coletados,
    montar_datafile,
    montar_variavel,
    nota_descontinuada,
    opcoes_estatisticas,
    universo_publicacao,
)

EXTREMO = "registro com marcação de valor extremo (...)"


def var(nome, tipo="Num", tamanho=8, rotulos=None, **kw) -> Variavel:
    return Variavel(ordem=1, nome=nome, descricao=f"Descrição de {nome}", tipo=tipo,
                    tamanho=tamanho, rotulos_valor=rotulos or {}, **kw)


def estatisticas_marcadas(v):
    return {k for k, marcado in opcoes_estatisticas(v).items() if marcado}


def test_campos_na_ordem_do_metadata_editor():
    campos = list(montar_variavel(var("X"), 1, "F1", "U", "2025"))
    assert len(campos) == 35
    assert campos[:8] == ["uid", "sid", "fid", "vid", "name", "labl", "sort_order", "var_intrvl"]
    assert campos[-1] == "var_derivation"


def test_latitude():
    j = montar_variavel(var("LATITUDE", tamanho=20), 3, "F1", "U", "2025")
    assert j["var_format"]["data_format"] == "F20.6"
    assert j["loc_width"] == 20
    assert j["var_intrvl"] == j["interval_type"] == "contin"
    assert (j["uid"], j["vid"], j["sort_order"], j["sid"]) == ("3", "V3", "2", "1")


def test_quantidade_com_valor_extremo():
    v = var("QT_EQUIP_TV", rotulos={88888: EXTREMO})
    j = montar_variavel(v, 1, "F1", "U", "2025")
    assert j["var_invalrng"] == {"values": ["88888"]}
    assert j["var_catgry_labels"] == [{"value": "88888", "labl": EXTREMO}]   # rótulo preservado
    assert j["var_imputation"].startswith("Código 88888: marca de tratamento de consistência")
    assert estatisticas_marcadas(v) == {"missing", "vald", "min", "max", "mean", "stdev"}
    assert j["var_format"]["data_format"] == "F8.0"


def test_categorica_com_nao_informado():
    v = var("TP_DEPENDENCIA", tamanho=1, rotulos={1: "Federal", 8: "Área tradicional", 9: "Não informado"})
    j = montar_variavel(v, 1, "F1", "U", "2025")
    assert j["var_invalrng"] == {"values": ["9"]}
    assert estatisticas_marcadas(v) == {"missing", "vald", "freq"}
    assert j["var_intrvl"] == "discrete"


def test_cnpj_so_com_sem_declaracao_nao_pede_frequencia():
    v = var("NU_CNPJ_MANTENEDORA", tamanho=14, rotulos={99999999999999: "Sem declaração"})
    assert estatisticas_marcadas(v) == {"missing", "vald"}


def test_identificador_texto_e_data():
    assert estatisticas_marcadas(var("NO_ENTIDADE", "Char", 100)) == {"missing", "vald"}
    assert estatisticas_marcadas(var("CO_ENTIDADE")) == {"missing", "vald"}
    assert estatisticas_marcadas(var("NU_DIAS")) == {"missing", "vald"}
    assert estatisticas_marcadas(var("VL_X")) == {"missing", "vald", "min", "max", "mean", "stdev"}
    data = var("DT_INICIO", "Data", 10)
    assert estatisticas_marcadas(data) == {"missing", "vald", "min", "max"}
    fmt = montar_variavel(data, 1, "F1", "U", None)["var_format"]
    assert fmt == {"type": "character", "schema": "other", "readstat_type": "string",
                   "data_format": "A10", "is_date": True}
    assert montar_variavel(var("NO_X", "Char", None), 1, "F1", "U", None)["var_format"]["data_format"] == "A1"


def test_notas_anos_e_descontinuidade():
    v = var("DS_ENDERECO", "Char", 100, notas="Retirada por LGPD",
            anos_coleta={"2019": "s", "2024": "s", "2025": "n"})
    assert anos_coletados(v) == "Coletado em: 2019–2024"
    assert nota_descontinuada(v, "2025") == "Variável descontinuada no ano de 2025."
    assert nota_descontinuada(v, "2024") == ""
    assert nota_descontinuada(v, None) == ""
    j = montar_variavel(v, 1, "F1", "U", "2025")
    assert j["var_notes"] == ("Retirada por LGPD\nColetado em: 2019–2024\n"
                              "Variável descontinuada no ano de 2025.")
    assert anos_coletados(var("X", anos_coleta={"2025": "s"})) == "Coletado em 2025"


def test_enriquecimento_do_caderno_e_questionario():
    extra = EnriquecimentoVariavel(
        questao="1 - Qual a dependência?",
        caderno={"var_txt": "Definição", "var_destaque": "Importante! Atenção",
                 "var_qstn_ivuinstr": "Orientação"},
        conceito={"conceito": "DEPENDÊNCIA ADMINISTRATIVA"},
    )
    j = montar_variavel(var("TP_X"), 1, "F1", "U", None, extra)
    assert j["var_txt"] == "Definição"
    assert j["var_qstn_ivuinstr"] == "Orientação\nImportante! Atenção"
    assert j["var_concept"] == [[{"concept": "Dependência Administrativa", "vocab": "", "vocabURI": ""}]]
    assert j["var_qstn_qstnlit"] == "1 - Qual a dependência?"
    sem = montar_variavel(var("TP_X"), 1, "F1", "U", None)
    assert sem["var_txt"] == "Descrição de TP_X"
    assert sem["var_concept"] == [[]]
    assert sem["var_qstn_ivuinstr"] == ""


def test_universo_e_datafile():
    assert universo_publicacao("2025") == "Escola de Educação Básica declarada em 2025"
    assert universo_publicacao(None) == UNIVERSO_SEM_ANO
    tabela = TabelaDicionario("gestor", "Dicionário - Gestor", [var("A"), var("B")], "2025")
    assert montar_datafile(tabela, "2025") == {
        "file_id": "F5", "fid": "F5", "file_name": "ceb2025_microdados_tabela_gestor_escolar.sav",
        "labl": "Dicionário - Gestor", "var_count": 2, "case_count": 0,
    }
