"""Normalização de texto compartilhada pelos casamentos e pela identificação."""
from __future__ import annotations

import re
import unicodedata
from functools import cache


def sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", str(texto))
        if unicodedata.category(c) != "Mn"
    )


@cache   # os casamentos normalizam os mesmos títulos milhares de vezes
def normalizar(texto: str) -> str:
    """Sem acento, minúsculo, pontuação trocada por espaço, espaços colapsados."""
    texto = re.sub(r"[^\w\s]", " ", sem_acento(texto).lower())
    return re.sub(r"\s+", " ", texto).strip()


def espacos_normalizados(texto) -> str:
    return " ".join(str(texto).split())


_CONECTIVOS = {"e", "de", "do", "da", "dos", "das", "em", "a", "o", "ou", "para", "com", "no", "na"}


def title_case(texto: str) -> str:
    """CAIXA ALTA → Title Case, com conectivos em minúsculas (exceto a 1ª palavra)."""
    saida = []
    for i, palavra in enumerate(texto.strip().split()):
        minuscula = palavra.lower()
        saida.append(minuscula if i > 0 and minuscula in _CONECTIVOS else minuscula.capitalize())
    return " ".join(saida)
