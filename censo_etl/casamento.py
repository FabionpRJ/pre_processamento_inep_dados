"""Casamento por similaridade entre variáveis do dicionário e os textos dos PDFs.

Três casamentos, todos auditáveis no relatório de casamento:

- descrição da variável ↔ questão do questionário   → `var_qstn_qstnlit`
- descrição ↔ bloco do Caderno por seção            → `var_txt`, `var_qstn_ivuinstr`
- descrição ↔ conceito do Caderno por conceito       → `var_concept`

Sem casamento acima do limiar a variável fica sem o campo: não se força
casamento duvidoso.
"""
from __future__ import annotations

import logging
import re
from functools import cache

from censo_etl.dicionario import Variavel
from censo_etl.pdf.questionarios import texto_garbled
from censo_etl.tabelas import POR_CHAVE
from censo_etl.texto import normalizar, sem_acento, title_case

log = logging.getLogger(__name__)

LIMIAR_QUESTAO = 0.50
LIMIAR_CONCEITO = 0.55

# ---------------------------------------------------------------------------
# Descrição ↔ questão
# ---------------------------------------------------------------------------

_STOPWORDS_QUESTAO = {
    "a", "o", "e", "ou", "em", "de", "da", "do", "das", "dos",
    "no", "na", "nos", "nas", "ao", "aos", "um", "uma", "uns", "umas",
    "para", "com", "por", "pelo", "pela", "pelos", "pelas", "que",
    "se", "este", "esta", "esse", "essa", "seu", "sua", "seus", "suas",
    "mais", "mas", "nao", "como", "ate", "apos", "sobre", "entre",
    "cujo", "cuja", "cujos", "cujas", "the", "of", "and",
}
# Genéricas demais para definir a variável sozinhas.
_PALAVRAS_GENERICAS = {"nome", "codigo", "numero", "sigla", "data", "indicador"}


@cache
def _palavras_questao(texto: str) -> frozenset[str]:
    t = re.sub(r"[^\w\s]", " ", sem_acento(texto).lower())
    return frozenset(w for w in t.split() if len(w) > 2 and w not in _STOPWORDS_QUESTAO)


def pontuar_questao(descricao: str, questao: str) -> float:
    """F1 entre as palavras específicas da descrição e as da questão.

    Exige: todas as palavras quando a descrição tem até 2; ao menos 2 quando
    tem 3 ou mais; e a questão com no máximo 8× as palavras da descrição.
    """
    if texto_garbled(questao):
        return 0.0
    palavras_desc = _palavras_questao(descricao)
    palavras_q = _palavras_questao(questao)
    if not palavras_desc or not palavras_q:
        return 0.0
    especificas = palavras_desc - _PALAVRAS_GENERICAS or palavras_desc
    comuns = len(especificas & palavras_q)
    n_desc, n_q = len(especificas), len(palavras_q)
    if (n_desc <= 2 and comuns < n_desc) or (n_desc >= 3 and comuns < 2) or n_q > n_desc * 8:
        return 0.0
    recall, precisao = comuns / n_desc, comuns / n_q
    if recall + precisao == 0:
        return 0.0
    return 2 * recall * precisao / (recall + precisao)


def melhor_questao(descricao: str, questoes: list[str]) -> tuple[str, float]:
    """`(texto, pontuação)` da melhor questão, ou `("", 0.0)` abaixo do limiar."""
    if not questoes or not descricao:
        return "", 0.0
    melhor, pontos = "", 0.0
    for questao in questoes:
        p = pontuar_questao(descricao, questao)
        if p > pontos:
            melhor, pontos = questao, p
    return (melhor, pontos) if pontos >= LIMIAR_QUESTAO else ("", 0.0)


# ---------------------------------------------------------------------------
# Descrição ↔ título de conceito
# ---------------------------------------------------------------------------

_STOPWORDS_CONCEITO = {
    "a", "ao", "aos", "as", "com", "da", "das", "de", "do", "dos",
    "e", "em", "entre", "esta", "este", "eu", "na", "nas", "no", "nos",
    "o", "os", "ou", "para", "pela", "pelas", "pelo", "pelos", "por",
    "qual", "que", "se", "sua", "suas", "seu", "seus", "um", "uma",
    "uns", "umas", "nao", "so", "ja", "mais", "mas", "nem",
}


@cache
def _palavras_conceito(texto: str) -> frozenset[str]:
    return frozenset(t for t in normalizar(texto).split() if t not in _STOPWORDS_CONCEITO and len(t) > 2)


