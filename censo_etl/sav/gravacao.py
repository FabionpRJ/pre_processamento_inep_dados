"""Gravação de `.sav` com os metadados do dicionário."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyreadstat

from censo_etl import formato
from censo_etl.dicionario import Variavel

# Limites do SPSS em BYTES UTF-8. Acima deles o readstat trunca sozinho, no
# byte exato — partindo caractere multibyte e gerando UTF-8 inválido.
LIMITE_ROTULO_VARIAVEL = 256
LIMITE_ROTULO_VALOR = 120
RETICENCIAS = "…"


def truncar(texto: str, limite: int) -> str:
    """Corta `texto` para caber em `limite` bytes UTF-8, com reticências, sem
    partir caractere. Assim o readstat nunca precisa truncar."""
    if len(texto.encode("utf-8")) <= limite:
        return texto
    espaco = limite - len(RETICENCIAS.encode("utf-8"))
    corte = texto.encode("utf-8")[:espaco].decode("utf-8", errors="ignore")
    pos = corte.rfind(" ")
    if pos > len(corte) * 0.6:
        corte = corte[:pos]
    return corte.rstrip(" ,.;-") + RETICENCIAS


def largura_bytes_colunas(df: pd.DataFrame) -> dict[str, int]:
    """Maior valor em bytes UTF-8 de cada coluna de texto.

    Texto é detectado por "não numérico": conforme a versão do pandas pode vir
    como `object` ou como dtype `str`.
    """
    return {
        nome: max((len(str(x).encode("utf-8")) for x in df[nome].dropna().unique()), default=0)
        for nome in df.columns if not pd.api.types.is_numeric_dtype(df[nome])
    }


def construir_meta_sav(variaveis: list[Variavel], colunas: list[str],
                       larguras_bytes: dict[str, int] | None = None) -> dict:
    """Argumentos de metadado para `pyreadstat.write_sav`.

    `A<n>` conta bytes: declara-se `A{max(tamanho do dicionário, bytes reais)}`,
    senão "2115 ET 4ª" (10 caracteres, 11 bytes) mentiria sobre a largura.
    """
    por_nome = {v.nome: v for v in variaveis}
    larguras_bytes = larguras_bytes or {}
    rotulos_coluna: dict[str, str] = {}
    rotulos_valor: dict[str, dict] = {}
    formatos: dict[str, str] = {}
    larguras_exibicao: dict[str, int] = {}
    medidas: dict[str, str] = {}

    for nome in colunas:
        var = por_nome.get(nome)
        if var is None:
            medidas[nome] = "unknown"
            continue
        texto = var.tipo in ("Char", "Data")
        if var.descricao:
            rotulos_coluna[nome] = truncar(var.descricao, LIMITE_ROTULO_VARIAVEL)
        if var.rotulos_valor:
            rv: dict = {}
            for chave, rotulo in var.rotulos_valor.items():
                if not texto:
                    try:
                        chave = int(chave)
                    except ValueError:
                        pass
                rv[chave] = truncar(rotulo, LIMITE_ROTULO_VALOR)
            rotulos_valor[nome] = rv
        if texto and var.tamanho:
            largura = max(int(var.tamanho), larguras_bytes.get(nome, 0))
            formatos[nome] = f"A{largura}"
            larguras_exibicao[nome] = largura
        elif var.tipo == "Num":
            # Mesma função do JSON: o .sav e o metadado declaram o mesmo formato.
            formatos[nome] = formato.formato_numerico(var.tipo, var.nome, var.tamanho)
            larguras_exibicao[nome] = formato.largura(var.tamanho)
        if var.rotulos_valor:
            medidas[nome] = "nominal"
        elif var.tipo == "Num":
            medidas[nome] = "scale"
        else:
            medidas[nome] = "unknown"

    meta: dict = {"column_labels": rotulos_coluna, "variable_value_labels": rotulos_valor,
                  "variable_measure": medidas}
    if formatos:
        meta["variable_format"] = formatos
    if larguras_exibicao:
        meta["variable_display_width"] = larguras_exibicao
    return meta


def gravar_sav(df: pd.DataFrame, caminho: Path, variaveis: list[Variavel]) -> float:
    """Grava o `.sav` e devolve o tamanho em MB.

    `row_compress` é a compressão de linha do próprio SPSS (não ZSAV): a escola
    cai de ~717 MB para ~158 MB sem mudar dados nem metadados.
    """
    meta = construir_meta_sav(variaveis, list(df.columns), largura_bytes_colunas(df))
    pyreadstat.write_sav(df, str(caminho), row_compress=True, **meta)
    return caminho.stat().st_size / 1_048_576
