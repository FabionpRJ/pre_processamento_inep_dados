"""Identificação de insumos pelo nome e pelo conteúdo, e nomes de saída.

Casos tirados das duas publicações reais do Censo 2025 mais variações hostis.
Uma mudança de convenção do INEP que o sistema não absorva quebra aqui.
"""
import pytest

from censo_etl.edicao import nome_saida, nome_saida_json, nome_saida_sav, prefixo_edicao
from censo_etl.insumos import classificar_nomes
from censo_etl.leitura_csv import identificar_tabela_por_cabecalho
from censo_etl.nomes import (
    ASSINATURA_QUESTIONARIO,
    ASSINATURA_TABELA,
    LIMIAR_CADERNO,
    identificar_questionario,
    identificar_tabela,
    pontuar_caderno,
    tokens_arquivo,
)
from censo_etl.tabelas import CHAVES, POR_CHAVE

CSVS = {
    # publicação "Anexos/"
    "Tabela_Escola_2025.csv": "escola",
    "Tabela_Matricula_2025.csv": "matricula",
    "Tabela_Docente_2025.csv": "docente",
    "Tabela_Turma_2025.csv": "turma",
    "Tabela_Gestor_Escolar_2025.csv": "gestor",
    "Tabela_Curso_Tecnico_2025.csv": "curso_tecnico",
    # publicação "ceb2025_CSV" — ano no prefixo
    "ceb2025_microdados_tabela_escola.csv": "escola",
    "ceb2025_microdados_tabela_matricula.csv": "matricula",
    "ceb2025_microdados_tabela_docente.csv": "docente",
    "ceb2025_microdados_tabela_turma.csv": "turma",
    "ceb2025_microdados_tabela_gestor_escolar.csv": "gestor",
    "ceb2025_microdados_tabela_curso_tecnico.csv": "curso_tecnico",
    # marcadores de republicação, em qualquer posição
    "Tabela_Curso_Tecnico_2025_V2.csv": "curso_tecnico",
    "Tabela_Escola_2025_retificada_V3.csv": "escola",
    "ceb2026_microdados_tabela_escola_retificado.csv": "escola",
    "Tabela_Escola_V2_2025.csv": "escola",
    # caixa, acento, separador e plural
    "TABELA_DE_MATRÍCULAS_2027.CSV": "matricula",
    "tabela de curso técnico 2026.csv": "curso_tecnico",
    "Base_Docentes_2030.csv": "docente",
    # abas do dicionário
    "Tabela_de_Escola": "escola",
    "Tabela_Curso_Técnico ": "curso_tecnico",
    "Tabela_de_Gestor": "gestor",
    # não são tabelas do Censo
    "md5_microdados_ed_basica_2025.txt": None,
    "Tabela_Curso_Superior_2025.csv": None,
    "leia-me.csv": None,
}

QUESTIONARIOS = {
    "Escola 2025.pdf": "escola",
    "Aluno 2025.pdf": "matricula",
    "Profissional Escolar 2025.pdf": "docente",
    "Turma 2025.pdf": "turma",
    "Gestor Escolar 2025.pdf": "gestor",
    "ceb2025_quest_escola.pdf": "escola",
    "ceb2025_quest_aluno.pdf": "matricula",
    "ceb2025_quest_profissional_escolar.pdf": "docente",
    "ceb2025_quest_turma.pdf": "turma",
    "ceb2025_quest_gestor_escolar.pdf": "gestor",
    # outro formulário, que só menciona a escola
    "Cadastro Escola Nova 2025.pdf": None,
    "ceb2025_quest_cadastro_escola_nova.pdf": None,
}

CADERNOS_SIM = [
    "Caderno de Conceitos e Orientações do Censo Escolar de 2025.pdf",
    "ceb2025_cadastro_de_conceitos_e_orientacoes_do_censo.pdf",   # erro de digitação da fonte
    "caderno_de_conceitos_2026.pdf",
]
CADERNOS_NAO = [
    "Leia-me.pdf",
    "ceb2025_leia-me.pdf",
    "Nota Técnica nº 5 de 2021 - Recomendações do Termo de Execução Descentralizada nº 8750.pdf",
    "Parecer Jurídico da Procuradoria Federal Especializada junto ao Inep (Projur) sobre a divulgação dos Microdados.pdf",
    "RIP Relatório de Impacto à Proteção de Dados Pessoais dos Censos Educacionais.pdf",
    "Escola 2025.pdf",
]

PACOTE_ANEXOS = [
    "microdados/dados/Tabela_Escola_2025.csv",
    "microdados/dados/Tabela_Turma_2025.csv",
    "microdados/dados/md5_microdados_ed_basica_2025.txt",
    "microdados/Anexos/ANEXO I - Dicionário de Dados/dicionário_dados_educação_básica.xlsx",
    "microdados/Anexos/ANEXO I - Dicionário de Dados/~$dicionário_dados_educação_básica.xlsx",
    "microdados/Anexos/ANEXO II -  Questionários do Censo da Educação Basica/Escola 2025.pdf",
    "microdados/Anexos/ANEXO II -  Questionários do Censo da Educação Basica/Cadastro Escola Nova 2025.pdf",
    "microdados/leia-me/Caderno de Conceitos e Orientações do Censo Escolar de 2025.pdf",
    "microdados/leia-me/Leia-me.pdf",
]
PACOTE_CEB = [
    "ceb2025_CSV/dados/ceb2025_microdados_tabela_escola.csv",
    "ceb2025_CSV/dados/ceb2025_microdados_tabela_turma.csv",
    "ceb2025_CSV/dicionario de dados/ceb2025_dicionario_dados_educacao_basica.xlsx",
    "ceb2025_CSV/questionarios/ceb2025_quest_escola.pdf",
    "ceb2025_CSV/questionarios/ceb2025_quest_cadastro_escola_nova.pdf",
    "ceb2025_CSV/leiame/ceb2025_cadastro_de_conceitos_e_orientacoes_do_censo.pdf",
    "ceb2025_CSV/leiame/ceb2025_leia-me.pdf",
    "ceb2025_CSV/documentacao complementar/ceb2025_RIP Relatorio de Impacto a Protecao de Dados Pessoais dos Censos Educacionais.pdf",
]

