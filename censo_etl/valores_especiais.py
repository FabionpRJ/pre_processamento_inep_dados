"""Códigos do dicionário que NÃO são categoria (docs/especificacao.md §valores especiais).

O dicionário lista, junto das categorias, marcas de que o valor observado não
existe ou foi tratado pelo produtor — em 2025: 88888 ("valor extremo"),
9 ("Não informado"), 99999999999999 ("Sem declaração").

Quem decide é o RÓTULO, nunca o número: no mesmo dicionário o `8` é categoria
real e o `9` é "Não informado". A forma do número só audita
(`parece_sentinela`). Os dois tipos vão para `var_invalrng` e `var_imputation`
(decisão registrada em docs/decisoes.md).
"""
from __future__ import annotations

from censo_etl.texto import sem_acento

IMPUTACAO = "imputacao"         # o produtor substituiu o valor (regra de consistência)
NAO_RESPOSTA = "nao_resposta"   # o valor nunca foi declarado

# Comparados sem acento, sem caixa e com espaço normalizado. Deliberadamente
# específicos: "nao informad", não "nao" ("Não oferece" é categoria real).
MARCADORES_IMPUTACAO: tuple[str, ...] = (
    "valor extremo", "valores extremos", "outlier",
    "imputad", "imputac",
    "marcacao de valor", "marcado com o codigo",
    "tratamento de valor", "valor tratado", "valor substituido",
)
MARCADORES_NAO_RESPOSTA: tuple[str, ...] = (
    "nao informad", "nao declarad", "nao respond", "nao consta",
    "sem declaracao", "sem informacao", "sem resposta", "sem preenchimento",
    "nao aplicav", "nao se aplica", "ignorado", "desconhecido",
)

FRASE_POR_TIPO: dict[str, str] = {
    IMPUTACAO:    "marca de tratamento de consistência aplicada pelo produtor",
    NAO_RESPOSTA: "marca de ausência de declaração atribuída pelo produtor",
}


def classificar_codigo_especial(rotulo) -> str | None:
    """`IMPUTACAO`, `NAO_RESPOSTA` ou None (categoria real). Imputação tem precedência."""
    texto = " ".join(sem_acento(str(rotulo or "")).lower().split())
    if not texto:
        return None
    if any(m in texto for m in MARCADORES_IMPUTACAO):
        return IMPUTACAO
    if any(m in texto for m in MARCADORES_NAO_RESPOSTA):
        return NAO_RESPOSTA
    return None


def parece_sentinela(codigo) -> bool:
    """Só para AUDITORIA: repetição de 8 ou 9 com 2+ dígitos (88, 999, 88888...).

    Com um dígito a forma não informa nada (8 é categoria, 9 não).
    """
    if isinstance(codigo, (int, float)):
        digitos = str(abs(int(codigo)))
    else:
        digitos = str(codigo).strip().lstrip("-")
    return len(digitos) >= 2 and digitos.isdigit() and digitos[0] in "89" and len(set(digitos)) == 1


def separar_codigos_especiais(rotulos_valor: dict | None) -> tuple[dict, dict]:
    """`(reais, especiais)`, com `especiais = {codigo: (tipo, rotulo)}`."""
    reais: dict = {}
    especiais: dict = {}
    for codigo, rotulo in (rotulos_valor or {}).items():
        if tipo := classificar_codigo_especial(rotulo):
            especiais[codigo] = (tipo, rotulo)
        else:
            reais[codigo] = rotulo
    return reais, especiais


def descrever_imputacao(especiais: dict | None) -> str:
    """Texto de `var_imputation`: um item por código, com a natureza de cada um."""
    return " ".join(
        f"Código {codigo}: {FRASE_POR_TIPO.get(tipo, 'valor atribuído pelo produtor')}; "
        f"no dicionário de variáveis, “{' '.join(str(rotulo).split())}”."
        for codigo, (tipo, rotulo) in sorted((especiais or {}).items())
    )
