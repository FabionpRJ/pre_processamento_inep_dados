"""Caches da extração do Caderno, versionados por impressão digital das entradas.

Formato gravado: `{"_fingerprint": "<16 hex>", "dados": ...}`. Um cache só é
reaproveitado se foi gerado pelo mesmo PDF, pelo mesmo dicionário e no mesmo
formato; senão é refeito. (Invalidar por mera existência reaproveitava, numa
pasta fixa, os conceitos de outra edição.)
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# Versão do FORMATO gravado. Suba ao mudar as chaves:
#   1 → var_txt / var_notes / var_qstn_ivuinstr
#   2 → var_notes renomeada para var_destaque
VERSAO_CACHE_CADERNO = "2"

CACHE_SECOES = "caderno_conceitos_metadados.json"
CACHE_CONCEITOS = "censo_html_dados.json"


def impressao_digital(caminho_pdf: Path | None, nomes_por_tabela: dict[str, list[str]] | None = None) -> str:
    """SHA-256 (16 hex) da versão do formato, dos bytes do PDF e dos nomes de variáveis."""
    h = hashlib.sha256(VERSAO_CACHE_CADERNO.encode("utf-8"))
    if caminho_pdf and Path(caminho_pdf).is_file():
        h.update(Path(caminho_pdf).read_bytes())
    else:
        h.update(b"<sem-pdf>")
    for tabela in sorted(nomes_por_tabela or {}):
        h.update(tabela.encode("utf-8"))
        for nome in nomes_por_tabela[tabela]:
            h.update(str(nome).encode("utf-8"))
    return h.hexdigest()[:16]


def ler(caminho: Path, impressao: str):
    """Os dados do cache, ou None se ausente, ilegível, antigo ou de outras entradas."""
    if not caminho.exists():
        return None
    try:
        bruto = json.loads(caminho.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Cache %s ilegível (%s); refazendo.", caminho.name, exc)
        return None
    if not isinstance(bruto, dict) or "_fingerprint" not in bruto:
        log.warning("Cache %s sem impressão digital (formato antigo); refazendo.", caminho.name)
        return None
    if bruto["_fingerprint"] != impressao:
        log.info("Cache %s veio de outras entradas (Caderno ou dicionário mudaram); refazendo.",
                 caminho.name)
        return None
    return bruto.get("dados")


def gravar(caminho: Path, impressao: str, dados) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as fh:
        json.dump({"_fingerprint": impressao, "dados": dados}, fh, ensure_ascii=False, indent=2)
