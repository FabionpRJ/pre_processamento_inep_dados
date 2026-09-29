"""Exceções de domínio.

A biblioteca sinaliza entrada inválida com exceção; só o CLI converte em
código de saída.
"""


class EntradaInvalida(Exception):
    """Insumo ausente, ilegível ou sem o conteúdo esperado."""
