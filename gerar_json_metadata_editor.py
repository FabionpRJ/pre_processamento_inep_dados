#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gerar_json_metadata_editor.py
============================================================================
Gera, a partir do "Dicionário de Variáveis - Educação Básica" do INEP, dos
questionários PDF e do Caderno de Conceitos e Orientações do Censo Escolar,
um arquivo .json por tabela no formato esperado pelo recurso "Importar
metadados" do World Bank Metadata Editor.

Os conceitos/orientações do Caderno são primeiro estruturados e alinhados
por variável do dicionário (ver censo_lib.obter_metadados_caderno) e
gravados em cache (`caderno_conceitos_metadados.json` na pasta de saída) —
execuções seguintes reaproveitam o cache e não fazem scraping do PDF de
novo. Esse alinhamento acontece antes e junto do casamento com os
questionários, de forma que cada variável é montada em uma única passada.

    Tabela_de_Escola        -> escola_import_metadata_editor.json
    Tabela_de_Matrícula     -> matricula_import_metadata_editor.json
    Tabela_de_Docente       -> docente_import_metadata_editor.json
    Tabela_de_Turma         -> turma_import_metadata_editor.json
    Tabela_de_Gestor        -> gestor_import_metadata_editor.json
    Tabela_Curso_Técnico    -> curso_tecnico_import_metadata_editor.json

Campos gerados (conforme model.json)
-------------------------------------
  uid, sid, fid, vid, name, labl, sort_order, var_intrvl, loc_width,
  var_invalrng, var_valrng, var_sumstat, var_catgry, var_catgry_labels,
  var_format, var_format_original, file_id, interval_type,
  sum_stats_options, var_concept, var_wgt_id,
  var_universe, var_txt, var_security, var_notes, var_respunit,
  var_qstn_preqtxt, var_qstn_qstnlit, var_qstn_postqtxt,
  var_forward, var_backward, var_qstn_ivuinstr,
  var_codinstr, var_imputation, var_derivation

USO (standalone)
----------------
    python gerar_json_metadata_editor.py
    python gerar_json_metadata_editor.py dicionario.xlsx
    python gerar_json_metadata_editor.py dicionario.xlsx /pasta_saida
    python gerar_json_metadata_editor.py dicionario.xlsx /pasta_saida /pasta_questionarios
    python gerar_json_metadata_editor.py dicionario.xlsx /pasta_saida /pasta_questionarios "Caderno de Conceitos.pdf"

REQUISITOS
----------
    pip install openpyxl pdfplumber
============================================================================
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import openpyxl

from censo_lib import (
    ABA_PARA_ARQUIVO,
    FID_POR_TABELA,
    QUESTIONARIO_POR_TABELA,
    encontrar_questao,
    extrair_questoes_pdf,
    obter_metadados_caderno,
)

# ---------------------------------------------------------------------------
# Constantes locais
# ---------------------------------------------------------------------------

CODE_RE          = re.compile(r"^\s*(-?\d+)\s*-\s*(\S.*)$")
NAO_APLICAVEL_RE = re.compile(r"^\s*-\s+(\S.*)$")

SUM_STATS_OPTIONS_PADRAO = {
    "wgt": True, "freq": True, "missing": True, "vald": True,
    "min": True, "max": True, "mean": True, "mean_wgt": True,
    "stdev": True, "stdev_wgt": True,
}

# ---------------------------------------------------------------------------
# Leitura e interpretação do dicionário (.xlsx)
# ---------------------------------------------------------------------------

def parse_categoria(texto: str | None) -> tuple[dict[int, str], list[str]]:
    rotulos: dict[int, str] = {}
    notas: list[str] = []
    if not texto:
        return rotulos, notas

    entradas: list[list] = []
    for linha in str(texto).split("\n"):
        linha = linha.rstrip()
        if not linha.strip():
            continue
        m_codigo = CODE_RE.match(linha)
        if m_codigo:
            entradas.append(["codigo", int(m_codigo.group(1)), m_codigo.group(2).strip()])
            continue
        m_na = NAO_APLICAVEL_RE.match(linha)
        if m_na:
            entradas.append(["nota", None, m_na.group(1).strip()])
            continue
        if entradas:
            entradas[-1][2] = (entradas[-1][2] + " " + linha.strip()).strip()
        else:
            entradas.append(["nota", None, linha.strip()])

    for tipo, chave, txt in entradas:
        if tipo == "codigo":
            rotulos[chave] = txt
        else:
            notas.append(txt)
    return rotulos, notas


