"""Identificação de insumos pelo NOME (camada 1 da identificação).

O nome vira um conjunto de tokens significativos e é pontuado contra a
assinatura de cada tabela. Ano, prefixo de edição, palavras de embalagem e
marcadores de versão são descartados em qualquer posição, então
`Tabela_Escola_2025` e `ceb2025_microdados_tabela_escola` dão no mesmo.
Ver docs/identificacao.md.
"""
from __future__ import annotations

import re
from pathlib import Path

from censo_etl.tabelas import TABELAS
from censo_etl.texto import sem_acento

# Palavras que aparecem nos nomes mas não dizem QUAL tabela é.
TOKENS_RUIDO: frozenset[str] = frozenset({
    # embalagem / coleção
    "tabela", "microdado", "dado", "base", "arquivo", "anexo", "planilha",
    "censo", "escolar", "educacao", "basica", "ceb", "ces", "inep",
    "csv", "xlsx", "pdf",
    # prefixo de questionário
    "quest", "questionario", "formulario",
    # artefatos que este pipeline gera (para serem reidentificáveis)
    "import", "metadata", "editor", "metadado", "sav", "json",
    # conectivos
    "de", "do", "da", "e", "em", "no", "na", "a", "o", "por", "para", "com",
    # marcadores de versão/republicação
    "v", "ver", "versao", "rev", "revisao", "final",
    "retificado", "retificada", "corrigido", "corrigida",
    "atualizado", "atualizada", "consolidado", "consolidada",
})

ASSINATURA_TABELA: dict[str, frozenset[str]] = {t.chave: t.assinatura for t in TABELAS}
ASSINATURA_QUESTIONARIO: dict[str, frozenset[str]] = {
    t.chave: t.assinatura_questionario for t in TABELAS
}

# Separa "Escola" (1.00) de "Cadastro Escola Nova" (0.33), outro formulário.
LIMIAR_NOME = 0.50

# Caderno de Conceitos: "conceito" carrega o peso porque a publicação de 2025
# saiu como "cadastro_de_conceitos" (erro de digitação da fonte).
TOKENS_CADERNO: dict[str, float] = {
    "conceito": 0.6, "orientacao": 0.2, "caderno": 0.15, "cadastro": 0.05,
}
LIMIAR_CADERNO = 0.55
# Outros PDFs do pacote que também citam "conceito"/"orientação".
TOKENS_NAO_CADERNO: frozenset[str] = frozenset({
    "nota", "tecnica", "parecer", "juridico", "termo", "execucao",
    "descentralizada", "relatorio", "impacto", "protecao", "leia", "leiame",
})

_ANO_TOKEN_RE = re.compile(r"^(?:19|20)\d{2}$")
_SO_DIGITOS_RE = re.compile(r"^\d+$")
_FRONTEIRA_ALFANUM_RE = re.compile(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])")  # "ceb2025" → "ceb 2025"


def _singular(token: str) -> str:
    """Plurais comuns do português ("gestores" → "gestor", "docentes" → "docente")."""
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
    """Conjunto de tokens significativos de um nome de arquivo ou aba."""
    bruto = _FRONTEIRA_ALFANUM_RE.sub(" ", sem_acento(texto).lower())
    tokens = set()
    for palavra in re.split(r"[^a-z0-9]+", bruto):
        if not palavra or _ANO_TOKEN_RE.match(palavra) or _SO_DIGITOS_RE.match(palavra):
            continue
        palavra = _singular(palavra)
        if palavra in TOKENS_RUIDO or len(palavra) < 2:
            continue
        tokens.add(palavra)
    return tokens


def pontuar_assinatura(tokens: set[str], assinatura: frozenset[str]) -> float:
    """Fração do nome explicada pela assinatura, que precisa estar inteira.

    Penalizar os excedentes distingue o nome que É a coisa do nome que só a
    menciona.
    """
    if not assinatura or not assinatura <= tokens:
        return 0.0
    return len(assinatura) / (len(assinatura) + len(tokens - assinatura))


def melhor_assinatura(
    nome: str, assinaturas: dict[str, frozenset[str]]
) -> tuple[str | None, float]:
    """Melhor chave para `nome` e sua pontuação; empate vai para a assinatura
    mais específica. Abaixo de `LIMIAR_NOME` devolve `(None, pontos)`."""
    tokens = tokens_arquivo(Path(str(nome)).stem)
    if not tokens:
        return None, 0.0
    melhor, pontos, especificidade = None, 0.0, 0
    for chave, assinatura in assinaturas.items():
        p = pontuar_assinatura(tokens, assinatura)
        if p > pontos or (p == pontos and p > 0 and len(assinatura) > especificidade):
            melhor, pontos, especificidade = chave, p, len(assinatura)
    if pontos < LIMIAR_NOME:
        return None, pontos
    return melhor, pontos


def identificar_tabela(nome: str) -> str | None:
    """Tabela a que um CSV, uma aba do dicionário ou um artefato gerado se refere."""
    return melhor_assinatura(nome, ASSINATURA_TABELA)[0]


def identificar_questionario(nome: str) -> str | None:
    """Tabela a que um questionário PDF se refere."""
    return melhor_assinatura(nome, ASSINATURA_QUESTIONARIO)[0]


def pontuar_caderno(nome: str) -> float:
    """O quanto um nome de PDF parece ser o Caderno de Conceitos."""
    tokens = tokens_arquivo(Path(nome).stem)
    if tokens & TOKENS_NAO_CADERNO:
        return 0.0
    return sum(peso for token, peso in TOKENS_CADERNO.items() if token in tokens)


def pontuar_dicionario(nome: str) -> float:
    tokens = tokens_arquivo(Path(nome).stem)
    return (1.0 if "dicionario" in tokens else 0.0) + (0.2 if "variavel" in tokens else 0.0)
