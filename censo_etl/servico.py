"""Lógica da interface que não depende do Streamlit (e por isso é testável)."""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field

from censo_etl.edicao import prefixo_edicao
from censo_etl.erros import EntradaInvalida
from censo_etl.pipeline import ResultadoExecucao

NOME_PACOTE = "censo_escolar_metadados.zip"


@dataclass
class ResultadoApp:
    """O que sobrevive ao rerun depois de processar."""
    zip_bytes: bytes
    n_json: int
    tem_censo_html: bool
    duracao: float
    avisos: list[str] = field(default_factory=list)


def assinatura(uploads: list, opcoes: tuple) -> tuple:
    """Identidade de uma execução (arquivos enviados + opções).

    Mudou a assinatura, o resultado anterior deixa de valer.
    """
    return tuple(sorted((u.name, u.size) for u in uploads if u is not None)), opcoes


def avisos_de_lacunas(ano: str | None, tem_caderno: bool, tem_questionarios: bool) -> list[str]:
    """Lacunas que ficam na tela junto do download, para ninguém tomar o
    resultado por completo."""
    avisos = []
    if not ano:
        avisos.append(
            "Ano da edição não determinado (nenhum insumo traz o ano no nome) — os arquivos "
            f"saíram como `{prefixo_edicao(None)}microdados_tabela_*`. Renomeie o dicionário "
            "incluindo o ano para corrigir.")
    if not tem_caderno:
        avisos.append("Caderno de Conceitos ausente — `var_concept` ficou vazio.")
    if not tem_questionarios:
        avisos.append("Questionários ausentes — `var_qstn_qstnlit` ficou vazio.")
    return avisos


def empacotar(resultado: ResultadoExecucao) -> bytes:
    """Zip de download: `json/*.json`, censo.html e relatório. Caches ficam de fora."""
    if not resultado.jsons:
        raise EntradaInvalida("Nenhum JSON de metadados foi gerado. Verifique no log se as abas "
                              "do dicionário correspondem às tabelas selecionadas.")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for caminho in sorted(resultado.jsons):
            zf.write(caminho, f"json/{caminho.name}")
        for caminho in (resultado.censo_html, resultado.relatorio):
            if caminho and caminho.is_file():
                zf.write(caminho, caminho.name)
    return buffer.getvalue()


def mensagem_sucesso(r: ResultadoApp) -> str:
    segundos = int(r.duracao)
    return (f"Metadados gerados — {r.n_json} .json" + (" + censo.html" if r.tem_censo_html else "")
            + f" em {segundos // 60}m{segundos % 60:02d}s.")


def explicar_erro(exc: BaseException) -> str:
    """Falha conhecida → orientação acionável (o traceback vai para o log)."""
    if isinstance(exc, EntradaInvalida):
        return str(exc)
    if isinstance(exc, zipfile.BadZipFile):
        return "O arquivo .zip está corrompido ou veio incompleto. Baixe de novo no site do INEP e refaça o upload."
    if isinstance(exc, KeyError):
        return f"Campo esperado ausente: {exc}. Verifique se o dicionário é de uma edição reconhecida do Censo."
    if isinstance(exc, UnicodeDecodeError):
        return "Não foi possível ler o texto de um arquivo (codificação não reconhecida)."
    if isinstance(exc, MemoryError):
        return "Memória insuficiente. Processe menos tabelas por vez — matrícula e docente são as maiores."
    if isinstance(exc, FileNotFoundError):
        return f"Arquivo esperado não encontrado: {exc.filename or exc}"
    if isinstance(exc, PermissionError):
        return f"Sem permissão de acesso ao arquivo: {exc.filename or exc}"
    return f"{type(exc).__name__}: {exc}"
