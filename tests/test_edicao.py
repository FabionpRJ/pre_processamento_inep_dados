from pathlib import Path

from censo_etl.edicao import ano_de_texto, detectar_ano_censo, detectar_ano_em_cascata


def test_ano_de_texto():
    assert ano_de_texto("ceb2025_microdados") == "2025"
    assert ano_de_texto("Nota 2021 de 2025") == "2025"
    assert ano_de_texto("sem ano") is None
    assert ano_de_texto("1800") is None


def test_dicionario_decide_sozinho():
    pdfs_2025 = [Path(f"{n} 2025.pdf") for n in ("Escola", "Aluno", "Turma", "Gestor Escolar", "Caderno")]
    assert detectar_ano_censo(nomes_extra=[Path("dicionario_2026.xlsx"), *pdfs_2025]) == "2025"
    assert detectar_ano_em_cascata(Path("dicionario_2026.xlsx"), pdfs_2025) == "2026"


def test_dicionario_sem_ano_cai_nos_demais():
    assert detectar_ano_em_cascata(Path("dicionario.xlsx"), [Path("Escola 2024.pdf"), None]) == "2024"
    assert detectar_ano_em_cascata(Path("dicionario.xlsx"), [Path("Escola.pdf")]) is None


def test_ano_pelos_dados(tmp_path):
    (tmp_path / "Tabela_Escola_2030.csv").write_text("NU_ANO_CENSO;CO\n2025;1\n", encoding="latin-1")
    assert detectar_ano_censo(tmp_path, nomes_extra=["x_2027"]) == "2025"
    (tmp_path / "Tabela_Escola_2030.csv").write_text("CO;X\n1;2\n", encoding="latin-1")
    assert detectar_ano_censo(tmp_path) == "2030"
