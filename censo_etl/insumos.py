"""Localização dos insumos do INEP num pacote (zip ou árvore extraída).

Nada procura por nome de PASTA, que já mudou entre publicações: os arquivos
são reconhecidos pelo próprio nome e as pastas deduzidas de onde eles caíram.
A prévia do zip e a extração real usam a mesma `classificar_nomes`, então não
podem discordar.
"""
from __future__ import annotations

import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from censo_etl.nomes import (
    ASSINATURA_QUESTIONARIO,
    LIMIAR_CADERNO,
    LIMIAR_NOME,
    identificar_questionario,
    identificar_tabela,
    pontuar_assinatura,
    pontuar_caderno,
    pontuar_dicionario,
    tokens_arquivo,
)
from censo_etl.texto import sem_acento

EXTENSOES_DICIONARIO = (".xlsx", ".xls")
# Só isto sai do zip: os CSVs de microdados não são insumo do serviço.
EXTENSOES_INSUMOS = (*EXTENSOES_DICIONARIO, ".pdf")


@dataclass
class NomesClassificados:
    """Resultado de `classificar_nomes`, com os nomes como vieram."""
    dicionario: str | None = None
    caderno: str | None = None
    questionarios: list[str] = field(default_factory=list)
    tabelas: dict[str, str] = field(default_factory=dict)   # tabela → nome do CSV
    csvs: list[str] = field(default_factory=list)


@dataclass
class InsumosLocalizados:
    dicionario: Path | None
    caderno: Path | None
    pasta_csv: Path | None
    pasta_questionarios: Path | None


def _eh_temporario_excel(nome: str) -> bool:
    return Path(nome).name.startswith("~$")


def classificar_nomes(nomes) -> NomesClassificados:
    """Classifica nomes (entradas de zip ou caminhos relativos) sem tocar em disco."""
    nomes = [str(n) for n in nomes]
    achados = NomesClassificados()

    planilhas = [n for n in nomes
                 if n.lower().endswith(EXTENSOES_DICIONARIO) and not _eh_temporario_excel(n)]
    melhor = 0.0
    for n in planilhas:
        pontos = pontuar_dicionario(n)
        if pontos > melhor:
            achados.dicionario, melhor = n, pontos
    if achados.dicionario is None and len(planilhas) == 1:
        # Nenhuma se diz dicionário: aceita a única planilha do pacote.
        achados.dicionario = planilhas[0]

    pdfs = [n for n in nomes if n.lower().endswith(".pdf")]
    melhor = 0.0
    for n in pdfs:
        pontos = pontuar_caderno(Path(n).name)
        if pontos > melhor:
            achados.caderno, melhor = n, pontos
    if melhor < LIMIAR_CADERNO:
        achados.caderno = None

    achados.questionarios = [n for n in pdfs if identificar_questionario(Path(n).name)]
    achados.csvs = [n for n in nomes if n.lower().endswith(".csv")]
    for n in achados.csvs:
        if tabela := identificar_tabela(Path(n).name):
            achados.tabelas.setdefault(tabela, Path(n).name)
    return achados


def eh_caderno_pelo_texto(caminho: Path) -> bool:
    """A 1ª página do Caderno traz o próprio título. Só usado quando o nome não
    decide, porque abrir PDF custa caro."""
    try:
        import pdfplumber
        with pdfplumber.open(caminho) as pdf:
            if not pdf.pages:
                return False
            texto = sem_acento(pdf.pages[0].extract_text() or "").lower()
    except Exception:
        return False
    return "caderno de conceito" in texto or (
        "conceito" in texto and "orientaco" in texto and "censo escolar" in texto
    )


def pasta_dominante(caminhos: list[Path]) -> Path | None:
    """Pasta com mais arquivos da lista; empate vai para a mais rasa."""
    if not caminhos:
        return None
    contagem = Counter(p.parent for p in caminhos)
    return max(contagem, key=lambda d: (contagem[d], -len(d.parts)))


def localizar_insumos(raiz: Path) -> InsumosLocalizados:
    """Dicionário, Caderno e pastas de CSV e de questionários numa árvore extraída."""
    arquivos = [p for p in raiz.rglob("*") if p.is_file()]
    relativos = {str(p.relative_to(raiz)): p for p in arquivos}
    achados = classificar_nomes(relativos)

    caderno = relativos.get(achados.caderno) if achados.caderno else None
    if caderno is None:
        caderno = next(
            (p for rel, p in sorted(relativos.items())
             if rel.lower().endswith(".pdf") and eh_caderno_pelo_texto(p)),
            None,
        )

    csvs = [relativos[n] for n in achados.csvs]
    return InsumosLocalizados(
        dicionario=relativos.get(achados.dicionario) if achados.dicionario else None,
        caderno=caderno,
        pasta_csv=pasta_dominante(csvs),
        pasta_questionarios=pasta_dominante([relativos[n] for n in achados.questionarios]),
    )


def localizar_questionario(pasta: Path | None, tabela: str) -> Path | None:
    """PDF de questionário da tabela em `pasta`; vence a maior pontuação de nome
    ("quest_escola" 1.00 ganha de "cadastro_escola_nova" 0.33)."""
    assinatura = ASSINATURA_QUESTIONARIO.get(tabela)
    if not pasta or not pasta.is_dir() or not assinatura:
        return None
    melhor, melhor_pontos = None, 0.0
    for pdf in sorted(pasta.rglob("*.pdf")):
        pontos = pontuar_assinatura(tokens_arquivo(pdf.stem), assinatura)
        if pontos >= LIMIAR_NOME and pontos > melhor_pontos:
            melhor, melhor_pontos = pdf, pontos
    return melhor


# ---------------------------------------------------------------------------
# Pacote .zip do INEP
# ---------------------------------------------------------------------------

def inspecionar_zip(arquivo) -> NomesClassificados | None:
    """Classifica o conteúdo do zip lendo só o índice central. None se ilegível.

    `arquivo` é caminho ou file-like; um file-like volta à posição 0.
    """
    try:
        with zipfile.ZipFile(arquivo) as zf:
            nomes = zf.namelist()
    except zipfile.BadZipFile:
        return None
    finally:
        _rebobinar(arquivo)
    return classificar_nomes(nomes)


def ler_membro_zip(arquivo, nome: str) -> bytes | None:
    """Um único arquivo de dentro do zip, sem extrair o resto."""
    try:
        with zipfile.ZipFile(arquivo) as zf:
            return zf.read(nome)
    except (zipfile.BadZipFile, KeyError):
        return None
    finally:
        _rebobinar(arquivo)


def extrair_insumos_zip(arquivo, destino: Path) -> None:
    """Extrai só `.xlsx`/`.xls`/`.pdf`; os CSVs de microdados ficam no arquivo."""
    try:
        with zipfile.ZipFile(arquivo) as zf:
            for info in zf.infolist():
                if not info.is_dir() and Path(info.filename).suffix.lower() in EXTENSOES_INSUMOS:
                    zf.extract(info, destino)
    finally:
        _rebobinar(arquivo)


def _rebobinar(arquivo) -> None:
    if hasattr(arquivo, "seek"):
        arquivo.seek(0)