VARS = {
    "escola": {"NU_ANO_CENSO", "CO_ENTIDADE", "TP_DEPENDENCIA", "IN_AGUA_POTAVEL", "IN_BIBLIOTECA"},
    "turma": {"NU_ANO_CENSO", "CO_ENTIDADE", "QT_TUR_BAS", "QT_TUR_INF", "TP_MEDIACAO_DIDATICO_PEDAGO"},
    "docente": {"NU_ANO_CENSO", "CO_ENTIDADE", "QT_DOC_BAS", "QT_DOC_INF", "TP_ESCOLARIDADE"},
}

SAIDA = {
    "escola": "ceb2025_microdados_tabela_escola",
    "matricula": "ceb2025_microdados_tabela_matricula",
    "docente": "ceb2025_microdados_tabela_docente",
    "turma": "ceb2025_microdados_tabela_turma",
    "gestor": "ceb2025_microdados_tabela_gestor_escolar",
    "curso_tecnico": "ceb2025_microdados_tabela_curso_tecnico",
}


@pytest.mark.parametrize("nome, esperado", CSVS.items())
def test_tabela_pelo_nome(nome, esperado):
    assert identificar_tabela(nome) == esperado


@pytest.mark.parametrize("nome, esperado", QUESTIONARIOS.items())
def test_questionario_pelo_nome(nome, esperado):
    assert identificar_questionario(nome) == esperado


@pytest.mark.parametrize("nome", CADERNOS_SIM)
def test_caderno_reconhecido(nome):
    assert pontuar_caderno(nome) >= LIMIAR_CADERNO


@pytest.mark.parametrize("nome", CADERNOS_NAO)
def test_outros_pdfs_nao_sao_caderno(nome):
    assert pontuar_caderno(nome) < LIMIAR_CADERNO


@pytest.mark.parametrize("nomes", [PACOTE_ANEXOS, PACOTE_CEB], ids=["anexos", "ceb"])
def test_pacote_inteiro(nomes):
    achados = classificar_nomes(nomes)
    assert achados.dicionario and "dicion" in achados.dicionario.lower()
    assert "~$" not in achados.dicionario
    assert sorted(achados.tabelas) == ["escola", "turma"]
    assert achados.caderno is not None
    assert len(achados.questionarios) == 1   # o formulário de cadastro fica de fora


def test_dicionario_unico_xlsx_sem_nome_reconhecivel():
    assert classificar_nomes(["pacote/planilha.xlsx", "pacote/~$planilha.xlsx"]).dicionario == "pacote/planilha.xlsx"


@pytest.mark.parametrize("colunas, esperado", [
    (["NU_ANO_CENSO", "CO_ENTIDADE", "TP_DEPENDENCIA", "IN_AGUA_POTAVEL"], "escola"),
    (["NU_ANO_CENSO", "CO_ENTIDADE", "QT_TUR_BAS", "QT_TUR_INF"], "turma"),
    (["NU_ANO_CENSO", "CO_ENTIDADE"], None),                      # só as colunas comuns
    (["FOO", "BAR", "BAZ"], None),
    (['"nu_ano_censo"', '"co_entidade"', '"qt_doc_bas"', '"qt_doc_inf"'], "docente"),
])
def test_tabela_pelo_cabecalho(colunas, esperado):
    assert identificar_tabela_por_cabecalho(colunas, VARS)[0] == esperado


def test_tokens():
    assert tokens_arquivo("ceb2025_microdados_tabela_escola") == {"escola"}
    assert tokens_arquivo("Tabela_Gestor_Escolar_2025") == {"gestor"}
    assert sorted(ASSINATURA_TABELA) == sorted(ASSINATURA_QUESTIONARIO) == sorted(CHAVES)


@pytest.mark.parametrize("tabela, esperado", SAIDA.items())
def test_nome_saida(tabela, esperado):
    assert nome_saida(tabela, 2025) == esperado


def test_nomes_de_saida():
    assert nome_saida_sav("gestor", 2025) == "ceb2025_microdados_tabela_gestor_escolar.sav"
    assert nome_saida_json("gestor", 2025) == "ceb2025_microdados_tabela_gestor_escolar_import_metadata_editor.json"
    assert nome_saida("escola", 2027) == "ceb2027_microdados_tabela_escola"
    assert nome_saida("escola", None) == "ceb_microdados_tabela_escola"
    assert prefixo_edicao(2025) == "ceb2025_"
    assert prefixo_edicao(None) == "ceb_"
    assert all(POR_CHAVE[t].base_saida for t in CHAVES)


@pytest.mark.parametrize("tabela", SAIDA)
def test_artefatos_gerados_sao_reidentificaveis(tabela):
    assert identificar_tabela(nome_saida_sav(tabela, 2025)) == tabela
    assert identificar_tabela(nome_saida_json(tabela, 2025)) == tabela