def localizar_linha_cabecalho(linhas: list[tuple]) -> int:
    for i, linha in enumerate(linhas):
        if linha and linha[0] == "N":
            return i
    raise ValueError('Linha de cabeçalho ("N | Nome da Variável | ...") não encontrada.')


def localizar_titulo(linhas: list[tuple], header_idx: int) -> str:
    for linha in linhas[:header_idx]:
        if not linha:
            continue
        for valor in linha:
            if valor and "Dicionário de Variáveis" in str(valor):
                return " ".join(str(valor).split())
    return "Dicionário de Variáveis"


def ler_aba(ws) -> dict:
    linhas = list(ws.iter_rows(values_only=True))
    header_idx = localizar_linha_cabecalho(linhas)
    titulo = localizar_titulo(linhas, header_idx)

    linha_anos = linhas[header_idx + 1]
    colunas_ano = []
    j = 6
    while j < len(linha_anos) and linha_anos[j] is not None:
        colunas_ano.append((j, f"20{str(linha_anos[j]).strip()}"))
        j += 1
    col_notas = j

    variaveis = []
    for linha in linhas[header_idx + 2:]:
        if linha is None or linha[0] is None or not isinstance(linha[0], (int, float)):
            continue
        nome = (linha[1] or "").strip()
        if not nome:
            continue
        descricao = " ".join(str(linha[2] or "").split())
        tipo = (str(linha[3]).strip() if linha[3] else "Num")
        tamanho = linha[4] if isinstance(linha[4], (int, float)) else None
        categoria_bruta = linha[5]
        anos_coleta = {}
        for idx_col, ano in colunas_ano:
            v = linha[idx_col] if idx_col < len(linha) else None
            anos_coleta[ano] = str(v).strip().lower() if v is not None else None
        notas_importantes = linha[col_notas] if col_notas < len(linha) else None
        if notas_importantes:
            notas_importantes = " ".join(str(notas_importantes).split())

        rotulos_valor, notas_aplicabilidade = parse_categoria(categoria_bruta)

        variaveis.append({
            "ordem":                          int(linha[0]),
            "nome_variavel":                  nome,
            "descricao":                      descricao,
            "tipo":                           tipo,
            "tamanho":                        tamanho,
            "rotulos_valor":                  rotulos_valor,
            "notas_aplicabilidade_categoria": notas_aplicabilidade,
            "anos_coleta":                    anos_coleta,
            "notas_importantes":              notas_importantes or None,
        })

    return {"titulo": titulo, "variaveis": variaveis}


def ler_dicionario(caminho_xlsx: Path) -> dict:
    wb = openpyxl.load_workbook(caminho_xlsx, data_only=True)
    tabelas = {}
    abas_por_nome_limpo = {nome.strip(): nome for nome in wb.sheetnames}
    for aba_dicionario, nome_arquivo in ABA_PARA_ARQUIVO.items():
        nome_real = abas_por_nome_limpo.get(aba_dicionario)
        if nome_real is None:
            print(f'[aviso] aba "{aba_dicionario}" não encontrada no arquivo; pulando.')
            continue
        tabelas[nome_arquivo] = ler_aba(wb[nome_real])
    return tabelas


# ---------------------------------------------------------------------------
# Montagem do JSON no formato do Metadata Editor
# ---------------------------------------------------------------------------

def montar_var_format(var: dict) -> dict:
    tipo = var["tipo"]
    if tipo in ("Char", "Data"):
        largura = int(var["tamanho"]) if var["tamanho"] else 1
        return {
            "type": "character", "schema": "other", "readstat_type": "string",
            "data_format": f"A{largura}", "is_date": tipo == "Data",
        }
    largura = int(var["tamanho"]) if var["tamanho"] else 8
    return {
        "type": "numeric", "schema": "other", "readstat_type": "double",
        "data_format": f"F{largura}.0", "is_date": False,
    }


