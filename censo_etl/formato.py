"""Formato numérico declarado — fonte única para o JSON e para o `.sav`.

Se os dois calculassem por conta própria voltariam a divergir (o JSON emitia
`F{n}.0` e o `.sav` saía com o padrão `F8.2` do pyreadstat).
"""
from __future__ import annotations

# Numéricas decimais; o resto do Censo é contagem ou código inteiro.
DECIMAIS_POR_VARIAVEL: dict[str, int] = {"LATITUDE": 6, "LONGITUDE": 6}
LARGURA_NUMERICA_PADRAO = 8


def decimais(tipo: str, nome: str) -> int:
    if tipo != "Num":
        return 0
    return DECIMAIS_POR_VARIAVEL.get(str(nome).upper(), 0)


def largura(tamanho) -> int:
    """A do dicionário quando houver, senão o padrão; no mínimo 1."""
    try:
        valor = int(tamanho) if tamanho else LARGURA_NUMERICA_PADRAO
    except (TypeError, ValueError):
        valor = LARGURA_NUMERICA_PADRAO
    return max(valor, 1)


def formato_numerico(tipo: str, nome: str, tamanho) -> str:
    """Formato SPSS, ex. `F8.0` / `F20.6`. A largura comporta ponto e casas."""
    casas = decimais(tipo, nome)
    w = largura(tamanho)
    if casas:
        w = max(w, casas + 2)
    return f"F{w}.{casas}"
