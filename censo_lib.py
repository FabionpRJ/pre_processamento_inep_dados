#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
censo_lib.py — Módulo compartilhado do pipeline do Censo Escolar 2025.

Expõe constantes, utilitários de leitura de CSV/JSON, extração de questões
de PDFs, extração/alinhamento de conceitos do Caderno de Conceitos e
construção de metadados SAV usados por gerar_json_metadata_editor,
criar_sav_vazio e popular_sav.
"""
from __future__ import annotations

import codecs
import hashlib
import io
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

import pandas as pd
import pyreadstat

# pandas 3 usa arrays de string apoiados em pyarrow por padrão quando o
# pyarrow está instalado (aqui, puxado transitivamente pelo streamlit) — em
# combinação com DataFrames de muitas colunas montadas por inserção
# individual (ver criar_sav_vazio.montar_df_vazio), isso já causou segfault
# em libarrow.so ao gravar com pyreadstat (confirmado via coredumpctl/gdb).
# Força o dtype "object" clássico do numpy para strings, evitando o
# caminho de código do Arrow neste pipeline.
pd.set_option("future.infer_string", False)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

ABA_PARA_ARQUIVO: dict[str, str] = {
    "Tabela_de_Escola":     "escola",
    "Tabela_de_Matrícula":  "matricula",
    "Tabela_de_Docente":    "docente",
    "Tabela_de_Turma":      "turma",
    "Tabela_de_Gestor":     "gestor",
    "Tabela_Curso_Técnico": "curso_tecnico",
}

FID_POR_TABELA: dict[str, str] = {
    "escola":        "F1",
    "matricula":     "F2",
    "docente":       "F3",
    "turma":         "F4",
    "gestor":        "F5",
    "curso_tecnico": "F6",
}

# As seis tabelas do Censo. Os VALORES são apenas ilustrativos do padrão de
# nome do INEP — nada casa por eles. A localização real dos CSVs é feita por
# `identificar_tabela`/`localizar_csv`, que ignoram ano e marcador de versão
# (ex: "Tabela_Curso_Tecnico_2025_V2.csv"). Só as CHAVES são usadas no código.
TABELAS: dict[str, str] = {
    "escola":        "Tabela_Escola_2025.csv",
    "matricula":     "Tabela_Matricula_2025.csv",
    "docente":       "Tabela_Docente_2025.csv",
    "turma":         "Tabela_Turma_2025.csv",
    "gestor":        "Tabela_Gestor_Escolar_2025.csv",
    "curso_tecnico": "Tabela_Curso_Tecnico_2025.csv",
}

NOME_TABELA: dict[str, str] = {
    "escola":        "Tabela_Escola",
    "matricula":     "Tabela_Matricula",
    "docente":       "Tabela_Docente",
    "turma":         "Tabela_Turma",
    "gestor":        "Tabela_Gestor",
    "curso_tecnico": "Tabela_Curso_Tecnico",
}

# ---------------------------------------------------------------------------
# Nomenclatura dos artefatos de SAÍDA
# ---------------------------------------------------------------------------
# A saída segue a convenção da publicação do INEP, para que os .sav fiquem ao
# lado dos CSVs de origem sem ambiguidade:
#
#     ceb2025_microdados_tabela_gestor_escolar.sav
#     └┬┘└─┬┘ └────┬───┘ └────────┬──────────┘
#      │   │       │              └─ BASE_ARQUIVO_SAIDA[tabela]
#      │   │       └─ fixo
#      │   └─ ano da edição, detectado (ver `detectar_ano_censo`)
#      └─ PREFIXO_EDICAO
#
# Vale para qualquer insumo: um pacote no formato antigo ("Tabela_Escola_2025
# .csv") também produz saída nesta convenção — o nome de saída é decisão do
# ETL, não herança do nome de entrada.
PREFIXO_EDICAO = "ceb"

# Base do nome de saída de cada tabela. Segue a grafia do INEP nos CSVs, que
# difere da chave interna em `gestor` → `tabela_gestor_escolar`.
BASE_ARQUIVO_SAIDA: dict[str, str] = {
    "escola":        "tabela_escola",
    "matricula":     "tabela_matricula",
    "docente":       "tabela_docente",
    "turma":         "tabela_turma",
    "gestor":        "tabela_gestor_escolar",
    "curso_tecnico": "tabela_curso_tecnico",
}

_ANO_VALIDO = range(1990, 2101)


def prefixo_edicao(ano: str | int | None) -> str:
    """`ceb2025_` — ou `ceb_` quando o ano não pôde ser determinado."""
    return f"{PREFIXO_EDICAO}{ano}_" if ano else f"{PREFIXO_EDICAO}_"


def nome_saida(tabela: str, ano: str | int | None) -> str:
    """Nome-base (sem extensão) do artefato de saída de uma tabela.

    >>> nome_saida("gestor", 2025)
    'ceb2025_microdados_tabela_gestor_escolar'
    """
    base = BASE_ARQUIVO_SAIDA.get(tabela, f"tabela_{tabela}")
    return f"{prefixo_edicao(ano)}microdados_{base}"


def nome_saida_json(tabela: str, ano: str | int | None) -> str:
    """Nome do JSON de importação do Metadata Editor."""
    return f"{nome_saida(tabela, ano)}_import_metadata_editor.json"


def nome_saida_sav(tabela: str, ano: str | int | None) -> str:
    return f"{nome_saida(tabela, ano)}.sav"


def _ano_de_texto(texto: str) -> str | None:
    """Último ano plausível encontrado em um texto livre."""
    achados = [a for a in re.findall(r"(?:19|20)\d{2}", str(texto))
               if int(a) in _ANO_VALIDO]
    return achados[-1] if achados else None


def _ano_do_csv(caminho: Path) -> str | None:
    """Lê o ano do Censo da PRIMEIRA linha de dados do CSV.

    A coluna canônica é `NU_ANO_CENSO`; qualquer coluna cujo nome contenha
    "ANO_CENSO" serve, para o caso de o INEP renomeá-la. Lê duas linhas, não o
    arquivo — vale também para as tabelas de centenas de MB.
    """
    try:
        encoding = detectar_encoding(caminho)
        sep = detectar_delimitador(caminho, encoding)
        with open(caminho, "r", encoding=encoding, errors="replace") as fh:
            cabecalho = fh.readline()
            primeira = fh.readline()
    except OSError:
        return None
    if not primeira:
        return None

    colunas = [c.strip().strip('"').strip("'").upper()
               for c in cabecalho.rstrip("\r\n").split(sep)]
    valores = [v.strip().strip('"').strip("'")
               for v in primeira.rstrip("\r\n").split(sep)]
    for i, col in enumerate(colunas):
        if "ANO_CENSO" in col and i < len(valores):
            valor = valores[i]
            if valor.isdigit() and int(valor) in _ANO_VALIDO:
                return valor
    return None


def detectar_ano_censo(
    pasta_csv: Path | None = None, nomes_extra=None
) -> str | None:
    """Descobre o ano da edição para nomear a saída.

    Ordem: (1) o valor de `NU_ANO_CENSO` nos próprios dados — a fonte mais
    confiável, porque não depende de nome nenhum; (2) o ano no nome dos CSVs;
    (3) o ano em `nomes_extra` (dicionário, Caderno, nome do pacote). Devolve
    None se nada informar o ano — o chamador decide se avisa; a saída sai como
    `ceb_microdados_...`, sem inventar um ano.

    Havendo divergência entre CSVs, vence o valor mais frequente.
    """
    candidatos: list[str] = []

    if pasta_csv and pasta_csv.is_dir():
        csvs = sorted(pasta_csv.rglob("*.csv"))
        for csv in csvs:
            if (ano := _ano_do_csv(csv)):
                candidatos.append(ano)
        if not candidatos:
            for csv in csvs:
                if (ano := _ano_de_texto(csv.stem)):
                    candidatos.append(ano)

    if not candidatos:
        for nome in (nomes_extra or []):
            if nome and (ano := _ano_de_texto(Path(str(nome)).stem)):
                candidatos.append(ano)

    if not candidatos:
        return None
    return Counter(candidatos).most_common(1)[0][0]

# Questionário (PDF) correspondente a cada tabela
QUESTIONARIO_POR_TABELA: dict[str, str] = {
    "escola":        "Escola 2025.pdf",
    "matricula":     "Aluno 2025.pdf",
    "docente":       "Profissional Escolar 2025.pdf",
    "turma":         "Turma 2025.pdf",
    "gestor":        "Gestor Escolar 2025.pdf",
    "curso_tecnico": "Turma 2025.pdf",
}

# Rótulo de exibição de cada tabela (abas do dicionário no censo.html)
ROTULO_TABELA: dict[str, str] = {
    "escola":        "Escola",
    "matricula":     "Matrícula",
    "docente":       "Docente",
    "turma":         "Turma",
    "gestor":        "Gestor Escolar",
    "curso_tecnico": "Curso Técnico",
}

# Universo estatístico — a POPULAÇÃO a que as variáveis se referem, que é o
# sentido do campo `var_universe` no DDI. Antes esse campo recebia os anos de
# coleta, que descrevem o período e não a população (os anos passaram para
# `var_notes`); depois recebeu um texto por tabela.
#
# O texto é o MESMO para as seis tabelas porque nesta publicação a unidade de
# observação é a mesma nas seis: os microdados são agregados por escola (toda
# tabela começa pelas colunas de identificação da escola e as variáveis de
# matrícula/docente/turma são contagens por escola). Um universo "Matrículas
# declaradas..." descreveria uma linha por matrícula, que não é o que o
# arquivo contém.

UNIVERSO_SEM_ANO = "Escola de Educação Básica declarada no Censo Escolar"


def universo_publicacao(ano: str | int | None) -> str:
    """Texto de `var_universe`, ancorado no ano do dicionário.

    Sem ano determinado, cai para um texto sem data em vez de emitir
    "declarada em None" — o mesmo princípio de `prefixo_edicao`.
    """
    return f"Escola de Educação Básica declarada em {ano}" if ano else UNIVERSO_SEM_ANO

# ---------------------------------------------------------------------------
# Formato numérico declarado (JSON do Metadata Editor e .sav)
# ---------------------------------------------------------------------------
# O formato precisa ser calculado num lugar só: enquanto o JSON emitia
# `F{tamanho}.0` e a gravação do .sav não declarava formato numérico nenhum
# (deixando o pyreadstat cair no padrão F8.2), os dois artefatos do mesmo
# pipeline discordavam em 100% das variáveis numéricas.

# Numéricas que representam grandeza decimal — o resto do Censo é contagem
# ou código inteiro. Declarar `.0` em coordenada faz o formato mentir.
DECIMAIS_POR_VARIAVEL: dict[str, int] = {
    "LATITUDE":  6,
    "LONGITUDE": 6,
}

LARGURA_NUMERICA_PADRAO = 8


def decimais_variavel(var: dict) -> int:
    """Casas decimais declaradas para a variável (0 para inteiros e texto)."""
    if var.get("tipo") != "Num":
        return 0
    return DECIMAIS_POR_VARIAVEL.get(str(var.get("nome_variavel", "")).upper(), 0)


def largura_variavel(var: dict) -> int:
    """Largura declarada: a do dicionário quando existir, senão o padrão."""
    tamanho = var.get("tamanho")
    try:
        largura = int(tamanho) if tamanho else LARGURA_NUMERICA_PADRAO
    except (TypeError, ValueError):
        largura = LARGURA_NUMERICA_PADRAO
    return max(largura, 1)


def formato_numerico(var: dict) -> str:
    """Formato SPSS de uma variável numérica, ex. "F8.0" / "F20.6".

    A largura precisa comportar o separador decimal e as casas — senão o
    SPSS/readstat reajusta por conta própria e o formato declarado no JSON
    deixa de valer para o .sav.
    """
    casas = decimais_variavel(var)
    largura = largura_variavel(var)
    if casas:
        largura = max(largura, casas + 2)
    return f"F{largura}.{casas}"


# Limites do formato SPSS, medidos em BYTES do texto codificado em UTF-8
# (confirmados contra o readstat: acima disso ele trunca por conta própria).
# Ver `truncar` — truncar por caractere gera UTF-8 inválido no .sav.
LIMITE_ROTULO_VARIAVEL = 256
LIMITE_ROTULO_VALOR    = 120

# ---------------------------------------------------------------------------
# Valores especiais do dicionário (sentinelas de tratamento e de não-resposta)
# ---------------------------------------------------------------------------
# O dicionário do INEP lista, na coluna de categorias, códigos que NÃO são
# categorias: são marcas de que o valor observado não existe ou foi tratado.
# Em 2025 são dois:
#
#     88888          "registro com marcação de valor extremo (...)"   26 vars QT_*
#     99999999999999 "Sem declaração"                                  2 vars de CNPJ
#     9              "Não informado"                                  20 vars TP_*
#
# **Quem decide é o RÓTULO, não o número.** No mesmo dicionário o código `8`
# de largura 1 é categoria real ("Área onde se localizam povos e comunidades
# tradicionais") enquanto o `9` da mesma largura é "Não informado": nenhuma
# regra baseada na forma do número separa os dois. A forma serve só para
# AUDITAR (`parece_sentinela`), levantando aviso quando um código com cara de
# sentinela escapa dos marcadores — que é como uma redação nova do INEP vira
# um aviso no log em vez de passar silenciosamente como categoria.
#
# Dois tipos, com destinos diferentes no JSON:
#
#   "imputacao"    o produtor SUBSTITUIU o valor observado ao aplicar uma regra
#                  de consistência. Vai para `var_invalrng` **e** descreve
#                  `var_imputation` — é o caso do 88888.
#   "nao_resposta" o valor nunca existiu (não declarado / não informado). Vai
#                  só para `var_invalrng`: não houve imputação a descrever.

_MARCADORES_IMPUTACAO: tuple[str, ...] = (
    "valor extremo", "valores extremos", "outlier",
    "imputad", "imputac",            # imputado/imputada/imputação
    "marcacao de valor", "marcado com o codigo",
    "tratamento de valor", "valor tratado", "valor substituido",
)

_MARCADORES_NAO_RESPOSTA: tuple[str, ...] = (
    "nao informad", "nao declarad", "nao respond", "nao consta",
    "sem declaracao", "sem informacao", "sem resposta", "sem preenchimento",
    "nao aplicav", "nao se aplica", "ignorado", "desconhecido",
)


def classificar_codigo_especial(rotulo: str) -> str | None:
    """Diz se o RÓTULO de um código o marca como valor não substantivo.

    Devolve `"imputacao"`, `"nao_resposta"` ou `None` (categoria real).
    A imputação é testada primeiro: um rótulo que fale em valor extremo
    descreve um tratamento aplicado pelo produtor, ainda que também contenha
    alguma palavra de ausência.
    """
    # " ".join(split()) normaliza o espaço interno: o rótulo vem de célula de
    # Excel e de linhas concatenadas em `parse_categoria`, então "Não  informado"
    # com dois espaços é forma real e precisa casar igual.
    texto = " ".join(_sem_acento(str(rotulo or "")).lower().split())
    if not texto:
        return None
    if any(m in texto for m in _MARCADORES_IMPUTACAO):
        return "imputacao"
    if any(m in texto for m in _MARCADORES_NAO_RESPOSTA):
        return "nao_resposta"
    return None


def parece_sentinela(codigo) -> bool:
    """Heurística de AUDITORIA: o número tem cara de sentinela?

    Repetição de 8 ou 9 com pelo menos dois dígitos (88, 999, 88888,
    99999999999999). Dois dígitos é o piso justamente porque, com um só, `8`
    é categoria real e `9` não — a forma não decide nada aí.

    Nunca classifica sozinha: só levanta aviso quando o rótulo não bateu com
    nenhum marcador conhecido. Ver `classificar_codigo_especial`.
    """
    digitos = str(abs(int(codigo))) if isinstance(codigo, (int, float)) else str(codigo).strip().lstrip("-")
    return (
        len(digitos) >= 2
        and digitos.isdigit()
        and digitos[0] in "89"
        and len(set(digitos)) == 1
    )


def separar_codigos_especiais(rotulos_valor: dict) -> tuple[dict, dict]:
    """Parte os códigos de uma variável em categorias reais e especiais.

    Devolve `(reais, especiais)`, onde `especiais` é
    `{codigo: (tipo, rotulo)}` com `tipo` em `"imputacao"`/`"nao_resposta"`.
    Os especiais continuam sendo rotulados no JSON (`var_catgry_labels`
    preserva o texto do dicionário) — o que muda é que deixam de contar como
    categoria para efeito de estatística e passam a ser declarados como
    valores inválidos.
    """
    reais: dict = {}
    especiais: dict = {}
    for codigo, rotulo in (rotulos_valor or {}).items():
        tipo = classificar_codigo_especial(rotulo)
        if tipo:
            especiais[codigo] = (tipo, rotulo)
        else:
            reais[codigo] = rotulo
    return reais, especiais


# Como cada tipo é descrito dentro de `var_imputation`. Os DOIS entram: a
# decisão registrada em reunião é tratar todo código especial como resultado do
# processamento do INEP, não só o de valor extremo — são todos valores que o
# produtor GRAVA no lugar da observação. O que a redação preserva é a natureza
# de cada um, para que o texto continue verdadeiro frente ao dicionário.
_FRASE_POR_TIPO: dict[str, str] = {
    "imputacao":    "marca de tratamento de consistência aplicada pelo produtor",
    "nao_resposta": "marca de ausência de declaração atribuída pelo produtor",
}


def descrever_imputacao(especiais: dict) -> str:
    """Texto de `var_imputation` a partir dos códigos especiais da variável.

    DDI: `imputation` é a descrição em texto livre do procedimento. Descreve
    **todos** os códigos especiais — tanto os de tratamento de consistência
    (88888) quanto os de não-resposta (9, 99999999999999): nenhum deles é
    valor observado, e todos chegam ao dado por decisão do produtor.

    A natureza de cada código continua explícita no texto (`_FRASE_POR_TIPO`),
    de modo que quem lê o metadado distinga "valor extremo tratado" de "não
    informado" sem precisar do dicionário ao lado.
    """
    if not especiais:
        return ""
    itens = [
        f"Código {codigo}: "
        f"{_FRASE_POR_TIPO.get(tipo, 'valor atribuído pelo produtor')}; "
        f"no dicionário de variáveis, “{' '.join(str(rotulo).split())}”."
        for codigo, (tipo, rotulo) in sorted(especiais.items())
    ]
    return " ".join(itens)

# ---------------------------------------------------------------------------
# Identificação resiliente de arquivos e abas
# ---------------------------------------------------------------------------
# O INEP não mantém convenção de nome entre publicações. Já foram vistos, para
# o MESMO ano de coleta:
#
#     Tabela_Escola_2025.csv        ceb2025_microdados_tabela_escola.csv
#     Escola 2025.pdf               ceb2025_quest_escola.pdf
#     leia-me/Caderno de Conceitos e Orientações do Censo Escolar de 2025.pdf
#     leiame/ceb2025_cadastro_de_conceitos_e_orientacoes_do_censo.pdf
#
# — prefixo de edição, ano no meio do nome, abreviações novas ("quest") e até
# erro de digitação da própria fonte ("cadastro" no lugar de "caderno"). Casar
# por chave inteira quebrava em todos esses casos.
#
# A identificação é feita em CAMADAS, da mais barata para a mais definitiva:
#
#   1. NOME  — o nome vira um CONJUNTO de tokens significativos (ano, prefixo
#              de edição, "microdados", "tabela", "quest"… são descartados) e é
#              pontuado contra a assinatura de cada tabela. Não importa a
#              ordem nem a posição: só quais palavras identificadoras existem.
#   2. CONTEÚDO — o cabeçalho do CSV é comparado com as variáveis que o
#              dicionário declara para cada tabela. É decisivo: mesmo que o
#              arquivo se chame `arquivo_01.csv`, as colunas dizem o que ele é.
#              (Medido no insumo real: 1.00 para a tabela certa, ≤0.51 para
#              todas as outras.) Para PDF, o texto da 1ª página faz esse papel.
#   3. RELATÓRIO — toda resolução registra por qual camada passou e com que
#              pontuação, para que uma identificação duvidosa seja auditável em
#              vez de silenciosa (mesma filosofia do relatorio_casamento.csv).
#
# Ponto de extensão: para acomodar um vocabulário novo do INEP, quase sempre
# basta acrescentar um token em `_TOKENS_RUIDO` (se for palavra de embalagem)
# ou em `ASSINATURA_*` (se for palavra identificadora). A camada 2 continua
# funcionando mesmo sem nenhum ajuste.

# Palavras de embalagem: aparecem no nome mas não dizem QUAL tabela é. Inclui
# os marcadores de republicação ("v2", "retificado") — que antes só eram
# removidos no final do nome e agora valem em qualquer posição.
_TOKENS_RUIDO: frozenset[str] = frozenset({
    # embalagem / coleção
    "tabela", "microdado", "dado", "base", "arquivo", "anexo", "planilha",
    "censo", "escolar", "educacao", "basica", "ceb", "ces", "inep",
    "csv", "xlsx", "pdf",
    # prefixo de questionário
    "quest", "questionario", "formulario",
    # embalagem dos artefatos que ESTE pipeline produz — para que
    # identificar_tabela reconheça também os nomes de saída
    # ("ceb2025_microdados_tabela_gestor_escolar_import_metadata_editor")
    "import", "metadata", "editor", "metadado", "sav", "json",
    # conectivos
    "de", "do", "da", "e", "em", "no", "na", "a", "o", "por", "para", "com",
    # marcadores de versão/republicação
    "v", "ver", "versao", "rev", "revisao", "final",
    "retificado", "retificada", "corrigido", "corrigida",
    "atualizado", "atualizada", "consolidado", "consolidada",
})

# Palavras identificadoras de cada tabela. `curso_tecnico` exige as duas: é o
# que impede "Tabela_Curso_Superior" de casar.
ASSINATURA_TABELA: dict[str, frozenset[str]] = {
    "escola":        frozenset({"escola"}),
    "matricula":     frozenset({"matricula"}),
    "docente":       frozenset({"docente"}),
    "turma":         frozenset({"turma"}),
    "gestor":        frozenset({"gestor"}),
    "curso_tecnico": frozenset({"curso", "tecnico"}),
}

# Assinatura do questionário PDF de cada tabela. `curso_tecnico` compartilha o
# questionário de Turma — daí o mesmo conjunto.
ASSINATURA_QUESTIONARIO: dict[str, frozenset[str]] = {
    "escola":        frozenset({"escola"}),
    "matricula":     frozenset({"aluno"}),
    "docente":       frozenset({"profissional"}),
    "turma":         frozenset({"turma"}),
    "gestor":        frozenset({"gestor"}),
    "curso_tecnico": frozenset({"turma"}),
}

# Abaixo disso a identificação por nome é considerada duvidosa e devolvida como
# não-resolvida (a camada de conteúdo assume). O valor separa "Escola" (1.00)
# de "Cadastro Escola Nova" (0.33), que é um formulário diferente.
LIMIAR_NOME = 0.50

# Containment mínimo entre o cabeçalho do CSV e as variáveis do dicionário, e
# margem mínima sobre a 2ª colocada. No insumo real a diferença é de 1.00 para
# ≤0.51, então há folga larga.
LIMIAR_COLUNAS = 0.60
MARGEM_COLUNAS = 0.15

_ANO_TOKEN_RE = re.compile(r"^(?:19|20)\d{2}$")
_SO_DIGITOS_RE = re.compile(r"^\d+$")
# "ceb2025" chega como um token só; separar letra de dígito expõe o ano.
_FRONTEIRA_ALFANUM_RE = re.compile(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])")


def _sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", str(texto))
        if unicodedata.category(c) != "Mn"
    )


def _singular(token: str) -> str:
    """Reduz plurais comuns do português, para que "Tabelas_de_Matrículas"
    tokenize igual a "Tabela_de_Matrícula".

    O "-es" só cai quando o radical termina em consoante que exige essa forma
    ("gestores" → gestor). Caso contrário cai só o "-s", senão "docentes"
    viraria "docent" e deixaria de casar com "docente".
    """
    if len(token) > 4 and token.endswith("oes"):
        return token[:-3] + "ao"
    if len(token) > 4 and token.endswith("ais"):
        return token[:-3] + "al"
    if len(token) > 4 and token.endswith("es") and token[-3] in "rzlns":
        return token[:-2]
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def tokens_arquivo(texto: str) -> set[str]:
    """Extrai de um nome de arquivo/aba o conjunto de tokens significativos.

    Descarta acento, caixa, separadores, ano (em QUALQUER posição), números
    soltos e as palavras de embalagem de `_TOKENS_RUIDO`. O resultado é um
    conjunto: a ordem e a posição das palavras não importam, que é o que torna
    `Tabela_Escola_2025` e `ceb2025_microdados_tabela_escola` equivalentes.
    """
    bruto = _FRONTEIRA_ALFANUM_RE.sub(" ", _sem_acento(texto).lower())
    tokens = set()
    for palavra in re.split(r"[^a-z0-9]+", bruto):
        if not palavra or _ANO_TOKEN_RE.match(palavra) or _SO_DIGITOS_RE.match(palavra):
            continue
        palavra = _singular(palavra)
        if palavra in _TOKENS_RUIDO or len(palavra) < 2:
            continue
        tokens.add(palavra)
    return tokens


def _pontuar_assinatura(tokens: set[str], assinatura: frozenset[str]) -> float:
    """Quanto do nome é explicado pela assinatura, exigindo que ela esteja
    inteira presente.

    Pontuar pelos EXCEDENTES é o que distingue um nome que É a coisa de um nome
    que apenas a MENCIONA: "quest_escola" → {escola}, sem excedente, 1.00;
    "cadastro_escola_nova" → {cadastro, escola, nova}, dois excedentes, 0.33.
    """
    if not assinatura or not assinatura <= tokens:
        return 0.0
    return len(assinatura) / (len(assinatura) + len(tokens - assinatura))


def _melhor_assinatura(
    nome: str, assinaturas: dict[str, frozenset[str]]
) -> tuple[str | None, float]:
    """Melhor tabela para `nome` e sua pontuação. Empate resolve pela
    assinatura mais específica (mais tokens exigidos)."""
    tokens = tokens_arquivo(Path(str(nome)).stem)
    if not tokens:
        return None, 0.0
    melhor, pontos, especificidade = None, 0.0, 0
    for tabela, assinatura in assinaturas.items():
        p = _pontuar_assinatura(tokens, assinatura)
        if p > pontos or (p == pontos and p > 0 and len(assinatura) > especificidade):
            melhor, pontos, especificidade = tabela, p, len(assinatura)
    if pontos < LIMIAR_NOME:
        return None, pontos
    return melhor, pontos


def identificar_tabela(nome: str) -> str | None:
    """Identifica a tabela pelo NOME de um CSV ou de uma aba do dicionário.

    Camada 1 apenas — ignora ano, prefixo de edição, acento, caixa, separadores
    e ordem das palavras. Para os CSVs, prefira `resolver_csvs`, que cai para a
    identificação por conteúdo quando o nome não basta.
    """
    return _melhor_assinatura(nome, ASSINATURA_TABELA)[0]


def identificar_questionario(nome: str) -> str | None:
    """Identifica a que tabela um questionário PDF pertence, pelo nome."""
    return _melhor_assinatura(nome, ASSINATURA_QUESTIONARIO)[0]


# --- Camada 2: identificação por conteúdo ----------------------------------

def ler_cabecalho_csv(caminho: Path) -> list[str]:
    """Lê só a primeira linha do CSV e devolve os nomes de coluna.

    Não carrega o arquivo: as tabelas de matrícula e docente têm centenas de MB
    e a identificação precisa ser barata o bastante para rodar em todas.
    """
    encoding = detectar_encoding(caminho)
    sep = detectar_delimitador(caminho, encoding)
    with open(caminho, "r", encoding=encoding, errors="replace") as fh:
        primeira = fh.readline()
    return [c.strip().strip('"').strip("'").upper()
            for c in primeira.rstrip("\r\n").split(sep) if c.strip()]


def identificar_tabela_por_cabecalho(
    colunas, variaveis_por_tabela: dict[str, set[str]]
) -> tuple[str | None, float]:
    """Identifica a tabela comparando uma lista de colunas com as variáveis que
    o dicionário declara para cada tabela.

    Pontua por *containment* (quanto do cabeçalho o dicionário cobre) e não por
    Jaccard: uma publicação pode omitir colunas que o dicionário lista sem
    deixar de ser aquela tabela. Exige também margem sobre a segunda colocada,
    porque as seis tabelas compartilham o bloco de colunas geográficas.
    """
    colunas = {str(c).strip().strip('"').strip("'").upper() for c in colunas if str(c).strip()}
    if not colunas:
        return None, 0.0

    pontuadas = sorted(
        ((len(colunas & vs) / len(colunas), t)
         for t, vs in variaveis_por_tabela.items() if vs),
        reverse=True,
    )
    if not pontuadas:
        return None, 0.0
    melhor_pontos, melhor = pontuadas[0]
    segundo = pontuadas[1][0] if len(pontuadas) > 1 else 0.0
    if melhor_pontos < LIMIAR_COLUNAS or melhor_pontos - segundo < MARGEM_COLUNAS:
        return None, melhor_pontos
    return melhor, melhor_pontos


def identificar_tabela_por_colunas(
    caminho: Path, variaveis_por_tabela: dict[str, set[str]]
) -> tuple[str | None, float]:
    """Idem, lendo o cabeçalho de um CSV em disco."""
    try:
        colunas = ler_cabecalho_csv(caminho)
    except OSError:
        return None, 0.0
    return identificar_tabela_por_cabecalho(colunas, variaveis_por_tabela)


# --- Camada 3: resolução com relatório --------------------------------------

def resolver_csvs(
    pasta: Path | None,
    variaveis_por_tabela: dict[str, set[str]] | None = None,
) -> dict:
    """Resolve {tabela: caminho_csv} em `pasta`, com relatório de proveniência.

    Devolve `{"por_tabela": {...}, "detalhes": [...], "nao_resolvidos": [...]}`.
    Cada detalhe traz `arquivo`, `tabela`, `camada` ("nome" ou "conteudo"),
    `pontos` e `conflito` — este último quando nome e conteúdo discordam, caso
    em que o CONTEÚDO prevalece (o cabeçalho é evidência mais forte que o nome)
    e a discordância fica registrada para revisão.

    Sem `variaveis_por_tabela` a camada 2 é pulada e o comportamento é o de
    identificação só por nome.
    """
    vazio: dict = {"por_tabela": {}, "detalhes": [], "nao_resolvidos": []}
    if not pasta or not pasta.is_dir():
        return vazio

    por_tabela: dict[str, Path] = {}
    detalhes: list[dict] = []
    nao_resolvidos: list[Path] = []

    for csv in sorted(pasta.rglob("*.csv")):
        por_nome, pontos_nome = _melhor_assinatura(csv.name, ASSINATURA_TABELA)
        por_conteudo, pontos_conteudo = (None, 0.0)
        if variaveis_por_tabela:
            por_conteudo, pontos_conteudo = identificar_tabela_por_colunas(
                csv, variaveis_por_tabela
            )

        tabela = por_conteudo or por_nome
        if not tabela:
            nao_resolvidos.append(csv)
            continue

        detalhes.append({
            "arquivo":  csv.name,
            "tabela":   tabela,
            "camada":   "conteudo" if por_conteudo else "nome",
            "pontos":   round(pontos_conteudo if por_conteudo else pontos_nome, 3),
            "conflito": bool(por_nome and por_conteudo and por_nome != por_conteudo),
        })
        por_tabela.setdefault(tabela, csv)

    return {
        "por_tabela": por_tabela,
        "detalhes": detalhes,
        "nao_resolvidos": nao_resolvidos,
    }


def mapear_csvs(
    pasta: Path | None,
    variaveis_por_tabela: dict[str, set[str]] | None = None,
) -> dict[str, Path]:
    """Mapeia {tabela: caminho_csv} para os CSVs reconhecidos em `pasta`."""
    return resolver_csvs(pasta, variaveis_por_tabela)["por_tabela"]


def localizar_csv(
    pasta: Path | None,
    tabela: str,
    variaveis_por_tabela: dict[str, set[str]] | None = None,
) -> Path | None:
    """Localiza o CSV da tabela em `pasta`, com qualquer nome."""
    return mapear_csvs(pasta, variaveis_por_tabela).get(tabela)


def localizar_questionario(pasta: Path | None, tabela: str) -> Path | None:
    """Localiza o questionário PDF da tabela em `pasta`, com qualquer nome.

    Entre candidatos, vence a maior pontuação de nome — é o que faz
    "quest_escola" (1.00) ganhar de "cadastro_escola_nova" (0.33) quando os
    dois estão na mesma pasta.
    """
    if not pasta or not pasta.is_dir():
        return None
    assinatura = ASSINATURA_QUESTIONARIO.get(tabela)
    if not assinatura:
        return None
    melhor, melhor_pontos = None, 0.0
    for pdf in sorted(pasta.rglob("*.pdf")):
        pontos = _pontuar_assinatura(tokens_arquivo(pdf.stem), assinatura)
        if pontos >= LIMIAR_NOME and pontos > melhor_pontos:
            melhor, melhor_pontos = pdf, pontos
    return melhor


# --- Localização dos demais insumos dentro do pacote do INEP ----------------
# A estrutura de pastas também mudou entre publicações:
#
#   Anexos/ANEXO I - Dicionário de Dados/   →  dicionario de dados/
#   Anexos/ANEXO II - Questionários.../     →  questionarios/
#   leia-me/                                →  leiame/  +  documentacao complementar/
#
# Por isso nada aqui procura por nome de PASTA: procura pelo ARQUIVO, em toda a
# árvore, e pontua o nome dele. As funções operam sobre uma lista de nomes
# (caminhos relativos ou entradas de um .zip) para que a prévia da interface e
# a extração real usem exatamente o mesmo critério e nunca discordem.

# Tokens esperados no nome do Caderno de Conceitos, com peso. "caderno" NÃO é
# obrigatório: a publicação de 2025 saiu como "cadastro_de_conceitos_e_
# orientacoes_do_censo" — erro de digitação da fonte. "conceito" carrega o
# peso, e a confirmação forte vem do texto da 1ª página.
_TOKENS_CADERNO: dict[str, float] = {
    "conceito": 0.6, "orientacao": 0.2, "caderno": 0.15, "cadastro": 0.05,
}
LIMIAR_CADERNO = 0.55

# Documentos que também citam "conceito"/"orientação" mas não são o Caderno.
_TOKENS_NAO_CADERNO: frozenset[str] = frozenset({
    "nota", "tecnica", "parecer", "juridico", "termo", "execucao",
    "descentralizada", "relatorio", "impacto", "protecao", "leia", "leiame",
})


def pontuar_caderno(nome: str) -> float:
    """Pontua o quanto um nome de PDF parece ser o Caderno de Conceitos."""
    tokens = tokens_arquivo(Path(nome).stem)
    if tokens & _TOKENS_NAO_CADERNO:
        return 0.0
    return sum(peso for t, peso in _TOKENS_CADERNO.items() if t in tokens)


def _eh_caderno_pelo_texto(caminho: Path) -> bool:
    """Confirma pelo conteúdo: a 1ª página do Caderno traz o próprio título.

    Só é consultado quando o nome não decide — abrir PDF custa caro.
    """
    try:
        import pdfplumber
        with pdfplumber.open(caminho) as pdf:
            if not pdf.pages:
                return False
            texto = _sem_acento(pdf.pages[0].extract_text() or "").lower()
    except Exception:
        return False
    return "caderno de conceito" in texto or (
        "conceito" in texto and "orientaco" in texto and "censo escolar" in texto
    )


def tabelas_do_dicionario(fonte) -> list[str]:
    """Tabelas que têm aba no dicionário, na ordem canônica do Censo.

    Lê apenas os NOMES das abas (`read_only`, sem carregar célula alguma).
    É o que define o recorte oferecido na interface: como os microdados não
    entram mais no pipeline, quem diz quais tabelas existem é o dicionário —
    antes eram os CSVs presentes no pacote.

    `fonte` é um caminho, `bytes` ou qualquer objeto file-like. Um arquivo
    ilegível devolve lista vazia; quem chama decide o que dizer ao usuário.
    """
    import openpyxl

    alvo = io.BytesIO(bytes(fonte)) if isinstance(
        fonte, (bytes, bytearray, memoryview)) else fonte
    try:
        wb = openpyxl.load_workbook(alvo, read_only=True)
    except Exception:
        return []
    try:
        achadas = {
            tabela for aba in wb.sheetnames
            if (tabela := identificar_tabela(aba.strip()))
        }
    finally:
        wb.close()
    return [t for t in ABA_PARA_ARQUIVO.values() if t in achadas]


def classificar_nomes(nomes) -> dict:
    """Classifica uma lista de nomes (entradas de zip ou caminhos relativos).

    Devolve `{"dicionario", "caderno", "questionarios", "tabelas", "csvs"}`.
    Trabalha só com strings, sem tocar em disco: é a mesma função usada pela
    prévia do zip na interface e pela extração real, o que garante que as duas
    não possam divergir.
    """
    nomes = [str(n) for n in nomes]

    def nome_base(n: str) -> str:
        return Path(n).name

    dicionario = None
    melhor_dic = 0.0
    for n in nomes:
        if not n.lower().endswith((".xlsx", ".xls")) or nome_base(n).startswith("~$"):
            continue
        tokens = tokens_arquivo(Path(n).stem)
        pontos = (1.0 if "dicionario" in tokens else 0.0) + (0.2 if "variavel" in tokens else 0.0)
        if pontos > melhor_dic:
            dicionario, melhor_dic = n, pontos
    if dicionario is None:
        # Nenhum .xlsx se diz dicionário: aceita o único .xlsx do pacote.
        candidatos = [n for n in nomes
                      if n.lower().endswith((".xlsx", ".xls"))
                      and not nome_base(n).startswith("~$")]
        if len(candidatos) == 1:
            dicionario = candidatos[0]

    caderno, melhor_cad = None, 0.0
    for n in nomes:
        if not n.lower().endswith(".pdf"):
            continue
        pontos = pontuar_caderno(nome_base(n))
        if pontos > melhor_cad:
            caderno, melhor_cad = n, pontos
    if melhor_cad < LIMIAR_CADERNO:
        caderno = None

    questionarios = [
        n for n in nomes
        if n.lower().endswith(".pdf") and identificar_questionario(nome_base(n))
    ]

    csvs = [n for n in nomes if n.lower().endswith(".csv")]
    tabelas: dict[str, str] = {}
    for n in csvs:
        tabela = identificar_tabela(nome_base(n))
        if tabela:
            tabelas.setdefault(tabela, nome_base(n))

    return {
        "dicionario":    dicionario,
        "caderno":       caderno,
        "questionarios": questionarios,
        "tabelas":       tabelas,
        "csvs":          csvs,
    }


def localizar_insumos(raiz: Path) -> dict:
    """Localiza os insumos do INEP em uma árvore já extraída.

    Devolve `{"dicionario", "caderno", "pasta_csv", "pasta_questionarios"}`
    como `Path | None`. As pastas são deduzidas dos ARQUIVOS encontrados, não
    do nome da pasta — `dados/`, `DADOS/` e `microdados/` são indiferentes.
    """
    arquivos = [p for p in raiz.rglob("*") if p.is_file()]
    relativos = {str(p.relative_to(raiz)): p for p in arquivos}
    achados = classificar_nomes(relativos.keys())

    dicionario = relativos.get(achados["dicionario"]) if achados["dicionario"] else None

    caderno = relativos.get(achados["caderno"]) if achados["caderno"] else None
    if caderno is None:
        # O nome não decidiu — pergunta ao conteúdo dos PDFs que sobraram.
        for rel, p in sorted(relativos.items()):
            if rel.lower().endswith(".pdf") and _eh_caderno_pelo_texto(p):
                caderno = p
                break

    csvs = [relativos[n] for n in achados["csvs"]]
    pasta_csv = _pasta_dominante(csvs) or _pasta_dominante(
        [p for p in arquivos if p.suffix.lower() == ".csv"]
    )

    quests = [relativos[n] for n in achados["questionarios"]]
    pasta_questionarios = _pasta_dominante(quests)

    return {
        "dicionario":         dicionario,
        "caderno":            caderno,
        "pasta_csv":          pasta_csv,
        "pasta_questionarios": pasta_questionarios,
    }


def _pasta_dominante(caminhos: list[Path]) -> Path | None:
    """Pasta que contém mais arquivos da lista. Empate resolve pela mais rasa,
    para não escolher uma subpasta quando os arquivos estão espalhados."""
    if not caminhos:
        return None
    contagem = Counter(p.parent for p in caminhos)
    return max(contagem, key=lambda d: (contagem[d], -len(d.parts)))

# ---------------------------------------------------------------------------
# Utilitários de CSV
# ---------------------------------------------------------------------------

# Codificações candidatas, em ordem de especificidade. As publicações do INEP
# já vieram em iso-8859-1 (";" como separador) e em UTF-8 com BOM (","); as duas
# precisam funcionar sem configuração. `latin-1` decodifica qualquer byte, então
# é o último da lista e nunca falha — é a rede de segurança.
_ENCODINGS_CANDIDATOS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


def detectar_encoding(caminho: Path) -> str:
    """Descobre a codificação de um CSV validando o arquivo INTEIRO.

    Validar só o começo já não basta: um arquivo latin-1 cujo primeiro acento
    apareça depois do trecho amostrado passa como UTF-8 aqui e estoura no meio
    da leitura do pandas, com centenas de MB já processados. O custo é apenas
    decodificar (~1 GB/s), sem materializar o texto.
    """
    for enc in _ENCODINGS_CANDIDATOS:
        if enc == "latin-1":
            break  # decodifica qualquer byte; não há o que validar
        decodificador = codecs.getincrementaldecoder(enc)()
        try:
            with open(caminho, "rb") as fh:
                while pedaco := fh.read(1 << 20):
                    decodificador.decode(pedaco)
                decodificador.decode(b"", final=True)
            return enc
        except UnicodeDecodeError:
            continue
    return "latin-1"


def detectar_delimitador(caminho: Path, encoding: str) -> str:
    """Detecta o separador pelo cabeçalho: o que mais aparece vence.

    Conta fora de aspas porque um rótulo de coluna com vírgula no meio ("Área,
    Curso") inverteria a contagem em um arquivo separado por ponto e vírgula.
    """
    with open(caminho, "r", encoding=encoding, errors="replace") as fh:
        cabecalho = fh.readline()
    fora_de_aspas = re.sub(r'"[^"]*"', "", cabecalho)
    contagem = {c: fora_de_aspas.count(c) for c in (";", ",", "\t", "|")}
    melhor = max(contagem, key=lambda c: (contagem[c], c == ";"))
    return melhor if contagem[melhor] else ";"


def ler_csv(caminho: Path) -> pd.DataFrame:
    encoding = detectar_encoding(caminho)
    sep = detectar_delimitador(caminho, encoding)
    return pd.read_csv(
        caminho,
        sep=sep,
        encoding=encoding,
        low_memory=False,
        dtype=str,
    )


# ---------------------------------------------------------------------------
# Extração de questões dos PDFs dos questionários
# ---------------------------------------------------------------------------

_QUESTAO_RE = re.compile(r"^\s*(\d+[a-z]?)\s*[-–]\s+(.+)", re.IGNORECASE)
# Detecta linhas com múltiplas questões mescladas (ex: "CEP 10 – UF 11 – Município")
_MULTI_QUESTAO_RE = re.compile(r"\s\d{1,2}[a-z]?\s*[-–]", re.IGNORECASE)

_STOPWORDS = {
    "a", "o", "e", "ou", "em", "de", "da", "do", "das", "dos",
    "no", "na", "nos", "nas", "ao", "aos", "um", "uma", "uns", "umas",
    "para", "com", "por", "pelo", "pela", "pelos", "pelas", "que",
    "se", "este", "esta", "esse", "essa", "seu", "sua", "seus", "suas",
    "mais", "mas", "nao", "como", "ate", "apos", "sobre", "entre",
    "cujo", "cuja", "cujos", "cujas", "the", "of", "and",
}

# Prefixos de campo muito genéricos que sozinhos não definem a variável
_PALAVRAS_GENERICAS = {"nome", "codigo", "numero", "sigla", "data", "indicador"}


def _texto_garbled(texto: str) -> bool:
    """Detecta texto com caracteres duplicados resultante de PDF mal renderizado."""
    alfa = [c for c in texto if c.isalpha()]
    if len(alfa) < 6:
        return False
    pares = sum(1 for i in range(len(alfa) - 1) if alfa[i] == alfa[i + 1])
    return pares / len(alfa) > 0.25


def _palavras_significativas(texto: str) -> set[str]:
    """Normaliza texto e retorna conjunto de palavras sem stopwords."""
    t = unicodedata.normalize("NFD", texto)
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = t.lower()
    t = re.sub(r"[^\w\s]", " ", t)
    return {w for w in t.split() if len(w) > 2 and w not in _STOPWORDS}


def _score_match(descricao: str, questao: str) -> float:
    """
    Score F1 entre palavras específicas da descrição e palavras da questão.

    Regras de qualidade mínima:
    - descrições com 1-2 palavras específicas: todas devem coincidir na questão
    - descrições com 3+ palavras específicas: ao menos 2 devem coincidir
    - a questão não pode ter mais de 8× mais palavras que a descrição (baixa precisão)
    """
    if _texto_garbled(questao):
        return 0.0

    d_words = _palavras_significativas(descricao)
    q_words = _palavras_significativas(questao)
    if not d_words or not q_words:
        return 0.0

    d_especificas = d_words - _PALAVRAS_GENERICAS or d_words

    inter = d_especificas & q_words
    n_match = len(inter)
    n_desc = len(d_especificas)
    n_ques = len(q_words)

    if n_desc <= 2 and n_match < n_desc:
        return 0.0
    if n_desc >= 3 and n_match < 2:
        return 0.0
    if n_ques > n_desc * 8:
        return 0.0

    recall    = n_match / n_desc
    precision = n_match / n_ques
    if recall + precision == 0:
        return 0.0
    return 2 * recall * precision / (recall + precision)


def extrair_questionario_html(pdf_path: Path) -> list[dict]:
    """
    Extrai as questões de um PDF de questionário preservando o número, no
    schema do `app-data` do censo.html: [{numero, texto}, ...].
    Extração de base reaproveitada por `extrair_questoes_pdf` (que descarta
    o número para o casamento com var_qstn_qstnlit) — não duplica o parsing
    do PDF.

    Quando o PDF não traz questões numeradas (formulários como o de Turma),
    recorre a `extrair_questionario_layout`, que identifica os rótulos de
    campo pelo corpo da fonte. Sem esse recurso a tabela inteira ficava com
    `var_qstn_qstnlit` vazio e o log só dizia "0 questões PDF".
    """
    try:
        import pdfplumber
    except ImportError:
        print("[aviso] pdfplumber não instalado; instale com: pip install pdfplumber")
        return []

    perguntas: list[dict] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                texto = page.extract_text() or ""
                for linha in texto.split("\n"):
                    m = _QUESTAO_RE.match(linha)
                    if not m:
                        continue
                    numero, texto_questao = m.group(1), m.group(2).strip()
                    if _texto_garbled(texto_questao):
                        continue
                    if _MULTI_QUESTAO_RE.search(texto_questao):
                        continue
                    perguntas.append({"numero": numero, "texto": texto_questao})
    except Exception as exc:
        print(f"[aviso] Erro ao ler {pdf_path.name}: {exc}")

    if not perguntas:
        perguntas = extrair_questionario_layout(pdf_path)
        if perguntas:
            print(f"  [info] {pdf_path.name}: sem questões numeradas; "
                  f"{len(perguntas)} rótulo(s) de campo extraído(s) por layout.")
        else:
            print(f"  [AVISO] {pdf_path.name}: nenhuma questão extraída "
                  f"(nem numerada, nem por layout) — var_qstn_qstnlit ficará "
                  f"vazio para as tabelas que dependem deste questionário.")

    return perguntas


def _linha_substantiva(texto: str) -> bool:
    """Linha que pode ser rótulo de campo — descarta título de seção e ruído."""
    return (
        len(texto) >= 8
        and not texto.isupper()          # cabeçalho de seção (IDENTIFICAÇÃO, ...)
        and any(c.isalpha() for c in texto)
        and not _texto_garbled(texto)
    )


def extrair_questionario_layout(pdf_path: Path) -> list[dict]:
    """Extrai os rótulos de campo de um questionário NÃO numerado.

    Nem todo questionário do INEP numera as perguntas: o de Turma, por
    exemplo, é um formulário em que o rótulo do campo ("Tipo de mediação
    didático-pedagógica") aparece num corpo de fonte maior que o das
    alternativas ("Presencial", "Semipresencial", ...). Sem numeração,
    `_QUESTAO_RE` não casa nada e a tabela inteira fica sem
    `var_qstn_qstnlit`.

    O nível de fonte dos rótulos é descoberto por estatística, não fixado:
    entre os corpos maiores que o mais frequente da página, vence o que
    rende mais linhas substantivas. Isso evita cair em pontuação de outra
    fonte (o PDF de Turma tem ":" em Times 8,6 sobre um corpo Arial 8,0).
    """
    try:
        import pdfplumber
    except ImportError:
        print("[aviso] pdfplumber não instalado; instale com: pip install pdfplumber")
        return []

    linhas: list[tuple[float, str]] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                for linha in page.extract_text_lines():
                    texto = " ".join(linha["text"].split())
                    chars = linha.get("chars") or []
                    if not texto or not chars:
                        continue
                    tamanho = Counter(round(c["size"], 1) for c in chars).most_common(1)[0][0]
                    linhas.append((tamanho, texto))
    except Exception as exc:
        print(f"[aviso] Erro ao ler layout de {pdf_path.name}: {exc}")
        return []

    if not linhas:
        return []

    corpo = Counter(t for t, _ in linhas).most_common(1)[0][0]
    por_nivel: dict[float, list[str]] = {}
    for tamanho, texto in linhas:
        if tamanho > corpo and _linha_substantiva(texto):
            por_nivel.setdefault(tamanho, []).append(texto)
    if not por_nivel:
        return []

    nivel = max(sorted(por_nivel), key=lambda t: len(por_nivel[t]))
    perguntas: list[dict] = []
    vistos: set[str] = set()
    for texto in por_nivel[nivel]:
        chave = texto.lower()
        if chave in vistos:
            continue
        vistos.add(chave)
        # Sem numeração no PDF: `numero` fica vazio em vez de inventar uma
        # sequência que não existe no documento original.
        perguntas.append({"numero": "", "texto": texto})
    return perguntas


def extrair_questoes_pdf(pdf_path: Path) -> list[str]:
    """Extrai textos de questões numeradas de um PDF de questionário."""
    return [p["texto"] for p in extrair_questionario_html(pdf_path)]


def encontrar_questao_com_score(
    descricao: str, questoes: list[str], limiar: float = 0.50
) -> tuple[str, float]:
    """Melhor questão para a descrição, com a pontuação obtida.

    Devolve ("", 0.0) quando nada supera o limiar. A pontuação é exposta
    para o relatório de casamento — sem ela não há como auditar por que uma
    variável recebeu determinada questão.
    """
    if not questoes or not descricao:
        return "", 0.0
    melhor_score = 0.0
    melhor_texto = ""
    for q in questoes:
        score = _score_match(descricao, q)
        if score > melhor_score:
            melhor_score = score
            melhor_texto = q
    if melhor_score >= limiar:
        return melhor_texto, melhor_score
    return "", 0.0


def encontrar_questao(descricao: str, questoes: list[str], limiar: float = 0.50) -> str:
    """
    Retorna o texto da questão mais similar à descrição da variável.
    Retorna '' se nenhuma questão superar o limiar de qualidade.
    """
    return encontrar_questao_com_score(descricao, questoes, limiar)[0]


# ---------------------------------------------------------------------------
# Extração de conceitos do Caderno de Conceitos e Orientações (PDF)
# ---------------------------------------------------------------------------

# Seções do Caderno que alimentam cada tabela do dicionário
TABELA_PARA_SECAO: dict[str, list[str]] = {
    "escola":        ["escola"],
    "matricula":     ["pessoa_fisica"],
    "docente":       ["pessoa_fisica"],
    "gestor":        ["pessoa_fisica"],
    "turma":         ["turma"],
    "curso_tecnico": ["turma"],
}

_STOPWORDS_CONCEITO = {
    "a", "ao", "aos", "as", "com", "da", "das", "de", "do", "dos",
    "e", "em", "entre", "esta", "este", "eu", "na", "nas", "no", "nos",
    "o", "os", "ou", "para", "pela", "pelas", "pelo", "pelos", "por",
    "qual", "que", "se", "sua", "suas", "seu", "seus", "um", "uma",
    "uns", "umas", "nao", "so", "ja", "mais", "mas", "nem",
}

# Linhas de boilerplate do PDF (exceto CONCEITOS/ORIENTAÇÕES, que têm papel funcional)
_LINHA_BOILERPLATE_CADERNO = re.compile(
    r"^(\d{1,3}|"
    r"CADERNO DE CONCEITOS.*|"
    r"1ª ETAPA DA COLETA|"
    r"MENU)$"
)


def _normalizar_conceito(texto: str) -> str:
    """Remove acentos, converte para minúsculas, remove pontuação."""
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = texto.lower()
    texto = re.sub(r"[^\w\s]", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _eh_all_caps(linha: str) -> bool:
    """True se a linha for toda em maiúsculas (letras) e tiver mais de 4 chars."""
    s = linha.strip()
    if len(s) < 5:
        return False
    letras = [c for c in s if c.isalpha()]
    return bool(letras) and all(c == c.upper() for c in letras)


def _secoes_vazias() -> dict[str, dict[str, list]]:
    return {
        "escola":        {"conceitos": [], "orientacoes": []},
        "turma":         {"conceitos": [], "orientacoes": []},
        "pessoa_fisica": {"conceitos": [], "orientacoes": []},
    }


def extrair_conceitos_pdf(caminho_pdf: Path) -> dict[str, dict[str, list]]:
    """
    Extrai do Caderno de Conceitos e Orientações os blocos de definições
    (CONCEITOS) e instruções de preenchimento (ORIENTAÇÕES), agrupados por
    seção do questionário:
      {
        'escola':        {'conceitos': [(titulo, definicao, nota)], 'orientacoes': [(titulo, texto)]},
        'turma':         {...},
        'pessoa_fisica': {...},
      }
    """
    try:
        import pdfplumber
    except ImportError:
        print("[aviso] pdfplumber não instalado; instale com: pip install pdfplumber")
        return _secoes_vazias()

    resultado = _secoes_vazias()

    all_lines: list[str] = []
    with pdfplumber.open(caminho_pdf) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for raw in text.split("\n"):
                s = raw.strip()
                if s:
                    all_lines.append(s)

    secao_atual: str | None = None
    modo_atual: str | None = None   # 'conceito' ou 'orientacao'
    titulo_atual: str | None = None
    texto_linhas: list[str] = []
    nota_linhas: list[str] = []
    em_nota = False

    def flush() -> None:
        if not (titulo_atual and secao_atual and modo_atual):
            return
        texto = " ".join(texto_linhas).strip()
        nota  = " ".join(nota_linhas).strip()
        if not texto:
            return
        if modo_atual == "conceito":
            resultado[secao_atual]["conceitos"].append((titulo_atual, texto, nota))
        else:
            resultado[secao_atual]["orientacoes"].append((titulo_atual, texto))

    i = 0
    while i < len(all_lines):
        linha = all_lines[i]

        if _LINHA_BOILERPLATE_CADERNO.match(linha):
            i += 1
            continue

        if "QUESTIONÁRIO DE ESCOLA" in linha and "PESSOA" not in linha:
            flush()
            secao_atual = "escola"
            modo_atual = titulo_atual = None
            texto_linhas, nota_linhas = [], []
            i += 1
            continue

        if "QUESTIONÁRIO DE TURMA" in linha:
            flush()
            secao_atual = "turma"
            modo_atual = titulo_atual = None
            texto_linhas, nota_linhas = [], []
            i += 1
            continue

        if "QUESTIONÁRIOS DE PESSOA" in linha or "QUESTIONÁRIO DE PESSOA" in linha:
            flush()
            secao_atual = "pessoa_fisica"
            modo_atual = titulo_atual = None
            texto_linhas, nota_linhas = [], []
            i += 1
            continue

        if linha == "CONCEITOS":
            flush()
            titulo_atual = None
            texto_linhas, nota_linhas = [], []
            em_nota = False
            modo_atual = "conceito"
            i += 1
            continue

        if linha == "ORIENTAÇÕES":
            flush()
            titulo_atual = None
            texto_linhas, nota_linhas = [], []
            em_nota = False
            modo_atual = "orientacao"
            i += 1
            continue

        if secao_atual is None or modo_atual is None:
            i += 1
            continue

        if _eh_all_caps(linha):
            partes: list[str] = [linha]
            j = i + 1
            while (
                j < len(all_lines)
                and _eh_all_caps(all_lines[j])
                and not _LINHA_BOILERPLATE_CADERNO.match(all_lines[j])
                and "QUESTIONÁRIO" not in all_lines[j]
                and all_lines[j] not in ("CONCEITOS", "ORIENTAÇÕES")
            ):
                candidato = all_lines[j]
                if candidato not in partes:   # deduplicar linhas repetidas de layout
                    partes.append(candidato)
                else:
                    break
                j += 1

            flush()
            titulo_atual = " ".join(partes)
            texto_linhas, nota_linhas = [], []
            em_nota = False
            i = j
            continue

        if titulo_atual:
            if linha.startswith("Importante!") or linha.startswith("Você sabia?"):
                em_nota = True
                nota_linhas.append(linha)
            elif em_nota:
                nota_linhas.append(linha)
            else:
                texto_linhas.append(linha)

        i += 1

    flush()  # último bloco
    return resultado


# ---------------------------------------------------------------------------
# Extração de conceitos para o censo.html (Caderno de Conceitos, schema golden)
# ---------------------------------------------------------------------------
# Diferente de extrair_conceitos_pdf/obter_metadados_caderno (que agregam o
# Caderno por variável do dicionário, para alimentar var_txt e
# var_qstn_ivuinstr do Metadata Editor), o censo.html precisa do Caderno
# estruturado por CONCEITO com granularidade fina de seção, categorias e
# destaques — algo que a extração por variável descarta (funde tudo em um
# único texto). Por isso esta extração lê o PDF de novo, mas reaproveita a
# mesma biblioteca (pdfplumber) e não duplica o pareamento com o dicionário.
# Distingue títulos/seções/categorias/destaques pela fonte tipográfica do
# Caderno (Gotham-Black/Bold = títulos e cabeçalhos, Gotham-Medium = nome de
# categoria, Gotham-Book = corpo de texto), já que o texto puro (extract_text)
# não preserva essa estrutura.

_SECAO_TOPO_LABEL: dict[str, str] = {"escola": "Escola", "turma": "Turma", "pessoa_fisica": "Pessoa Física"}

_TRIGGER_DESTAQUE: dict[str, str] = {
    "importante": "Importante",
    "voce sabia": "Você sabia",
    "atencao": "Atenção",
}

_MINUSCULAS_SECAO = {"e", "de", "do", "da", "dos", "das", "em", "a", "o", "ou", "para", "com", "no", "na"}

_PAGINA_NUM_RE = re.compile(r"^\d{1,3}$")

# Correções pontuais de cabeçalhos de seção que, no Caderno, trazem um
# complemento no título principal (tamanho 14pt) que não existe na aba
# lateral equivalente — mantém o rótulo curto e estável entre edições.
_SECAO_SUB_OVERRIDES: dict[str, str] = {
    "DADOS DE VÍNCULO DO PROFISSIONAL ESCOLAR EM SALA DE AULA": "DADOS DE VÍNCULO DO PROFISSIONAL ESCOLAR",
}


def _titulo_case_secao(texto: str) -> str:
    """Converte um cabeçalho em CAIXA ALTA para Title Case, com conectivos
    (e/de/do/...) em minúsculas — exceto na primeira palavra."""
    palavras = texto.strip().split()
    saida = []
    for i, p in enumerate(palavras):
        pl = p.lower()
        saida.append(pl if i > 0 and pl in _MINUSCULAS_SECAO else pl.capitalize())
    return " ".join(saida)


def _fonte_classe(fontname: str) -> str:
    if "Black" in fontname:
        return "black"
    if "Bold" in fontname:
        return "bold"
    if "Medium" in fontname:
        return "medium"
    return "book"


def _norm_destaque(texto: str) -> str | None:
    t = _normalizar_conceito(texto.rstrip("!:?"))
    return _TRIGGER_DESTAQUE.get(t)


def _linhas_com_fonte_pdf(page):
    """Agrupa palavras da página em linhas visuais (bucket de `top`, com
    tolerância para a leve variação de baseline entre fontes diferentes na
    mesma linha), ordenadas da esquerda para a direita."""
    words = page.extract_words(extra_attrs=["fontname", "size"])
    if not words:
        return []
    words = sorted(words, key=lambda w: (w["top"], w["x0"]))
    linhas: list[list[dict]] = []
    atual: list[dict] = []
    atual_top = None
    for w in words:
        if atual_top is None or abs(w["top"] - atual_top) <= 2.5:
            atual.append(w)
            atual_top = w["top"] if atual_top is None else atual_top
        else:
            linhas.append(sorted(atual, key=lambda x: x["x0"]))
            atual, atual_top = [w], w["top"]
    if atual:
        linhas.append(sorted(atual, key=lambda x: x["x0"]))
    return linhas


def _runs_da_pagina_pdf(page):
    """Retorna os tokens de uma página como lista de runs (mesma fonte
    consecutiva mesclada em um único texto), na ordem de leitura."""
    runs = []
    for linha in _linhas_com_fonte_pdf(page):
        texto_atual: list[str] = []
        classe_atual = size_atual = None
        for w in linha:
            classe = _fonte_classe(w["fontname"])
            if classe != classe_atual:
                if texto_atual:
                    runs.append({"texto": " ".join(texto_atual), "classe": classe_atual, "size": size_atual})
                texto_atual = []
                size_atual = w["size"]  # tamanho da 1ª palavra do run (estável mesmo com jitter de nº de página colado)
            texto_atual.append(w["text"])
            classe_atual = classe
        if texto_atual:
            runs.append({"texto": " ".join(texto_atual), "classe": classe_atual, "size": size_atual})
    return runs


def extrair_conceitos_html(caminho_pdf: Path) -> list[dict]:
    """
    Extrai do Caderno de Conceitos os CONCEITOS estruturados no schema do
    `app-data` do censo.html: [{conceito, secao, definicao, categorias,
    destaques}, ...]. Ignora os blocos de ORIENTAÇÕES (não fazem parte do
    Caderno de Conceitos navegável) e para antes dos quadros de referência
    em anexo (línguas indígenas, cursos técnicos etc. — ver
    `extrair_quadros_pdf`).
    """
    try:
        import pdfplumber
    except ImportError:
        print("[aviso] pdfplumber não instalado; instale com: pip install pdfplumber")
        return []

    with pdfplumber.open(caminho_pdf) as pdf:
        pagina_inicio = 0
        pagina_fim = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            texto_pg = (page.extract_text() or "").upper()
            if "QUESTIONÁRIO DE ESCOLA" in texto_pg:
                pagina_inicio = i
                break

        for i in range(pagina_inicio, len(pdf.pages)):
            if (pdf.pages[i].extract_text() or "").lstrip().startswith("QUADRO DE"):
                pagina_fim = i
                break

        conceitos: list[dict] = []
        secao_top: str | None = None
        secao_sub: str | None = None
        modo: str | None = None  # 'conceitos' | 'orientacoes'
        cur: dict | None = None
        titulo_buffer: list[str] = []
        secao_buffer: list[str] = []

        def flush() -> None:
            nonlocal cur
            if cur and modo == "conceitos" and cur["conceito"]:
                cur["definicao"] = cur["definicao"].strip()
                for d in cur["destaques"]:
                    d["texto"] = d["texto"].strip()
                for c in cur["categorias"]:
                    c["descricao"] = c["descricao"].strip()
                # sentinelas negativas (ex.: "Não há X") não viram categoria própria
                cur["categorias"] = [
                    c for c in cur["categorias"] if not re.match(r"^n[aã]o\b", c["nome"], re.IGNORECASE)
                ]
                if cur["definicao"] or cur["categorias"] or cur["destaques"]:
                    conceitos.append(cur)

        def resolver_titulo_buffer() -> None:
            nonlocal cur
            if not titulo_buffer:
                return
            texto_titulo = re.sub(r"\s+\d{1,3}$", "", " ".join(titulo_buffer))
            titulo_buffer.clear()
            if cur is not None and not (cur["definicao"] or cur["categorias"] or cur["destaques"]):
                cur["conceito"] = (cur["conceito"] + " " + texto_titulo).strip()
                return
            if (
                cur is not None
                and cur["conceito"] == texto_titulo
                and cur["secao_top"] == secao_top
                and cur["secao_sub"] == secao_sub
            ):
                return  # eco do título ao continuar o mesmo conceito após quebra de página
            flush()
            cur = {
                "conceito": texto_titulo, "secao_top": secao_top, "secao_sub": secao_sub,
                "definicao": "", "categorias": [], "destaques": [],
            }

        def resolver_secao_buffer() -> None:
            nonlocal secao_top, secao_sub, cur, modo
            if not secao_buffer:
                return
            resolver_titulo_buffer()
            texto_secao = re.sub(r"\s+\d{1,3}$", "", " ".join(secao_buffer))
            secao_buffer.clear()
            flush()
            m = re.match(r"^QUESTIONÁRIOS?\s+DE\s+(ESCOLA|TURMA|PESSOA)\b\s*(FÍSICA\b)?\.?", texto_secao.upper())
            if m:
                secao_top = {"ESCOLA": "escola", "TURMA": "turma", "PESSOA": "pessoa_fisica"}[m.group(1)]
                resto = texto_secao[m.end():].strip(" -—.")
                if resto.startswith("("):
                    fim_paren = resto.find(")")
                    resto = resto[fim_paren + 1:].strip(" -—.") if fim_paren != -1 else ""
                secao_sub = resto or None
            else:
                secao_sub = _SECAO_SUB_OVERRIDES.get(texto_secao, texto_secao)
            cur = None
            modo = None

        for pi in range(pagina_inicio, pagina_fim):
            for run in _runs_da_pagina_pdf(pdf.pages[pi]):
                texto = run["texto"].strip()
                if not texto:
                    continue
                classe = run["classe"]
                size = run["size"] or 0

                if _PAGINA_NUM_RE.match(texto) and classe in ("bold", "black"):
                    continue  # nº de página solto (rodapé)
                if texto in ("CADERNO DE CONCEITOS E ORIENTAÇÕES DO CENSO ESCOLAR 2025", "1ª ETAPA DA COLETA", "MENU"):
                    continue

                trigger = _norm_destaque(texto) if classe in ("bold", "black") else None

                titulo_candidato = (
                    classe in ("bold", "black") and 7.5 <= size <= 9.5
                    and texto.isupper() and trigger is None
                    and texto.upper() not in ("CONCEITOS", "ORIENTAÇÕES")
                )
                if titulo_candidato:
                    titulo_buffer.append(texto)
                    continue

                secao_candidata = (
                    classe == "black" and size >= 13 and trigger is None
                    and texto.upper() not in ("CONCEITOS", "ORIENTAÇÕES")
                )
                if secao_candidata:
                    secao_buffer.append(texto)
                    continue

                resolver_secao_buffer()
                resolver_titulo_buffer()

                if texto.upper() in ("CONCEITOS", "ORIENTAÇÕES") and classe == "black":
                    novo_modo = "conceitos" if texto.upper() == "CONCEITOS" else "orientacoes"
                    if novo_modo != modo:
                        flush()
                        cur = None
                        modo = novo_modo
                    continue

                if modo != "conceitos":
                    continue  # ignora ORIENTAÇÕES e preâmbulo

                if trigger:
                    if cur is None:
                        continue
                    cur["destaques"].append({"tipo": trigger, "texto": ""})
                    continue

                if cur is None:
                    continue

                if classe == "medium":
                    cur["categorias"].append({"nome": texto, "descricao": ""})
                    continue

                if cur["destaques"]:
                    cur["destaques"][-1]["texto"] += (" " if cur["destaques"][-1]["texto"] else "") + texto
                elif cur["categorias"]:
                    cur["categorias"][-1]["descricao"] += (" " if cur["categorias"][-1]["descricao"] else "") + texto
                else:
                    cur["definicao"] += (" " if cur["definicao"] else "") + texto

        resolver_secao_buffer()
        resolver_titulo_buffer()
        flush()

    resultado = []
    for c in conceitos:
        rotulo_topo = _SECAO_TOPO_LABEL[c["secao_top"]]
        secao = f"Questionário de {rotulo_topo}"
        if c["secao_sub"]:
            secao += f" — {_titulo_case_secao(c['secao_sub'])}"
        resultado.append({
            "conceito": c["conceito"],
            "secao": secao,
            "definicao": c["definicao"],
            "categorias": c["categorias"],
            "destaques": c["destaques"],
        })
    return resultado


# ---------------------------------------------------------------------------
# Extração dos quadros de referência do Caderno de Conceitos (anexos)
# ---------------------------------------------------------------------------
# Os quadros (língua indígena, cursos técnicos, áreas do conhecimento,
# atividades complementares, cursos de formação superior, áreas de
# pós-graduação) vêm dos anexos em tabela do próprio PDF do Caderno — não há
# extração prévia desses quadros em nenhum outro lugar do pipeline.

_QUADROS_DEFINICAO: list[dict] = [
    {"id": "lingua", "titulo": "Língua Indígena", "cols": ["codigo", "nome"],
     "labels": ["Código", "Língua"], "heading": "QUADRO DE LÍNGUA INDÍGENA"},
    {"id": "tecnicos", "titulo": "Cursos Técnicos", "cols": ["codigo", "nome"],
     "labels": ["Código", "Curso Técnico"], "heading": "QUADRO DE CURSOS TÉCNICOS"},
    {"id": "areas_conhec", "titulo": "Áreas do Conhecimento / Componentes Curriculares",
     "cols": ["area", "codigo", "nome"], "labels": ["Área Geral", "Código", "Componente Curricular"],
     "heading": "QUADRO DE ÁREAS DO CONHECIMENTO"},
    {"id": "atividade", "titulo": "Tipos de Atividade Complementar",
     "cols": ["area", "subarea", "codigo", "nome"], "labels": ["Área", "Subárea", "Código", "Atividade"],
     "heading": "QUADRO DE TIPOS DE ATIVIDADE COMPLEMENTAR"},
    {"id": "cursos_sup", "titulo": "Cursos de Formação Superior",
     "cols": ["area_nome", "curso_cod", "nome_grau"], "labels": ["Área", "Código", "Curso / Grau"],
     "heading": "QUADRO DE CURSOS DE FORMAÇÃO SUPERIOR"},
    {"id": "pos_grad", "titulo": "Áreas de Pós-Graduação", "cols": ["codigo", "nome"],
     "labels": ["Código", "Área"], "heading": "QUADRO DE ÁREAS DE PÓS-GRADUAÇÃO"},
]

_CODIGO_GENERICO_RE = re.compile(r"^\d+[A-Za-z]?\d*$")
_CODIGO_4D_RE = re.compile(r"^\d{4}$")
_CODIGO_CURSO_SUP_RE = re.compile(r"^\d{4}[A-Za-z]\d{3}$")
_CODIGO_AREA_RE = re.compile(r"^\d{1,2}$")


def _limpa_celula(valor) -> str:
    if valor is None:
        return ""
    return re.sub(r"\s+", " ", str(valor)).strip()


def _quadro_linhas_lingua(tabelas: list, estado: dict) -> list[dict]:
    linhas = []
    for tabela in tabelas:
        for row in tabela:
            for j in (0, 2, 4):
                if j + 1 >= len(row):
                    continue
                codigo, nome = _limpa_celula(row[j]), _limpa_celula(row[j + 1])
                if codigo and nome and codigo.isdigit():
                    linhas.append({"codigo": codigo, "nome": nome})
    return linhas


def _quadro_linhas_tecnicos(tabelas: list, estado: dict) -> list[dict]:
    linhas = []
    for tabela in tabelas:
        for row in tabela:
            if len(row) < 3:
                continue
            codigo, nome = _limpa_celula(row[1]), _limpa_celula(row[2])
            if codigo and nome and _CODIGO_4D_RE.match(codigo):
                linhas.append({"codigo": codigo, "nome": nome})
    return linhas


def _quadro_linhas_areas_conhec(tabelas: list, estado: dict) -> list[dict]:
    linhas = []
    for tabela in tabelas:
        for row in tabela:
            if len(row) < 2:
                continue
            c0, c1 = _limpa_celula(row[0]), _limpa_celula(row[1])
            if c0 and not c1 and not _CODIGO_GENERICO_RE.match(c0):
                estado["area"] = c0
                continue
            if c0 and c1 and _CODIGO_GENERICO_RE.match(c0):
                linhas.append({"area": estado.get("area", ""), "codigo": c0, "nome": c1})
    return linhas


def _quadro_linhas_atividade(tabelas: list, estado: dict) -> list[dict]:
    linhas = []
    for tabela in tabelas:
        for row in tabela:
            if len(row) < 4:
                continue
            area, subarea, codigo, nome = (_limpa_celula(x) for x in row[:4])
            if area:
                estado["area"] = area
            if subarea:
                estado["subarea"] = subarea
            if codigo and nome and _CODIGO_GENERICO_RE.match(codigo):
                linhas.append({
                    "area": estado.get("area", ""), "subarea": estado.get("subarea", ""),
                    "codigo": codigo, "nome": nome,
                })
    return linhas


def _quadro_linhas_cursos_sup(tabelas: list, estado: dict) -> list[dict]:
    linhas = []
    for tabela in tabelas:
        for row in tabela:
            if len(row) < 4:
                continue
            cod_area, nome_area, curso_cod, nome_grau = (_limpa_celula(x) for x in row[:4])
            if nome_area and _CODIGO_AREA_RE.match(cod_area):
                estado["area_nome"] = nome_area
            if curso_cod and nome_grau and _CODIGO_CURSO_SUP_RE.match(curso_cod):
                linhas.append({"area_nome": estado.get("area_nome", ""), "curso_cod": curso_cod, "nome_grau": nome_grau})
    return linhas


def _quadro_linhas_pos_grad(tabelas: list, estado: dict) -> list[dict]:
    linhas = []
    for tabela in tabelas:
        for row in tabela:
            if len(row) < 2:
                continue
            codigo, nome = _limpa_celula(row[0]), _limpa_celula(row[1])
            if codigo and nome and _CODIGO_GENERICO_RE.match(codigo):
                linhas.append({"codigo": codigo, "nome": nome})
    return linhas


_QUADROS_PARSERS = {
    "lingua": _quadro_linhas_lingua,
    "tecnicos": _quadro_linhas_tecnicos,
    "areas_conhec": _quadro_linhas_areas_conhec,
    "atividade": _quadro_linhas_atividade,
    "cursos_sup": _quadro_linhas_cursos_sup,
    "pos_grad": _quadro_linhas_pos_grad,
}


def extrair_quadros_pdf(caminho_pdf: Path) -> list[dict]:
    """
    Extrai os quadros de referência dos anexos do Caderno de Conceitos:
    [{id, titulo, cols, labels, rows}, ...], na mesma ordem/esquema do
    golden censo.html (ver `_QUADROS_DEFINICAO`).
    """
    try:
        import pdfplumber
    except ImportError:
        print("[aviso] pdfplumber não instalado; instale com: pip install pdfplumber")
        return []

    tabelas_por_id: dict[str, list] = {d["id"]: [] for d in _QUADROS_DEFINICAO}
    with pdfplumber.open(caminho_pdf) as pdf:
        for page in pdf.pages:
            texto = (page.extract_text() or "").lstrip()
            for d in _QUADROS_DEFINICAO:
                if texto.startswith(d["heading"]):
                    tabelas_por_id[d["id"]].append(page.extract_tables())
                    break

    resultado = []
    for d in _QUADROS_DEFINICAO:
        estado: dict = {}
        parser = _QUADROS_PARSERS[d["id"]]
        linhas: list[dict] = []
        for tabelas_pagina in tabelas_por_id[d["id"]]:
            linhas.extend(parser(tabelas_pagina, estado))
        resultado.append({
            "id": d["id"], "titulo": d["titulo"], "cols": d["cols"], "labels": d["labels"], "rows": linhas,
        })
    return resultado


def _tokens_significativos_conceito(texto: str) -> set[str]:
    """Tokens normalizados sem stopwords."""
    return {
        t for t in _normalizar_conceito(texto).split()
        if t not in _STOPWORDS_CONCEITO and len(t) > 2
    }


def _score_match_conceito(label: str, titulo_pdf: str) -> float:
    """
    Pontuação de similaridade entre o rótulo de uma variável e um título de
    conceito do Caderno. Retorna valor em [0, 1].
    """
    base_label = label.split(" - ")[0] if " - " in label else label

    toks_label = _tokens_significativos_conceito(label)
    toks_base  = _tokens_significativos_conceito(base_label)
    toks_pdf   = _tokens_significativos_conceito(titulo_pdf)

    if not toks_pdf or (not toks_label and not toks_base):
        return 0.0

    melhor_toks = toks_label if len(toks_label) > len(toks_base) else toks_base
    intersecao  = melhor_toks & toks_pdf
    cob_label   = len(intersecao) / len(melhor_toks) if melhor_toks else 0
    cob_pdf     = len(intersecao) / len(toks_pdf)    if toks_pdf   else 0

    if cob_label + cob_pdf == 0:
        return 0.0
    f1 = 2 * cob_label * cob_pdf / (cob_label + cob_pdf)

    prefix_pdf = _normalizar_conceito(titulo_pdf)[:30]
    prefix_lbl = _normalizar_conceito(base_label)[:30]
    if prefix_pdf and prefix_lbl and prefix_pdf == prefix_lbl:
        f1 = max(f1, 0.85)

    return f1


def _melhor_match_conceito(
    label: str,
    blocos: list[tuple],
    limiar: float = 0.55,
) -> tuple | None:
    """Retorna o bloco com maior pontuação acima do limiar, ou None."""
    melhor_score = limiar
    melhor = None
    for bloco in blocos:
        score = _score_match_conceito(label, bloco[0])
        if score > melhor_score:
            melhor_score = score
            melhor = bloco
    return melhor


def mapear_conceitos_por_variavel(
    secoes: dict[str, dict[str, list]],
    tabelas_variaveis: dict[str, list[dict]],
) -> dict[str, dict[str, dict]]:
    """
    Alinha os blocos de conceitos/orientações extraídos do Caderno com as
    variáveis do dicionário .xlsx, tabela a tabela — antes de qualquer JSON
    de metadados ser montado.

    Parâmetros
    ----------
    secoes            : retorno de `extrair_conceitos_pdf`
    tabelas_variaveis : {tabela: [variaveis do dicionário]}, cada variável
                        com as chaves "nome_variavel" e "descricao"

    Retorna
    -------
    {tabela: {nome_variavel: {var_txt?, var_destaque?, var_qstn_ivuinstr?}}}
    """
    resultado: dict[str, dict[str, dict]] = {}
    for tabela, variaveis in tabelas_variaveis.items():
        secoes_tabela = TABELA_PARA_SECAO.get(tabela, [])
        blocos_conceito: list[tuple] = []
        blocos_orientacao: list[tuple] = []
        for s in secoes_tabela:
            blocos_conceito.extend(secoes.get(s, {}).get("conceitos", []))
            blocos_orientacao.extend(secoes.get(s, {}).get("orientacoes", []))
        if not blocos_conceito and not blocos_orientacao:
            continue

        mapa_tabela: dict[str, dict] = {}
        for var in variaveis:
            label = var.get("descricao", "")
            nome  = var.get("nome_variavel", "")
            if not label or not nome:
                continue

            entrada: dict[str, str] = {}

            match_c = _melhor_match_conceito(label, blocos_conceito)
            if match_c:
                _, definicao, nota_imp = match_c
                if definicao:
                    entrada["var_txt"] = definicao
                if nota_imp:
                    # Destaque "Importante!"/"Você sabia?" do Caderno. O nome
                    # NÃO é var_notes: este texto fala com quem preenche o
                    # Educacenso, e vai para var_qstn_ivuinstr (§4.0).
                    entrada["var_destaque"] = nota_imp

            match_o = _melhor_match_conceito(label, [(t, txt, "") for t, txt in blocos_orientacao])
            if match_o:
                _, instrucao, _ = match_o
                if instrucao:
                    entrada["var_qstn_ivuinstr"] = instrucao

            if entrada:
                mapa_tabela[nome] = entrada

        if mapa_tabela:
            resultado[tabela] = mapa_tabela

    return resultado


# Versão do FORMATO do cache do Caderno. Entra na impressão digital para que
# uma mudança nas chaves gravadas invalide os caches antigos — sem isso, um
# cache gravado com o esquema anterior seria lido como válido (as entradas não
# mudaram) e as chaves renomeadas viriam vazias, em silêncio.
#   1 -> chaves var_txt / var_notes / var_qstn_ivuinstr
#   2 -> `var_notes` renomeada para `var_destaque` (o destaque do Caderno passou
#        a alimentar var_qstn_ivuinstr, não var_notes; ver DOCUMENTACAO §4.0)
VERSAO_CACHE_CADERNO = "2"


def fingerprint_fontes(
    caminho_pdf: Path | None,
    tabelas_variaveis: dict[str, list[dict]] | None = None,
) -> str:
    """Identidade das entradas que produziram um cache de metadados.

    Um cache do Caderno depende do PDF, do dicionário (o alinhamento é feito
    contra as variáveis dele) **e** do formato em que é gravado. Sem esta
    impressão digital os caches invalidavam só por existência do arquivo:
    alimentar o Caderno de outra edição numa pasta de saída fixa reaproveitava
    silenciosamente os conceitos da edição anterior.
    """
    h = hashlib.sha256()
    h.update(VERSAO_CACHE_CADERNO.encode("utf-8"))
    if caminho_pdf and Path(caminho_pdf).is_file():
        h.update(Path(caminho_pdf).read_bytes())
    else:
        h.update(b"<sem-pdf>")
    for tabela in sorted(tabelas_variaveis or {}):
        h.update(tabela.encode("utf-8"))
        for var in tabelas_variaveis[tabela]:
            h.update(str(var.get("nome_variavel", "")).encode("utf-8"))
    return h.hexdigest()[:16]


def ler_cache_versionado(caminho_cache: Path, fingerprint: str) -> dict | None:
    """Lê um cache só se ele tiver sido gerado pelas mesmas entradas.

    Caches no formato antigo (sem `_fingerprint`) são tratados como
    desatualizados — é o comportamento seguro: eles podem ter vindo de outro
    Caderno ou de outro dicionário.
    """
    if not caminho_cache.exists():
        return None
    try:
        with open(caminho_cache, encoding="utf-8") as fh:
            bruto = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"  [aviso] Cache {caminho_cache.name} ilegível ({exc}); refazendo.")
        return None
    if not isinstance(bruto, dict) or "_fingerprint" not in bruto:
        print(f"  [aviso] Cache {caminho_cache.name} sem impressão digital "
              f"(formato antigo); refazendo.")
        return None
    if bruto["_fingerprint"] != fingerprint:
        print(f"  [info] Cache {caminho_cache.name} veio de outras entradas "
              f"(Caderno ou dicionário mudaram); refazendo.")
        return None
    return bruto.get("dados")


def gravar_cache_versionado(caminho_cache: Path, fingerprint: str, dados) -> None:
    """Grava o cache junto da impressão digital das entradas que o geraram."""
    caminho_cache.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho_cache, "w", encoding="utf-8") as fh:
        json.dump({"_fingerprint": fingerprint, "dados": dados},
                  fh, ensure_ascii=False, indent=2)


def atualizar_case_count(caminho_json: Path, n_linhas: int) -> bool:
    """Grava no JSON de importação o nº real de linhas do .sav.

    O JSON é escrito no passo 1, antes de qualquer dado ser carregado, então
    `case_count` nascia sempre 0 e nada voltava para corrigir. Chamado ao
    fim do passo 3, quando o total de linhas finalmente é conhecido.
    """
    try:
        with open(caminho_json, encoding="utf-8") as fh:
            payload = json.load(fh)
        if payload.get("datafile", {}).get("case_count") == n_linhas:
            return False
        payload.setdefault("datafile", {})["case_count"] = n_linhas
        with open(caminho_json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        return True
    except (json.JSONDecodeError, OSError, KeyError) as exc:
        print(f"  [aviso] Não foi possível atualizar case_count em "
              f"{caminho_json.name}: {exc}")
        return False


def obter_metadados_caderno(
    caminho_caderno: Path | None,
    caminho_cache: Path,
    tabelas_variaveis: dict[str, list[dict]],
) -> dict[str, dict[str, dict]]:
    """
    Retorna os metadados do Caderno de Conceitos já estruturados e alinhados
    por variável/tabela (ver `mapear_conceitos_por_variavel`).

    O cache em `caminho_cache` só é reaproveitado se tiver sido gerado pelo
    mesmo Caderno e pelo mesmo dicionário (ver `fingerprint_fontes`); caso
    contrário o PDF é lido de novo.
    """
    fingerprint = fingerprint_fontes(caminho_caderno, tabelas_variaveis)
    em_cache = ler_cache_versionado(caminho_cache, fingerprint)
    if em_cache is not None:
        print(f"  Metadados do Caderno já estruturados: {caminho_cache.name} (scraping do PDF ignorado)")
        return em_cache

    if not caminho_caderno or not caminho_caderno.is_file():
        return {}

    print(f"  Extraindo conceitos do Caderno: {caminho_caderno.name} ...")
    try:
        secoes = extrair_conceitos_pdf(caminho_caderno)
    except Exception as exc:
        print(f"  [ERRO] Não foi possível ler o Caderno: {exc}")
        return {}

    mapa = mapear_conceitos_por_variavel(secoes, tabelas_variaveis)
    n_vars = sum(len(v) for v in mapa.values())
    print(f"  Conceitos alinhados a {n_vars} variável(is) em {len(mapa)} tabela(s).")

    gravar_cache_versionado(caminho_cache, fingerprint, mapa)
    print(f"  Metadados do Caderno estruturados salvos em: {caminho_cache.name}")

    return mapa


# ---------------------------------------------------------------------------
# Casamento conceito↔variável para var_concept (mesma fonte do censo.html)
# ---------------------------------------------------------------------------
# Diferente de `obter_metadados_caderno` acima (que alimenta var_txt/
# var_qstn_ivuinstr a partir de `extrair_conceitos_pdf`, blocos
# por seção), aqui casamos com a lista `conceitos` já estruturada por
# CONCEITO — a mesma usada no `app-data` do censo.html, produzida por
# `extrair_conceitos_html`. Não reprocessa o PDF: recebe a lista pronta.

def rotulo_conceito(titulo: str) -> str:
    """Título do conceito em Title Case, para uso como rótulo de metadado.

    Os títulos vêm em CAIXA ALTA do Caderno (é assim que aparecem no PDF),
    o que serve de cabeçalho no censo.html mas fica ruim como valor de
    `var_concept`. Converte só na saída do JSON — o censo.html continua
    exibindo o título como está no documento original.
    """
    return _titulo_case_secao(titulo) if titulo.isupper() else titulo.strip()


def indexar_conceitos(conceitos: list[dict]) -> dict[str, dict]:
    """
    Indexa a lista `conceitos` (schema do `app-data` do censo.html — ver
    `extrair_conceitos_html`) por chave normalizada do título do conceito.
    Falha graciosa: lista vazia/ausente devolve índice vazio.
    """
    if not conceitos:
        print("  [aviso] Lista de conceitos vazia; var_concept não será enriquecido.")
        return {}
    indice: dict[str, dict] = {}
    for c in conceitos:
        chave = _normalizar_conceito(c.get("conceito", ""))
        if chave:
            indice.setdefault(chave, c)
    return indice


def mapear_conceitos_para_concept(
    conceitos: list[dict],
    tabelas_variaveis: dict[str, list[dict]],
) -> dict[str, dict[str, dict]]:
    """
    Casa cada variável do dicionário com um conceito do Caderno, para
    popular `var_concept` no JSON do Metadata Editor.

    Ordem de prioridade do casamento:
      (a) nome normalizado da descrição da variável bate exatamente com o
          título normalizado de um conceito (índice);
      (b) melhor correspondência por similaridade de texto entre a
          descrição da variável e o título do conceito, reaproveitando
          `_melhor_match_conceito`/`_score_match_conceito` (mesma
          heurística já usada no casamento do Caderno com var_txt).
    Sem match confiável (abaixo do limiar), a variável fica sem conceito —
    não força casamentos duvidosos.

    Retorna {tabela: {nome_variavel: conceito_dict}}.
    """
    indice_conceitos = indexar_conceitos(conceitos)
    if not indice_conceitos:
        return {}

    blocos = [(c["conceito"], c) for c in conceitos]
    resultado: dict[str, dict[str, dict]] = {}
    for tabela, variaveis in tabelas_variaveis.items():
        mapa_tabela: dict[str, dict] = {}
        for var in variaveis:
            label = var.get("descricao", "")
            nome = var.get("nome_variavel", "")
            if not label or not nome:
                continue

            match = indice_conceitos.get(_normalizar_conceito(label))
            if match is None:
                melhor = _melhor_match_conceito(label, blocos)
                match = melhor[1] if melhor else None
            if match is not None:
                mapa_tabela[nome] = match
        if mapa_tabela:
            resultado[tabela] = mapa_tabela
    return resultado


# ---------------------------------------------------------------------------
# Leitura e normalização de metadados JSON
# ---------------------------------------------------------------------------

def _tipo_do_var_format(var_format: dict) -> str:
    if var_format.get("type") == "character":
        return "Data" if var_format.get("is_date") else "Char"
    return "Num"


def _normalizar_novo_formato(variables: list[dict]) -> list[dict]:
    result = []
    for i, v in enumerate(variables):
        tipo = _tipo_do_var_format(v.get("var_format") or {})
        rotulos: dict = {}
        for cat in v.get("var_catgry_labels") or []:
            val_str = str(cat.get("value", ""))
            texto   = cat.get("labl", "")
            if tipo == "Num":
                try:
                    rotulos[int(val_str)] = texto
                except ValueError:
                    rotulos[val_str] = texto
            else:
                rotulos[val_str] = texto
        result.append({
            "ordem":              i + 1,
            "nome_variavel":      v["name"],
            "descricao_completa": v.get("labl", ""),
            "tipo":               tipo,
            "tamanho":            v.get("loc_width"),
            "rotulos_valor":      rotulos,
        })
    return result


def encontrar_json(nome: str, pastas: list[Path]) -> Path | None:
    """Localiza o JSON de importação da tabela.

    Tenta primeiro os nomes exatos das convenções já usadas (inclusive as
    antigas, para que uma pasta de saída anterior continue processável) e, se
    nenhum bater, varre os `*_import_metadata_editor.json` da pasta e
    identifica cada um por `identificar_tabela` — assim o ano no nome
    ("ceb2025_...") não precisa ser conhecido aqui.
    """
    nome_longo = NOME_TABELA[nome]
    padroes = [
        f"{nome}_import_metadata_editor.json",
        f"{nome_longo}_import_metadata_editor.json",
        f"{nome}_metadados.json",
        f"{nome_longo}_metadados.json",
    ]
    for pasta in pastas:
        for padrao in padroes:
            p = pasta / padrao
            if p.exists():
                return p
    for pasta in pastas:
        if not pasta.is_dir():
            continue
        for p in sorted(pasta.glob("*_import_metadata_editor.json")):
            if identificar_tabela(p.name) == nome:
                return p
    return None


def nome_sav_do_json(caminho_json: Path, tabela: str, ano=None) -> str:
    """Nome do .sav que o JSON declara em `datafile.file_name`.

    O JSON do passo 1 é a FONTE do nome: os passos 2 e 3 leem daqui em vez de
    recalcular. Antes cada passo derivava o nome por conta própria e os dois
    divergiam — o JSON declarava `gestor.sav` enquanto o arquivo gravado era
    `Tabela_Gestor.sav`, e o Metadata Editor usa esse campo para amarrar o
    JSON ao arquivo de dados. Sem o campo, cai na convenção corrente.
    """
    try:
        with open(caminho_json, encoding="utf-8") as fh:
            declarado = (json.load(fh).get("datafile") or {}).get("file_name")
    except (OSError, json.JSONDecodeError, AttributeError):
        declarado = None
    if declarado and str(declarado).strip():
        return Path(str(declarado).strip()).name
    return nome_saida_sav(tabela, ano)


def carregar_metadados(caminho_json: Path) -> list[dict]:
    with open(caminho_json, encoding="utf-8") as fh:
        dados = json.load(fh)
    if "variables" in dados:
        return _normalizar_novo_formato(dados["variables"])
    return dados["variaveis"]


# ---------------------------------------------------------------------------
# Construção de metadados e gravação de SAV
# ---------------------------------------------------------------------------

RETICENCIAS = "…"


def truncar(texto: str, limite: int) -> str:
    """Trunca `texto` para caber em `limite` BYTES quando codificado em UTF-8.

    O SPSS mede rótulos em bytes, não em caracteres (ver LIMITE_ROTULO_*). Ao
    truncar por caractere, um rótulo com acentos passava do limite em bytes e
    era o readstat quem cortava — no byte exato do limite, no meio de um
    caractere multibyte. O .sav ficava com um byte-líder órfão (ex.: `\\xe2` do
    "…" que acrescentamos aqui), ou seja, UTF-8 inválido. O pyreadstat tolera
    na leitura, mas leitores estritos rejeitam o arquivo — foi o que quebrou a
    importação no Metadata Editor ("invalid byte sequence").

    Cortando aqui, com reserva para as reticências, o readstat nunca precisa
    truncar e nenhum caractere é partido ao meio.
    """
    if len(texto.encode("utf-8")) <= limite:
        return texto

    espaco = limite - len(RETICENCIAS.encode("utf-8"))
    # errors="ignore" descarta um caractere multibyte partido pela fatia.
    corte = texto.encode("utf-8")[:espaco].decode("utf-8", errors="ignore")
    pos = corte.rfind(" ")
    if pos > len(corte) * 0.6:
        corte = corte[:pos]
    return corte.rstrip(" ,.;-") + RETICENCIAS


def largura_bytes_colunas(df: pd.DataFrame) -> dict[str, int]:
    """Maior comprimento em BYTES (UTF-8) de cada coluna de texto do df.

    É o que define a largura real que o readstat reserva para a variável no
    .sav — ver `construir_meta_sav`.
    """
    larguras: dict[str, int] = {}
    for nome in df.columns:
        # Não testa `dtype == object`: conforme a versão/opções do pandas, uma
        # coluna de texto pode vir como object ou como dtype "str".
        if pd.api.types.is_numeric_dtype(df[nome]):
            continue
        serie = df[nome].dropna()
        larguras[nome] = max(
            (len(str(x).encode("utf-8")) for x in serie.unique()), default=0
        )
    return larguras


def construir_meta_sav(
    variaveis: list[dict],
    colunas_df: list[str],
    larguras_bytes: dict[str, int] | None = None,
) -> tuple[dict, dict, dict, dict, dict]:
    """Retorna (column_labels, value_labels, formatos, display_widths, medidas).

    `larguras_bytes` (ver `largura_bytes_colunas`) é o comprimento real em
    bytes dos dados de cada coluna de texto. O formato SPSS `A<n>` conta
    BYTES, enquanto o `tamanho` do dicionário do INEP conta CARACTERES: um
    valor como "2115 ET 4ª" tem 10 caracteres mas 11 bytes. Declarar `A10`
    nesse caso faz o formato mentir sobre o dado — e um leitor que fatia a
    string pela largura declarada corta no meio do "ª" (C2 AA), produzindo
    sequência UTF-8 inválida. Por isso a largura declarada é sempre o maior
    valor entre a do dicionário e a real em bytes.
    """
    meta_por_nome = {v["nome_variavel"]: v for v in variaveis}
    larguras_bytes = larguras_bytes or {}

    column_labels:  dict[str, str] = {}
    value_labels:   dict[str, dict] = {}
    formatos:       dict[str, str]  = {}
    display_widths: dict[str, int]  = {}
    medidas:        dict[str, str]  = {}

    for nome in colunas_df:
        var = meta_por_nome.get(nome)
        if var is None:
            medidas[nome] = "unknown"
            continue

        tipo = var["tipo"]

        if var.get("descricao_completa"):
            column_labels[nome] = truncar(var["descricao_completa"], LIMITE_ROTULO_VARIAVEL)

        rotulos_brutos: dict = var.get("rotulos_valor") or {}
        if rotulos_brutos:
            rv: dict = {}
            for chave_str, texto in rotulos_brutos.items():
                texto_ok = truncar(texto, LIMITE_ROTULO_VALOR)
                if tipo in ("Char", "Data"):
                    rv[chave_str] = texto_ok
                else:
                    try:
                        rv[int(chave_str)] = texto_ok
                    except ValueError:
                        rv[chave_str] = texto_ok
            value_labels[nome] = rv

        if tipo in ("Char", "Data") and var.get("tamanho"):
            largura = max(int(var["tamanho"]), larguras_bytes.get(nome, 0))
            formatos[nome]       = f"A{largura}"
            display_widths[nome] = largura
        elif tipo == "Num":
            # Sem isto o pyreadstat cai no padrão F8.2 e o .sav passa a
            # contradizer o `var_format` declarado no JSON de importação —
            # antes divergiam em 100% das numéricas. Mesma função dos dois
            # lados garante que continuem iguais.
            formatos[nome]       = formato_numerico(var)
            display_widths[nome] = largura_variavel(var)

        if rotulos_brutos:
            medidas[nome] = "nominal"
        elif tipo == "Num":
            medidas[nome] = "scale"
        else:
            medidas[nome] = "unknown"

    return column_labels, value_labels, formatos, display_widths, medidas


def gravar_sav(df: pd.DataFrame, caminho: Path, variaveis: list[dict]) -> float:
    """Grava df como .sav com metadados. Retorna tamanho em MB.

    `row_compress=True` usa a compressão de linha do próprio formato SPSS (o
    padrão do SPSS ao salvar; não é ZSAV). Reduz Tabela_Escola de ~717 MB para
    ~158 MB, o que evita estourar limites de upload/memória na importação —
    sem alterar dados nem metadados.
    """
    col_labels, val_labels, formatos, disp_widths, medidas = construir_meta_sav(
        variaveis, list(df.columns), largura_bytes_colunas(df)
    )
    kwargs: dict = dict(
        column_labels=col_labels,
        variable_value_labels=val_labels,
        variable_measure=medidas,
        row_compress=True,
    )
    if formatos:
        kwargs["variable_format"] = formatos
    if disp_widths:
        kwargs["variable_display_width"] = disp_widths
    pyreadstat.write_sav(df, str(caminho), **kwargs)
    return caminho.stat().st_size / 1_048_576