def _anos_coletados(var: dict) -> str:
    """Formata os anos de coleta da variável como string de universo."""
    anos_coleta = var.get("anos_coleta") or {}
    anos_sim = sorted(ano for ano, val in anos_coleta.items() if val == "s")
    if not anos_sim:
        return ""
    if len(anos_sim) == 1:
        return f"Coletado em {anos_sim[0]}"
    return f"Coletado em: {anos_sim[0]}–{anos_sim[-1]}"


def montar_variavel(
    var: dict,
    indice: int,
    fid: str,
    questao_literal: str = "",
    conceito: dict | None = None,
) -> dict:
    tipo = var["tipo"]
    var_format = montar_var_format(var)
    loc_width = int(var["tamanho"]) if (tipo in ("Char", "Data") and var["tamanho"]) else 8
    sid = fid.replace("F", "")

    categorias = [
        {"value": str(codigo), "labl": texto}
        for codigo, texto in sorted(var["rotulos_valor"].items())
    ]

    # Conceitos/orientações do Caderno, já estruturados e alinhados por
    # variável (ver censo_lib.obter_metadados_caderno). Preservam o dado do
    # dicionário quando o Caderno não traz definição correspondente.
    conceito = conceito or {}
    var_txt = conceito.get("var_txt") or var["descricao"]
    var_notes = var.get("notas_importantes") or ""
    nota_caderno = conceito.get("var_notes")
    if nota_caderno:
        var_notes = f"{var_notes}\n{nota_caderno}".strip() if var_notes else nota_caderno

    return {
        "uid":                  str(indice),
        "sid":                  sid,
        "fid":                  fid,
        "vid":                  f"V{indice}",
        "name":                 var["nome_variavel"],
        "labl":                 var["descricao"],
        "sort_order":           str(indice - 1),
        "var_intrvl":           "discrete",
        "loc_width":            loc_width,
        "var_invalrng":         {"values": []},
        "var_valrng":           {"range": {"UNITS": "REAL", "count": 0, "min": "", "max": ""}},
        "var_sumstat":          [],
        "var_catgry":           [],
        "var_catgry_labels":    categorias,
        "var_format":           var_format,
        "var_format_original":  var_format,
        "file_id":              fid,
        "interval_type":        "discrete",
        "sum_stats_options":    SUM_STATS_OPTIONS_PADRAO,
        "var_concept":          [[]],
        "var_wgt_id":           "",
        "var_universe":         _anos_coletados(var),
        "var_txt":              var_txt,
        "var_security":         "",
        "var_notes":            var_notes,
        "var_respunit":         "",
        "var_qstn_preqtxt":     "",
        "var_qstn_qstnlit":     questao_literal,
        "var_qstn_postqtxt":    "",
        "var_forward":          "",
        "var_backward":         "",
        "var_qstn_ivuinstr":    conceito.get("var_qstn_ivuinstr", ""),
        "var_codinstr":         "",
        "var_imputation":       "",
        "var_derivation":       "",
    }


def montar_datafile(nome_arquivo: str, titulo: str, total_variaveis: int, fid: str) -> dict:
    return {
        "file_id":    fid,
        "fid":        fid,
        "file_name":  f"{nome_arquivo}.sav",
        "labl":       titulo,
        "var_count":  total_variaveis,
        "case_count": 0,
    }


def gerar_json_importacao(
    nome_arquivo: str,
    titulo: str,
    variaveis: list[dict],
    pasta_saida: Path,
    questoes: list[str] | None = None,
    conceitos_por_variavel: dict[str, dict] | None = None,
) -> Path:
    fid = FID_POR_TABELA.get(nome_arquivo, "F1")
    questoes = questoes or []
    conceitos_por_variavel = conceitos_por_variavel or {}

    vars_montadas = [
        montar_variavel(
            v, i + 1, fid,
            encontrar_questao(v["descricao"], questoes),
            conceitos_por_variavel.get(v["nome_variavel"]),
        )
        for i, v in enumerate(variaveis)
    ]

    payload = {
        "datafile":  montar_datafile(nome_arquivo, titulo, len(variaveis), fid),
        "variables": vars_montadas,
    }
    pasta_saida.mkdir(parents=True, exist_ok=True)
    caminho = pasta_saida / f"{nome_arquivo}_import_metadata_editor.json"
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return caminho


