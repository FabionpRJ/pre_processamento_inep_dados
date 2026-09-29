"""Leitura dos JSONs de importação gerados pelo serviço, e o que se grava de volta."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from censo_etl.dicionario import Variavel
from censo_etl.edicao import nome_saida_sav
from censo_etl.nomes import identificar_tabela

log = logging.getLogger(__name__)


def encontrar_json(tabela: str, pasta: Path) -> Path | None:
    """O `*_import_metadata_editor.json` da tabela em `pasta`, sem precisar do ano."""
    if not pasta.is_dir():
        return None
    return next((p for p in sorted(pasta.glob("*_import_metadata_editor.json"))
                 if identificar_tabela(p.name) == tabela), None)


def carregar_variaveis(caminho_json: Path) -> list[Variavel]:
    """Variáveis do JSON, no formato do dicionário (tipo, tamanho, rótulos)."""
    dados = json.loads(caminho_json.read_text(encoding="utf-8"))
    variaveis = []
    for i, v in enumerate(dados["variables"], start=1):
        fmt = v.get("var_format") or {}
        if fmt.get("type") == "character":
            tipo = "Data" if fmt.get("is_date") else "Char"
        else:
            tipo = "Num"
        rotulos: dict = {}
        for cat in v.get("var_catgry_labels") or []:
            valor = str(cat.get("value", ""))
            try:
                chave = int(valor) if tipo == "Num" else valor
            except ValueError:
                chave = valor
            rotulos[chave] = cat.get("labl", "")
        variaveis.append(Variavel(ordem=i, nome=v["name"], descricao=v.get("labl", ""),
                                  tipo=tipo, tamanho=v.get("loc_width"), rotulos_valor=rotulos))
    return variaveis


def nome_sav_do_json(caminho_json: Path, tabela: str) -> str:
    """O `.sav` que o JSON declara em `datafile.file_name` — fonte única do nome,
    para o arquivo e o metadado não divergirem. Sem o campo, a convenção sem ano."""
    try:
        declarado = (json.loads(caminho_json.read_text(encoding="utf-8")).get("datafile") or {}).get("file_name")
    except (OSError, json.JSONDecodeError, AttributeError):
        declarado = None
    if declarado and str(declarado).strip():
        return Path(str(declarado).strip()).name
    return nome_saida_sav(tabela, None)


def atualizar_case_count(caminho_json: Path, n_linhas: int) -> bool:
    """Grava no JSON o número real de linhas; True se mudou."""
    try:
        payload = json.loads(caminho_json.read_text(encoding="utf-8"))
        if payload.get("datafile", {}).get("case_count") == n_linhas:
            return False
        payload.setdefault("datafile", {})["case_count"] = n_linhas
        with open(caminho_json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        return True
    except (json.JSONDecodeError, OSError, KeyError) as exc:
        log.warning("Não foi possível atualizar case_count em %s: %s", caminho_json.name, exc)
        return False
