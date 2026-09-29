import io
import zipfile
from types import SimpleNamespace

from censo_etl.erros import EntradaInvalida
from censo_etl.pipeline import ResultadoExecucao
from censo_etl.servico import (
    ResultadoApp,
    assinatura,
    avisos_de_lacunas,
    empacotar,
    explicar_erro,
    mensagem_sucesso,
)


def test_assinatura_muda_com_arquivo_e_opcao():
    a = SimpleNamespace(name="d.xlsx", size=10)
    b = SimpleNamespace(name="c.pdf", size=5)
    assert assinatura([a, None, b], (1,)) == assinatura([b, a], (1,))
    assert assinatura([a], (1,)) != assinatura([a], (2,))
    assert assinatura([a], (1,)) != assinatura([a, b], (1,))


def test_avisos_de_lacunas():
    assert avisos_de_lacunas("2025", True, True) == []
    avisos = avisos_de_lacunas(None, False, False)
    assert len(avisos) == 3 and "`ceb_microdados_tabela_*`" in avisos[0]


def test_empacotar_deixa_caches_de_fora(tmp_path):
    (tmp_path / "x_import_metadata_editor.json").write_text("{}")
    (tmp_path / "ceb_censo.html").write_text("<html>")
    (tmp_path / "caderno_conceitos_metadados.json").write_text("{}")
    r = ResultadoExecucao(ano=None, jsons=[tmp_path / "x_import_metadata_editor.json"],
                          censo_html=tmp_path / "ceb_censo.html")
    nomes = zipfile.ZipFile(io.BytesIO(empacotar(r))).namelist()
    assert sorted(nomes) == ["ceb_censo.html", "json/x_import_metadata_editor.json"]
    try:
        empacotar(ResultadoExecucao(ano=None))
    except EntradaInvalida:
        pass
    else:
        raise AssertionError("pacote sem JSON deveria falhar")


def test_mensagens():
    assert mensagem_sucesso(ResultadoApp(b"", 2, True, 75.4)) == "Metadados gerados — 2 .json + censo.html em 1m15s."
    assert explicar_erro(EntradaInvalida("sem abas")) == "sem abas"
    assert explicar_erro(zipfile.BadZipFile()).startswith("O arquivo .zip está corrompido")
    assert explicar_erro(ValueError("x")) == "ValueError: x"
