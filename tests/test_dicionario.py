from censo_etl.dicionario import ler_dicionario, parse_categoria, tabelas_do_dicionario


def test_parse_categoria():
    rotulos, notas = parse_categoria(
        "1 - Federal\n2 - Estadual\n  e Municipal\n- Não se aplica a extintas\n-1 - Negativo\n\n")
    assert rotulos == {1: "Federal", 2: "Estadual e Municipal", -1: "Negativo"}
    assert notas == ["Não se aplica a extintas"]


def test_parse_categoria_texto_solto_vira_nota():
    assert parse_categoria("Texto livre\ncontinua") == ({}, ["Texto livre continua"])
    assert parse_categoria(None) == ({}, [])


def test_ler_dicionario(dicionario_minimo, caplog):
    tabelas = ler_dicionario(dicionario_minimo)
    assert list(tabelas) == ["escola"]
    assert "Legenda" in caplog.text
    escola = tabelas["escola"]
    assert escola.titulo == "Dicionário de Variáveis - Tabela de Escola"
    assert escola.ano_dicionario == "2025"
    nomes = [v.nome for v in escola.variaveis]
    assert nomes == ["NU_ANO_CENSO", "TP_DEPENDENCIA", "DS_ENDERECO", "LATITUDE"]
    tp = escola.variaveis[1]
    assert tp.descricao == "Dependência"
    assert tp.rotulos_valor == {1: "Federal", 2: "Estadual continuação", 9: "Não informado"}
    assert tp.anos_coleta == {"2024": "s", "2025": "s"}
    assert tp.notas == "Nota importante"
    assert escola.variaveis[0].descricao == "Ano do Censo"
    assert escola.variaveis[2].notas_aplicabilidade == ["Não se aplica a escolas extintas"]
    assert escola.variaveis[3].anos_coleta == {"2024": None, "2025": "s"}


def test_tabelas_do_dicionario(dicionario_minimo):
    assert tabelas_do_dicionario(dicionario_minimo) == ["escola"]
    assert tabelas_do_dicionario(dicionario_minimo.read_bytes()) == ["escola"]
    with open(dicionario_minimo, "rb") as fh:
        assert tabelas_do_dicionario(fh) == ["escola"]
    assert tabelas_do_dicionario(b"isto nao e um xlsx") == []
