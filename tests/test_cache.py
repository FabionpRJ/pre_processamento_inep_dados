import json

from censo_etl import cache


def test_invalidacao(tmp_path):
    pdf = tmp_path / "caderno.pdf"
    pdf.write_bytes(b"pdf v1")
    destino = tmp_path / "cache.json"
    nomes = {"escola": ["A", "B"]}
    impressao = cache.impressao_digital(pdf, nomes)
    cache.gravar(destino, impressao, {"x": 1})
    assert cache.ler(destino, impressao) == {"x": 1}

    pdf.write_bytes(b"pdf v2")                                              # PDF mudou
    assert cache.ler(destino, cache.impressao_digital(pdf, nomes)) is None
    assert cache.ler(destino, cache.impressao_digital(tmp_path / "caderno.pdf", {"escola": ["A"]})) is None  # dicionário mudou

    destino.write_text(json.dumps({"x": 1}))                                # formato antigo
    assert cache.ler(destino, impressao) is None
    destino.write_text("{corrompido")                                       # corrompido
    assert cache.ler(destino, impressao) is None
    assert cache.ler(tmp_path / "nao_existe.json", impressao) is None


def test_impressao_sem_pdf_e_estavel(tmp_path):
    assert cache.impressao_digital(None) == cache.impressao_digital(tmp_path / "ausente.pdf")
    assert len(cache.impressao_digital(None)) == 16
