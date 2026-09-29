"""Interface: bloqueios, painel e o caso mínimo (só o dicionário), via AppTest."""
import io
import zipfile

import pytest
from streamlit.testing.v1 import AppTest

from conftest import RAIZ


def _app() -> AppTest:
    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=120)
    at.run()
    return at


def _widget(colecao, rotulo):
    return next(w for w in colecao if rotulo.lower() in (w.label or "").lower())


def _modo_arquivos(at):
    _widget(at.radio, "Forma de envio").set_value("Arquivos separados").run()


def test_sem_dicionario_para_nos_dois_modos():
    at = _app()
    assert [i.value for i in at.info] == ["Aguardando o dicionário de variáveis (.xlsx)."]
    _modo_arquivos(at)
    assert [i.value for i in at.info] == ["Aguardando o dicionário de variáveis (.xlsx)."]
    assert not at.exception


def test_zip_corrompido():
    at = _app()
    _widget(at.file_uploader, ".zip").set_value(("pacote.zip", b"lixo", "application/zip")).run()
    assert [e.value for e in at.error] == ["O .zip não pôde ser lido — arquivo corrompido ou incompleto."]


def test_opcional_marcado_sem_arquivo_bloqueia(dicionario_minimo):
    at = _app()
    _modo_arquivos(at)
    _widget(at.file_uploader, "Dicionário").set_value(
        (dicionario_minimo.name, dicionario_minimo.read_bytes(), "application/octet-stream")).run()
    assert at.info[0].value.startswith("Aguardando: Caderno de Conceitos (.pdf), questionários (.pdf).")
    assert [m.value for m in at.multiselect] == [["escola"]]
    assert _widget(at.checkbox, "no censo.html").disabled   # sem questionário


def test_so_dicionario(dicionario_minimo):
    at = _app()
    _modo_arquivos(at)
    _widget(at.file_uploader, "Dicionário").set_value(
        (dicionario_minimo.name, dicionario_minimo.read_bytes(), "application/octet-stream")).run()
    _widget(at.checkbox, "Incluir Caderno").uncheck().run()
    _widget(at.checkbox, "Incluir questionários").uncheck().run()
    _widget(at.button, "Processar").click().run()
    assert not at.exception
    assert at.success[0].value.startswith("Metadados gerados — 1 .json + censo.html em ")
    assert [w.value for w in at.warning] == [
        "Caderno de Conceitos ausente — `var_concept` ficou vazio.",
        "Questionários ausentes — `var_qstn_qstnlit` ficou vazio.",
    ]
    nomes = zipfile.ZipFile(io.BytesIO(at.session_state["resultado"].zip_bytes)).namelist()
    assert sorted(nomes) == ["ceb2025_censo.html", "ceb2025_relatorio_casamento.csv",
                             "json/ceb2025_microdados_tabela_escola_import_metadata_editor.json"]
    assert _widget(at.button, "Processar").disabled

    _widget(at.checkbox, "Gerar censo.html").uncheck().run()   # mudou opção → resultado descartado
    assert not at.success
    assert not _widget(at.button, "Processar").disabled


@pytest.fixture(autouse=True)
def _sem_estatisticas(monkeypatch):
    monkeypatch.setenv("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