def localizar_dicionario_padrao() -> Path | None:
    candidatos = sorted(Path(".").glob("*dicion*.xlsx"))
    return candidatos[0] if candidatos else None


def localizar_caderno_padrao() -> Path | None:
    for p in sorted(Path(".").glob("*.pdf")):
        nome = p.name.lower()
        if "caderno" in nome and "conceito" in nome:
            return p
    return None


# ---------------------------------------------------------------------------
# API pública (usada por main.py)
# ---------------------------------------------------------------------------

def executar(
    caminho_xlsx: Path,
    pasta_saida: Path,
    pasta_questionarios: Path | None = None,
    caminho_caderno: Path | None = None,
) -> None:
    if not caminho_xlsx.exists():
        sys.exit(f'Arquivo não encontrado: "{caminho_xlsx}"')
    print(f'Lendo dicionário: "{caminho_xlsx}"')
    tabelas = ler_dicionario(caminho_xlsx)
    pasta_saida.mkdir(parents=True, exist_ok=True)

    usar_pdfs = pasta_questionarios is not None and pasta_questionarios.is_dir()
    if usar_pdfs:
        print(f'Questionários: "{pasta_questionarios.resolve()}"')
    else:
        print("[aviso] Pasta de questionários não informada; var_qstn_qstnlit ficará vazio.")

    # Estrutura os conceitos/orientações do Caderno alinhados por variável,
    # antes de montar qualquer JSON. Se já existir um cache estruturado em
    # `pasta_saida`, o scraping do PDF é ignorado.
    caminho_cache_caderno = pasta_saida / "caderno_conceitos_metadados.json"
    tabelas_variaveis = {nome: info["variaveis"] for nome, info in tabelas.items()}
    print("Metadados do Caderno de Conceitos:")
    metadados_caderno = obter_metadados_caderno(
        caminho_caderno, caminho_cache_caderno, tabelas_variaveis
    )
    if not metadados_caderno:
        print("  [aviso] Nenhum metadado do Caderno disponível; var_txt/var_qstn_ivuinstr do Caderno ficarão vazios.")

    for nome_arquivo, info in tabelas.items():
        questoes: list[str] = []
        if usar_pdfs:
            nome_pdf = QUESTIONARIO_POR_TABELA.get(nome_arquivo)
            if nome_pdf:
                pdf_path = pasta_questionarios / nome_pdf
                if pdf_path.exists():
                    questoes = extrair_questoes_pdf(pdf_path)
                else:
                    print(f"  [aviso] PDF não encontrado: {pdf_path}")

        n_questoes = len(questoes)
        n_com_match = sum(
            1 for v in info["variaveis"]
            if encontrar_questao(v["descricao"], questoes)
        )
        conceitos_tabela = metadados_caderno.get(nome_arquivo, {})
        caminho = gerar_json_importacao(
            nome_arquivo, info["titulo"], info["variaveis"], pasta_saida, questoes,
            conceitos_tabela,
        )
        match_info = f", {n_com_match}/{len(info['variaveis'])} vars com questão" if n_questoes else ""
        conceito_info = f", {len(conceitos_tabela)}/{len(info['variaveis'])} vars com conceito" if conceitos_tabela else ""
        print(f"  OK: {caminho.name}  ({len(info['variaveis'])} vars, {n_questoes} questões PDF{match_info}{conceito_info})")

    print(f"\nJSONs gravados em: {pasta_saida.resolve()}")


# ---------------------------------------------------------------------------
# Ponto de entrada standalone
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) > 1:
        caminho_xlsx = Path(sys.argv[1])
    else:
        caminho_xlsx = localizar_dicionario_padrao()
        if caminho_xlsx is None:
            sys.exit(
                "Informe o caminho do dicionário .xlsx:\n"
                "    python gerar_json_metadata_editor.py dicionario.xlsx [pasta_saida] [pasta_questionarios] [caderno.pdf]"
            )

    pasta_saida = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("sav")
    pasta_questionarios = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    caminho_caderno = Path(sys.argv[4]) if len(sys.argv) > 4 else localizar_caderno_padrao()

    executar(caminho_xlsx, pasta_saida, pasta_questionarios, caminho_caderno)
    print("\nConcluído.")


if __name__ == "__main__":
    main()
