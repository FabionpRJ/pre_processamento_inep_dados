from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
INSUMOS = RAIZ / "exemplo_input" / "microdados_censo_escolar_2025"


@pytest.fixture
def dicionario_minimo(tmp_path) -> Path:
    """Planilha no layout do INEP, com uma aba reconhecida e outra não."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Tabela_de_Escola"
    ws.append(["Dicionário de Variáveis -   Tabela de Escola"])
    ws.append([])
    ws.append(["N", "Nome da Variável", "Descrição", "Tipo", "Tamanho", "Categoria", "Coleta por ano"])
    ws.append([None, None, None, None, None, None, 24, 25, None])
    ws.append([1, "NU_ANO_CENSO", "Ano  do Censo", "Num", 4, None, "s", "s", None])
    ws.append([2, "TP_DEPENDENCIA", "Dependência", "Num", 1,
               "1 - Federal\n2 - Estadual\ncontinuação\n9 - Não informado", "s", "s", "Nota   importante"])
    ws.append([3, "DS_ENDERECO", "Endereço", "Char", 100, "- Não se aplica a escolas extintas", "n", "n", None])
    ws.append([4, "LATITUDE", "Latitude", "Num", 20, None, None, "s", None])
    ws.append(["Fonte: INEP"])
    wb.create_sheet("Legenda")
    caminho = tmp_path / "dicionario_2025.xlsx"
    wb.save(caminho)
    return caminho
