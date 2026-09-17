#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""testar_identificacao.py — Regressão da identificação de insumos.

O INEP muda a forma dos insumos sem aviso: nome de arquivo, estrutura de
pastas, delimitador e codificação já mudaram entre publicações do MESMO ano.
Este teste fixa o comportamento esperado em cima dos nomes reais já vistos,
mais variações hostis, para que uma mudança futura de convenção quebre AQUI e
não no meio de um processamento de 500 MB.

Não depende de nenhum insumo em disco: só de nomes. Rode com

    python testar_identificacao.py
"""
from __future__ import annotations

import sys

from censo_lib import (
    ASSINATURA_QUESTIONARIO,
    ASSINATURA_TABELA,
    BASE_ARQUIVO_SAIDA,
    classificar_nomes,
    identificar_questionario,
    identificar_tabela,
    identificar_tabela_por_cabecalho,
    nome_saida,
    nome_saida_json,
    nome_saida_sav,
    pontuar_caderno,
    prefixo_edicao,
    tokens_arquivo,
)

falhas: list[str] = []


def checar(rotulo: str, obtido, esperado) -> None:
    if obtido != esperado:
        falhas.append(f"{rotulo}\n      esperado: {esperado!r}\n      obtido:   {obtido!r}")


# ---------------------------------------------------------------------------
# 1. Nomes de CSV — as duas convenções reais + variações
# ---------------------------------------------------------------------------
CSVS = {
    # publicação "Anexos/" (2025, 1ª forma)
    "Tabela_Escola_2025.csv":                       "escola",
    "Tabela_Matricula_2025.csv":                    "matricula",
    "Tabela_Docente_2025.csv":                      "docente",
    "Tabela_Turma_2025.csv":                        "turma",
    "Tabela_Gestor_Escolar_2025.csv":               "gestor",
    "Tabela_Curso_Tecnico_2025.csv":                "curso_tecnico",
    # publicação "ceb2025_CSV" (2025, 2ª forma) — ano no PREFIXO
    "ceb2025_microdados_tabela_escola.csv":         "escola",
    "ceb2025_microdados_tabela_matricula.csv":      "matricula",
    "ceb2025_microdados_tabela_docente.csv":        "docente",
    "ceb2025_microdados_tabela_turma.csv":          "turma",
    "ceb2025_microdados_tabela_gestor_escolar.csv": "gestor",
    "ceb2025_microdados_tabela_curso_tecnico.csv":  "curso_tecnico",
    # marcadores de republicação, em qualquer posição
    "Tabela_Curso_Tecnico_2025_V2.csv":             "curso_tecnico",
    "Tabela_Escola_2025_retificada_V3.csv":         "escola",
    "ceb2026_microdados_tabela_escola_retificado.csv": "escola",
    "Tabela_Escola_V2_2025.csv":                    "escola",
    # caixa, acento, separador e plural
    "TABELA_DE_MATRÍCULAS_2027.CSV":                "matricula",
    "tabela de curso técnico 2026.csv":             "curso_tecnico",
    "Base_Docentes_2030.csv":                       "docente",
    # abas do dicionário (mesma função)
    "Tabela_de_Escola":                             "escola",
    "Tabela_Curso_Técnico ":                        "curso_tecnico",
    "Tabela_de_Gestor":                             "gestor",
    # não são tabelas do Censo
    "md5_microdados_ed_basica_2025.txt":            None,
    "Tabela_Curso_Superior_2025.csv":               None,
    "leia-me.csv":                                  None,
}
for nome, esperado in CSVS.items():
    checar(f"identificar_tabela({nome!r})", identificar_tabela(nome), esperado)

# ---------------------------------------------------------------------------
# 2. Questionários — inclui o par que colide por substring
# ---------------------------------------------------------------------------
QUESTIONARIOS = {
    "Escola 2025.pdf":                        "escola",
    "Aluno 2025.pdf":                         "matricula",
    "Profissional Escolar 2025.pdf":          "docente",
    "Turma 2025.pdf":                         "turma",
    "Gestor Escolar 2025.pdf":                "gestor",
    "ceb2025_quest_escola.pdf":               "escola",
    "ceb2025_quest_aluno.pdf":                "matricula",
    "ceb2025_quest_profissional_escolar.pdf": "docente",
    "ceb2025_quest_turma.pdf":                "turma",
    "ceb2025_quest_gestor_escolar.pdf":       "gestor",
    # NÃO é o questionário da Escola — é outro formulário
    "Cadastro Escola Nova 2025.pdf":          None,
    "ceb2025_quest_cadastro_escola_nova.pdf": None,
}
for nome, esperado in QUESTIONARIOS.items():
    checar(f"identificar_questionario({nome!r})", identificar_questionario(nome), esperado)

# ---------------------------------------------------------------------------
# 3. Caderno de Conceitos — o nome de 2025 tem erro de digitação da fonte
# ---------------------------------------------------------------------------
CADERNOS_SIM = [
    "Caderno de Conceitos e Orientações do Censo Escolar de 2025.pdf",
    "ceb2025_cadastro_de_conceitos_e_orientacoes_do_censo.pdf",
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
from censo_lib import LIMIAR_CADERNO
for nome in CADERNOS_SIM:
    checar(f"pontuar_caderno({nome[:40]!r}) >= limiar",
           pontuar_caderno(nome) >= LIMIAR_CADERNO, True)
for nome in CADERNOS_NAO:
    checar(f"pontuar_caderno({nome[:40]!r}) < limiar",
           pontuar_caderno(nome) < LIMIAR_CADERNO, True)

# ---------------------------------------------------------------------------
# 4. Pacote inteiro — as duas árvores reais, com as pastas que cada uma usa
# ---------------------------------------------------------------------------
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
for rotulo, nomes in (("Anexos", PACOTE_ANEXOS), ("ceb", PACOTE_CEB)):
    achados = classificar_nomes(nomes)
    checar(f"[{rotulo}] dicionário localizado",
           achados["dicionario"] is not None and "dicion" in achados["dicionario"].lower(), True)
    checar(f"[{rotulo}] dicionário não é o temporário do Excel",
           "~$" not in (achados["dicionario"] or ""), True)
    checar(f"[{rotulo}] tabelas", sorted(achados["tabelas"]), ["escola", "turma"])
    checar(f"[{rotulo}] caderno localizado", achados["caderno"] is not None, True)
    checar(f"[{rotulo}] questionários (o formulário de cadastro fica de fora)",
           len(achados["questionarios"]), 1)

# ---------------------------------------------------------------------------
# 5. Camada de conteúdo — decide quando o nome não diz nada
# ---------------------------------------------------------------------------
VARS = {
    "escola":    {"NU_ANO_CENSO", "CO_ENTIDADE", "TP_DEPENDENCIA", "IN_AGUA_POTAVEL", "IN_BIBLIOTECA"},
    "turma":     {"NU_ANO_CENSO", "CO_ENTIDADE", "QT_TUR_BAS", "QT_TUR_INF", "TP_MEDIACAO_DIDATICO_PEDAGO"},
    "docente":   {"NU_ANO_CENSO", "CO_ENTIDADE", "QT_DOC_BAS", "QT_DOC_INF", "TP_ESCOLARIDADE"},
}
checar("cabeçalho de escola",
       identificar_tabela_por_cabecalho(
           ["NU_ANO_CENSO", "CO_ENTIDADE", "TP_DEPENDENCIA", "IN_AGUA_POTAVEL"], VARS)[0],
       "escola")
checar("cabeçalho de turma",
       identificar_tabela_por_cabecalho(
           ["NU_ANO_CENSO", "CO_ENTIDADE", "QT_TUR_BAS", "QT_TUR_INF"], VARS)[0],
       "turma")
checar("cabeçalho ambíguo (só as colunas comuns) não decide",
       identificar_tabela_por_cabecalho(["NU_ANO_CENSO", "CO_ENTIDADE"], VARS)[0],
       None)
checar("cabeçalho estranho não decide",
       identificar_tabela_por_cabecalho(["FOO", "BAR", "BAZ"], VARS)[0],
       None)
checar("cabeçalho com aspas e caixa baixa",
       identificar_tabela_por_cabecalho(
           ['"nu_ano_censo"', '"co_entidade"', '"qt_doc_bas"', '"qt_doc_inf"'], VARS)[0],
       "docente")

# ---------------------------------------------------------------------------
# 6. Tokenização — o que sustenta tudo acima
# ---------------------------------------------------------------------------
checar("tokens_arquivo('ceb2025_microdados_tabela_escola')",
       tokens_arquivo("ceb2025_microdados_tabela_escola"), {"escola"})
checar("tokens_arquivo('Tabela_Gestor_Escolar_2025')",
       tokens_arquivo("Tabela_Gestor_Escolar_2025"), {"gestor"})
checar("as seis tabelas têm assinatura",
       sorted(ASSINATURA_TABELA), sorted(ASSINATURA_QUESTIONARIO))

# ---------------------------------------------------------------------------
# 7. Nomenclatura da SAÍDA
# ---------------------------------------------------------------------------
# A saída segue a convenção da publicação do INEP, independentemente do formato
# do insumo: um pacote antigo ("Tabela_Escola_2025.csv") também sai assim.
SAIDA = {
    "escola":        "ceb2025_microdados_tabela_escola",
    "matricula":     "ceb2025_microdados_tabela_matricula",
    "docente":       "ceb2025_microdados_tabela_docente",
    "turma":         "ceb2025_microdados_tabela_turma",
    "gestor":        "ceb2025_microdados_tabela_gestor_escolar",
    "curso_tecnico": "ceb2025_microdados_tabela_curso_tecnico",
}
for tabela, esperado in SAIDA.items():
    checar(f"nome_saida({tabela!r}, 2025)", nome_saida(tabela, 2025), esperado)

checar("nome_saida_sav", nome_saida_sav("gestor", 2025),
       "ceb2025_microdados_tabela_gestor_escolar.sav")
checar("nome_saida_json", nome_saida_json("gestor", 2025),
       "ceb2025_microdados_tabela_gestor_escolar_import_metadata_editor.json")
checar("outra edição", nome_saida("escola", 2027),
       "ceb2027_microdados_tabela_escola")
checar("sem ano determinado", nome_saida("escola", None),
       "ceb_microdados_tabela_escola")
checar("prefixo com ano", prefixo_edicao(2025), "ceb2025_")
checar("prefixo sem ano", prefixo_edicao(None), "ceb_")
checar("toda tabela tem base de saída",
       sorted(BASE_ARQUIVO_SAIDA), sorted(ASSINATURA_TABELA))

# Ida e volta: os artefatos que ESTE pipeline produz precisam ser
# reidentificáveis, senão `encontrar_json` não acha o JSON no passo 3.
for tabela in SAIDA:
    checar(f"round-trip .sav de {tabela}",
           identificar_tabela(nome_saida_sav(tabela, 2025)), tabela)
    checar(f"round-trip .json de {tabela}",
           identificar_tabela(nome_saida_json(tabela, 2025)), tabela)

# ---------------------------------------------------------------------------
if falhas:
    print(f"\n{len(falhas)} FALHA(S):\n")
    for f in falhas:
        print(f"  ✗ {f}")
    sys.exit(1)
print("Identificação de insumos e nomenclatura de saída: todos os casos passaram.")