def pontuar_conceito(descricao: str, titulo: str) -> float:
    """F1 entre a descrição (ou só a parte antes de " - ") e o título do conceito;
    mesmo começo (30 caracteres normalizados) garante ao menos 0,85."""
    base = descricao.split(" - ")[0] if " - " in descricao else descricao
    palavras_desc = _palavras_conceito(descricao)
    palavras_base = _palavras_conceito(base)
    palavras_titulo = _palavras_conceito(titulo)
    if not palavras_titulo or (not palavras_desc and not palavras_base):
        return 0.0
    melhores = palavras_desc if len(palavras_desc) > len(palavras_base) else palavras_base
    comuns = melhores & palavras_titulo
    cob_desc = len(comuns) / len(melhores) if melhores else 0
    cob_titulo = len(comuns) / len(palavras_titulo)
    if cob_desc + cob_titulo == 0:
        return 0.0
    f1 = 2 * cob_desc * cob_titulo / (cob_desc + cob_titulo)
    inicio_titulo, inicio_base = normalizar(titulo)[:30], normalizar(base)[:30]
    if inicio_titulo and inicio_titulo == inicio_base:
        f1 = max(f1, 0.85)
    return f1


def _melhor_bloco(descricao: str, blocos: list[tuple]) -> tuple | None:
    """Bloco `(titulo, ...)` de maior pontuação estritamente acima do limiar."""
    melhor, pontos = None, LIMIAR_CONCEITO
    for bloco in blocos:
        p = pontuar_conceito(descricao, bloco[0])
        if p > pontos:
            melhor, pontos = bloco, p
    return melhor


def rotulo_conceito(titulo: str) -> str:
    """Título do conceito para `var_concept`: Title Case se vier em caixa alta."""
    return title_case(titulo) if titulo.isupper() else titulo.strip()


# ---------------------------------------------------------------------------
# Mapas por tabela
# ---------------------------------------------------------------------------

def mapear_secoes_por_variavel(
    secoes: dict[str, dict[str, list]], variaveis_por_tabela: dict[str, list[Variavel]]
) -> dict[str, dict[str, dict]]:
    """`{tabela: {variavel: {var_txt?, var_destaque?, var_qstn_ivuinstr?}}}`.

    Cada tabela casa só com as seções do Caderno que lhe correspondem.
    """
    resultado: dict[str, dict[str, dict]] = {}
    for tabela, variaveis in variaveis_por_tabela.items():
        secoes_tabela = POR_CHAVE[tabela].secoes_caderno if tabela in POR_CHAVE else ()
        conceitos = [b for s in secoes_tabela for b in secoes.get(s, {}).get("conceitos", [])]
        orientacoes = [(t, txt, "") for s in secoes_tabela
                       for t, txt in secoes.get(s, {}).get("orientacoes", [])]
        if not conceitos and not orientacoes:
            continue
        mapa: dict[str, dict] = {}
        for var in variaveis:
            if not var.descricao or not var.nome:
                continue
            entrada: dict[str, str] = {}
            if bloco := _melhor_bloco(var.descricao, conceitos):
                _, definicao, destaque = bloco
                if definicao:
                    entrada["var_txt"] = definicao
                if destaque:
                    entrada["var_destaque"] = destaque
            if bloco := _melhor_bloco(var.descricao, orientacoes):
                if bloco[1]:
                    entrada["var_qstn_ivuinstr"] = bloco[1]
            if entrada:
                mapa[var.nome] = entrada
        if mapa:
            resultado[tabela] = mapa
    return resultado


def mapear_conceitos_por_variavel(
    conceitos: list[dict], variaveis_por_tabela: dict[str, list[Variavel]]
) -> dict[str, dict[str, dict]]:
    """`{tabela: {variavel: conceito}}` para `var_concept`.

    Primeiro título idêntico (normalizado) à descrição; senão, o mais similar.
    """
    if not conceitos:
        log.warning("Lista de conceitos vazia; var_concept não será enriquecido.")
        return {}
    indice: dict[str, dict] = {}
    for c in conceitos:
        if chave := normalizar(c.get("conceito", "")):
            indice.setdefault(chave, c)
    if not indice:
        return {}
    blocos = [(c["conceito"], c) for c in conceitos]

    resultado: dict[str, dict[str, dict]] = {}
    for tabela, variaveis in variaveis_por_tabela.items():
        mapa: dict[str, dict] = {}
        for var in variaveis:
            if not var.descricao or not var.nome:
                continue
            conceito = indice.get(normalizar(var.descricao))
            if conceito is None and (bloco := _melhor_bloco(var.descricao, blocos)):
                conceito = bloco[1]
            if conceito is not None:
                mapa[var.nome] = conceito
        if mapa:
            resultado[tabela] = mapa
    return resultado
