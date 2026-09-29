"""CSVs de microdados: formato e identificação por conteúdo (camadas 2 e 3).

Só as ferramentas standalone de `.sav` e a detecção de ano por
`NU_ANO_CENSO` leem CSV; o serviço de metadados não.
"""
from __future__ import annotations

import codecs
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from censo_etl.nomes import ASSINATURA_TABELA, melhor_assinatura

log = logging.getLogger(__name__)

# latin-1 decodifica qualquer byte: é a rede de segurança, sempre por último.
ENCODINGS_CANDIDATOS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
DELIMITADORES = (";", ",", "\t", "|")

# Containment mínimo do cabeçalho nas variáveis do dicionário e margem sobre a
# 2ª colocada (as seis tabelas compartilham o bloco de colunas geográficas).
LIMIAR_COLUNAS = 0.60
MARGEM_COLUNAS = 0.15


def detectar_encoding(caminho: Path) -> str:
    """Codificação do arquivo, validando-o INTEIRO.

    Validar só uma amostra deixa passar um latin-1 cujo primeiro acento
    apareça depois dela, e a leitura estoura no meio do arquivo.
    """
    for encoding in ENCODINGS_CANDIDATOS[:-1]:
        decodificador = codecs.getincrementaldecoder(encoding)()
        try:
            with open(caminho, "rb") as fh:
                while pedaco := fh.read(1 << 20):
                    decodificador.decode(pedaco)
                decodificador.decode(b"", final=True)
            return encoding
        except UnicodeDecodeError:
            continue
    return ENCODINGS_CANDIDATOS[-1]


def detectar_delimitador(caminho: Path, encoding: str) -> str:
    """O separador mais frequente no cabeçalho, contado fora de aspas."""
    with open(caminho, encoding=encoding, errors="replace") as fh:
        cabecalho = fh.readline()
    fora_de_aspas = re.sub(r'"[^"]*"', "", cabecalho)
    contagem = {c: fora_de_aspas.count(c) for c in DELIMITADORES}
    melhor = max(contagem, key=lambda c: (contagem[c], c == ";"))
    return melhor if contagem[melhor] else ";"


def _limpar_celula(valor: str) -> str:
    return valor.strip().strip('"').strip("'")


def primeiras_linhas(caminho: Path) -> tuple[list[str], list[str]]:
    """Nomes de coluna (maiúsculos) e valores da primeira linha de dados."""
    encoding = detectar_encoding(caminho)
    sep = detectar_delimitador(caminho, encoding)
    with open(caminho, encoding=encoding, errors="replace") as fh:
        cabecalho, primeira = fh.readline(), fh.readline()
    colunas = [_limpar_celula(c).upper() for c in cabecalho.rstrip("\r\n").split(sep)]
    valores = [_limpar_celula(v) for v in primeira.rstrip("\r\n").split(sep)] if primeira else []
    return colunas, valores


def ler_cabecalho_csv(caminho: Path) -> list[str]:
    """Só a primeira linha: as tabelas grandes passam de 100 MB."""
    return [c for c in primeiras_linhas(caminho)[0] if c]


def identificar_tabela_por_cabecalho(
    colunas, variaveis_por_tabela: dict[str, set[str]]
) -> tuple[str | None, float]:
    """Tabela cujas variáveis do dicionário mais cobrem o cabeçalho.

    Containment, não Jaccard: uma publicação pode omitir colunas que o
    dicionário lista sem deixar de ser aquela tabela.
    """
    colunas = {_limpar_celula(str(c)).upper() for c in colunas if str(c).strip()}
    if not colunas:
        return None, 0.0
    pontuadas = sorted(
        ((len(colunas & vs) / len(colunas), t) for t, vs in variaveis_por_tabela.items() if vs),
        reverse=True,
    )
    if not pontuadas:
        return None, 0.0
    melhor_pontos, melhor = pontuadas[0]
    segundo = pontuadas[1][0] if len(pontuadas) > 1 else 0.0
    if melhor_pontos < LIMIAR_COLUNAS or melhor_pontos - segundo < MARGEM_COLUNAS:
        return None, melhor_pontos
    return melhor, melhor_pontos


@dataclass
class IdentificacaoCsv:
    arquivo: Path
    tabela: str
    camada: str      # "nome" ou "conteudo"
    pontos: float
    conflito: bool   # nome e cabeçalho discordaram (vale o cabeçalho)


@dataclass
class ResolucaoCsvs:
    por_tabela: dict[str, Path]
    detalhes: list[IdentificacaoCsv]
    nao_resolvidos: list[Path]


def resolver_csvs(
    pasta: Path | None, variaveis_por_tabela: dict[str, set[str]] | None = None
) -> ResolucaoCsvs:
    """Identifica os CSVs de `pasta` por nome e, havendo variáveis, por cabeçalho.

    Quando os dois discordam vale o cabeçalho, e o conflito fica registrado.
    """
    resolucao = ResolucaoCsvs({}, [], [])
    if not pasta or not pasta.is_dir():
        return resolucao
    for csv in sorted(pasta.rglob("*.csv")):
        por_nome, pontos_nome = melhor_assinatura(csv.name, ASSINATURA_TABELA)
        por_conteudo, pontos_conteudo = None, 0.0
        if variaveis_por_tabela:
            try:
                por_conteudo, pontos_conteudo = identificar_tabela_por_cabecalho(
                    ler_cabecalho_csv(csv), variaveis_por_tabela)
            except OSError:
                pass
        tabela = por_conteudo or por_nome
        if not tabela:
            resolucao.nao_resolvidos.append(csv)
            continue
        resolucao.detalhes.append(IdentificacaoCsv(
            arquivo=csv,
            tabela=tabela,
            camada="conteudo" if por_conteudo else "nome",
            pontos=round(pontos_conteudo if por_conteudo else pontos_nome, 3),
            conflito=bool(por_nome and por_conteudo and por_nome != por_conteudo),
        ))
        resolucao.por_tabela.setdefault(tabela, csv)
    return resolucao
