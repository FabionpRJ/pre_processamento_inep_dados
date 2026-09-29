"""Formato de log comum ao CLI e à interface: avisos e erros ganham etiqueta."""
from __future__ import annotations

import logging

_ETIQUETA = {logging.WARNING: "[aviso] ", logging.ERROR: "[erro] ", logging.CRITICAL: "[erro] "}


class FormatoEtiquetado(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return _ETIQUETA.get(record.levelno, "") + record.getMessage()


def registrar_saida(handler: logging.Handler, nivel: int = logging.INFO) -> logging.Handler:
    """Liga `handler` ao logger do pacote com o formato padrão; devolve o handler."""
    handler.setFormatter(FormatoEtiquetado())
    logger = logging.getLogger("censo_etl")
    logger.setLevel(nivel)
    logger.addHandler(handler)
    return handler


def remover_saida(handler: logging.Handler) -> None:
    logging.getLogger("censo_etl").removeHandler(handler)
