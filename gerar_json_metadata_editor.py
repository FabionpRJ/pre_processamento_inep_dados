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

As três fontes (dicionário, Caderno e questionários) alimentam também o
`censo.html` gerado ao lado dos JSONs — ver `montar_dicionario_html` e
gerar_caderno_html.gerar_censo_html.

Recorte por tabela: `tabelas_alvo` restringe quais tabelas viram JSON. O
dicionário é sempre lido por inteiro, porque é fonte do
censo.html e base do alinhamento com o Caderno — assim o cache do Caderno
não depende do recorte pedido em cada execução.

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

import csv
import json
import re
import sys
from pathlib import Path

import openpyxl

from censo_lib import (
    ABA_PARA_ARQUIVO,
    descrever_imputacao, parece_sentinela, separar_codigos_especiais,
    FID_POR_TABELA,
    ROTULO_TABELA,
    universo_publicacao,
    encontrar_questao_com_score,
    extrair_conceitos_html,
    extrair_questionario_html,
    extrair_quadros_pdf,
    fingerprint_fontes,
    formato_numerico,
    gravar_cache_versionado,
    identificar_tabela,
    largura_variavel,
    detectar_ano_censo,
    ler_cache_versionado,
    localizar_questionario,
    nome_saida_json,
    nome_saida_sav,
    prefixo_edicao,
    mapear_conceitos_para_concept,
    obter_metadados_caderno,
    rotulo_conceito,
)
from gerar_caderno_html import gerar_censo_html

# ---------------------------------------------------------------------------
# Constantes locais
# ---------------------------------------------------------------------------

CODE_RE          = re.compile(r"^\s*(-?\d+)\s*-\s*(\S.*)$")
NAO_APLICAVEL_RE = re.compile(r"^\s*-\s+(\S.*)$")
PREFIXO_RE       = re.compile(r"^([A-Z]+)_")

# Prefixos de nome de variável do Censo Escolar/INEP que indicam uma
# quantidade contínua (contagem). Os códigos de "valor extremo" (ex.: 88888)
# que o dicionário lista em rotulos_valor deixaram de contar como categoria
# por conta própria (ver `separar_codigos_especiais`), então esta lista já não
# precisa compensar isso — segue valendo para as QT_ que não têm código
# especial nenhum e ainda assim são contagens.
PREFIXOS_CONTINUOS      = {"QT"}
NOMES_CONTINUOS         = {"LATITUDE", "LONGITUDE"}
# Prefixos que indicam código/identificador administrativo (sem valor
# analítico agregado: não é categoria nem quantidade).
PREFIXOS_IDENTIFICADOR  = {"CO", "NU", "ID"}
# Exceções ao padrão de prefixo: variáveis cujo nome não segue a convenção
# mas que são identificadores (ex.: NO_ENTIDADE = "Código da Escola", apesar
# do prefixo NO_ de nome/texto).
NOMES_IDENTIFICADOR     = {"NO_ENTIDADE"}


def determinar_sum_stats_options(var: dict) -> dict:
    """Decide quais estatísticas-resumo fazem sentido calcular para a variável.

    Não há variável de peso amostral no Censo Escolar (é enumeração completa,
    não amostra) — por isso wgt/mean_wgt/stdev_wgt são sempre False.
    """
    opcoes = {
        "wgt": False, "freq": False, "missing": True, "vald": True,
        "min": False, "max": False, "mean": False, "mean_wgt": False,
        "stdev": False, "stdev_wgt": False,
    }

    tipo = var["tipo"]
    nome = var["nome_variavel"]
    # Só categorias REAIS contam. Um código de imputação ou de não-resposta
    # não torna a variável categórica: as 2 variáveis de CNPJ têm como única
    # "categoria" o 99999999999999 de "Sem declaração", e pediam uma tabela de
    # frequência de 200 mil CNPJs distintos.
    categorias_reais, _ = separar_codigos_especiais(var["rotulos_valor"])
    tem_categoria = bool(categorias_reais)
    m = PREFIXO_RE.match(nome)
    prefixo = m.group(1) if m else ""

    if tipo == "Data":
        opcoes["min"] = opcoes["max"] = True
    elif nome in NOMES_IDENTIFICADOR:
        pass
    elif nome in NOMES_CONTINUOS or prefixo in PREFIXOS_CONTINUOS:
        opcoes["min"] = opcoes["max"] = opcoes["mean"] = opcoes["stdev"] = True
    elif tem_categoria:
        opcoes["freq"] = True
    elif tipo == "Num" and prefixo not in PREFIXOS_IDENTIFICADOR:
        opcoes["min"] = opcoes["max"] = opcoes["mean"] = opcoes["stdev"] = True
    # Char sem categoria (texto livre) e identificadores (CO_/NU_/ID_) ficam
    # apenas com missing/vald.

    return opcoes

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

    # Ano do dicionário = última coluna de "Coleta por ano". É a edição que a
    # planilha descreve, e é dele que dependem o universo (`var_universe`) e o
    # critério de descontinuidade — por isso sai daqui, da própria planilha, e
    # não do ano detectado pelos nomes dos arquivos, que pode divergir.
    ano_dicionario = colunas_ano[-1][1] if colunas_ano else None

    return {"titulo": titulo, "variaveis": variaveis, "ano_dicionario": ano_dicionario}


def ler_dicionario(caminho_xlsx: Path) -> dict:
    """Lê o dicionário .xlsx e devolve {tabela: {titulo, variaveis, ano_dicionario}}.

    As abas são casadas de forma tolerante (ver censo_lib.identificar_tabela):
    ignora ano, acento, caixa e separadores, de modo que um dicionário novo com
    grafia levemente diferente continue sendo reconhecido. Abas não
    reconhecidas são ignoradas; o recorte por tabela é feito em `executar`.
    """
    wb = openpyxl.load_workbook(caminho_xlsx, data_only=True)
    abas_por_tabela: dict[str, str] = {}
    for nome_aba in wb.sheetnames:
        tabela = identificar_tabela(nome_aba.strip())
        if tabela:
            abas_por_tabela.setdefault(tabela, nome_aba)
        else:
            print(f'[aviso] aba "{nome_aba}" não reconhecida como tabela do Censo; ignorando.')

    # Preserva a ordem canônica das tabelas, não a ordem das abas do arquivo.
    return {
        nome_arquivo: ler_aba(wb[abas_por_tabela[nome_arquivo]])
        for nome_arquivo in ABA_PARA_ARQUIVO.values()
        if nome_arquivo in abas_por_tabela
    }


# ---------------------------------------------------------------------------
# Montagem do JSON no formato do Metadata Editor
# ---------------------------------------------------------------------------

def montar_var_format(var: dict) -> dict:
    """Formato declarado da variável.

    O formato numérico vem de `censo_lib.formato_numerico`, a mesma função
    usada na gravação do .sav — antes este módulo emitia sempre `F{n}.0`
    enquanto o .sav saía com o padrão F8.2 do pyreadstat, e os dois
    artefatos do mesmo pipeline se contradiziam.
    """
    tipo = var["tipo"]
    if tipo in ("Char", "Data"):
        largura = int(var["tamanho"]) if var["tamanho"] else 1
        return {
            "type": "character", "schema": "other", "readstat_type": "string",
            "data_format": f"A{largura}", "is_date": tipo == "Data",
        }
    return {
        "type": "numeric", "schema": "other", "readstat_type": "double",
        "data_format": formato_numerico(var), "is_date": False,
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


def nota_descontinuada(var: dict, ano_dicionario: str | None) -> str:
    """Flag de descontinuidade da variável no ano da edição, ou "".

    Critério decidido em reunião: a coluna do ano do dicionário na matriz
    "Coleta por ano" marcada com "n" significa variável descontinuada naquele
    ano. É deliberadamente literal — inclui as variáveis que aparecem com "n"
    em todos os anos (na edição 2025, os 9 campos de endereço da tabela Escola,
    que nunca chegaram a ser publicados).
    """
    if not ano_dicionario:
        return ""
    if (var.get("anos_coleta") or {}).get(ano_dicionario) != "n":
        return ""
    return f"Variável descontinuada no ano de {ano_dicionario}."


def montar_variavel(
    var: dict,
    indice: int,
    fid: str,
    questao_literal: str = "",
    conceito: dict | None = None,
    conceito_concept: dict | None = None,
    universo: str = "",
    ano_dicionario: str | None = None,
) -> dict:
    var_format = montar_var_format(var)
    # Largura declarada segue o dicionário para todos os tipos — antes as
    # numéricas ficavam fixas em 8, contradizendo o próprio `data_format`
    # do mesmo objeto (ex.: LATITUDE com F20 e loc_width 8).
    loc_width = largura_variavel(var)
    sid = fid.replace("F", "")

    # O rótulo de TODO código é preservado, inclusive o dos especiais: quem
    # abrir o metadado precisa saber o que 88888 significa. O que muda é que os
    # especiais são também declarados como valores inválidos logo abaixo.
    categorias = [
        {"value": str(codigo), "labl": texto}
        for codigo, texto in sorted(var["rotulos_valor"].items())
    ]

    # Valores que não são observação: código de tratamento de consistência do
    # produtor ("imputacao") ou de ausência de declaração ("nao_resposta").
    # Vão para var_invalrng para que média, desvio e frequência não os tratem
    # como quantidade — 88888 entrando numa média de "quantidade de televisões"
    # é a diferença entre 3,4 e 4.317,0.
    _, especiais = separar_codigos_especiais(var["rotulos_valor"])
    valores_invalidos = [str(codigo) for codigo in sorted(especiais)]
    # DDI: `imputation` descreve o PROCEDIMENTO, em texto livre. TODOS os
    # códigos especiais entram — a decisão registrada em reunião é tratar o
    # valor especial como resultado do processamento do INEP, não só o de valor
    # extremo. A natureza de cada um fica explícita no texto (ver
    # censo_lib.descrever_imputacao).
    texto_imputacao = descrever_imputacao(especiais)

    # Conceitos/orientações do Caderno, já estruturados e alinhados por
    # variável (ver censo_lib.obter_metadados_caderno). Preservam o dado do
    # dicionário quando o Caderno não traz definição correspondente.
    conceito = conceito or {}
    var_txt = conceito.get("var_txt") or var["descricao"]

    # Cada campo de texto tem UMA fonte, decidida em reunião:
    #
    #   var_notes          ("Notas sobre as variáveis")   <- dicionário
    #   var_qstn_ivuinstr  ("Instruções para o entrevistador") <- Caderno
    #
    # Os destaques "Importante!"/"Você sabia?" do Caderno são endereçados a
    # quem PREENCHE o Educacenso ("as secretarias devem ter atenção no
    # preenchimento..."), não a quem analisa os microdados: são instrução de
    # coleta, e por isso saíram de var_notes para var_qstn_ivuinstr, junto das
    # orientações de preenchimento que já iam nesse campo.
    partes_notes = [
        var.get("notas_importantes") or "",
        # Anos de coleta descrevem o PERÍODO, não a população — por isso não
        # ficam em var_universe.
        _anos_coletados(var),
        # Descontinuidade no ano da edição (ver `nota_descontinuada`).
        nota_descontinuada(var, ano_dicionario),
    ]
    var_notes = "\n".join(p for p in partes_notes if p).strip()

    partes_ivuinstr = [
        conceito.get("var_qstn_ivuinstr") or "",
        conceito.get("var_destaque") or "",
    ]
    var_qstn_ivuinstr = "\n".join(p for p in partes_ivuinstr if p).strip()

    # Conceito casado a partir da mesma estrutura que alimenta o censo.html
    # (ver censo_lib.mapear_conceitos_para_concept). Guarda o TÍTULO do
    # conceito, não a definição: no DDI `concept` é um rótulo curto ligado a
    # vocabulário controlado, e a definição completa já vai em var_txt —
    # antes o mesmo parágrafo (até 1807 caracteres) ia nos dois campos.
    titulo_concept = rotulo_conceito((conceito_concept or {}).get("conceito", ""))
    var_concept = [[{"concept": titulo_concept, "vocab": "", "vocabURI": ""}]] if titulo_concept else [[]]

    # Contínua vs discreta: `determinar_sum_stats_options` já distingue os
    # dois casos (QT_, lat/long, datas, presença de categorias). Antes
    # var_intrvl era "discrete" fixo, contradizendo as 707 variáveis que o
    # mesmo objeto marcava com mean/stdev.
    opcoes_sumstat = determinar_sum_stats_options(var)
    intervalo = "contin" if opcoes_sumstat["mean"] else "discrete"

    return {
        "uid":                  str(indice),
        "sid":                  sid,
        "fid":                  fid,
        "vid":                  f"V{indice}",
        "name":                 var["nome_variavel"],
        "labl":                 var["descricao"],
        "sort_order":           str(indice - 1),
        "var_intrvl":           intervalo,
        "loc_width":            loc_width,
        "var_invalrng":         {"values": valores_invalidos},
        "var_valrng":           {"range": {"UNITS": "REAL", "count": 0, "min": "", "max": ""}},
        "var_sumstat":          [],
        "var_catgry":           [],
        "var_catgry_labels":    categorias,
        "var_format":           var_format,
        "var_format_original":  var_format,
        "file_id":              fid,
        "interval_type":        intervalo,
        "sum_stats_options":    opcoes_sumstat,
        "var_concept":          var_concept,
        "var_wgt_id":           "",
        "var_universe":         universo,
        "var_txt":              var_txt,
        "var_security":         "",
        "var_notes":            var_notes,
        "var_respunit":         "",
        "var_qstn_preqtxt":     "",
        "var_qstn_qstnlit":     questao_literal,
        "var_qstn_postqtxt":    "",
        "var_forward":          "",
        "var_backward":         "",
        "var_qstn_ivuinstr":    var_qstn_ivuinstr,
        "var_codinstr":         "",
        "var_imputation":       texto_imputacao,
        "var_derivation":       "",
    }


def montar_datafile(
    nome_arquivo: str, titulo: str, total_variaveis: int, fid: str, ano=None
) -> dict:
    """Cabeçalho `datafile` do JSON de importação.

    `file_name` DECLARA o nome do arquivo de dados a que este metadado se
    refere — é por ele que o Metadata Editor amarra o JSON ao .sav. O ETL não
    gera mais o .sav, mas o campo continua sendo a referência correta: é o
    nome que o arquivo tem na convenção do INEP, e é daqui que os scripts
    standalone criar_sav_vazio/popular_sav o leem
    (censo_lib.nome_sav_do_json) em vez de recalcular. Antes este campo dizia
    "gestor.sav" enquanto o arquivo gravado era "Tabela_Gestor.sav".

    `case_count` nasce 0 e assim permanece na saída do serviço, que não lê os
    microdados; popular_sav o regrava quando usado standalone.
    """
    return {
        "file_id":    fid,
        "fid":        fid,
        "file_name":  nome_saida_sav(nome_arquivo, ano),
        "labl":       titulo,
        "var_count":  total_variaveis,
        "case_count": 0,
    }


def gerar_json_importacao(
    nome_arquivo: str,
    titulo: str,
    variaveis: list[dict],
    pasta_saida: Path,
    questao_por_variavel: dict[str, str] | None = None,
    conceitos_por_variavel: dict[str, dict] | None = None,
    concept_por_variavel: dict[str, dict] | None = None,
    ano=None,
    ano_dicionario: str | None = None,
) -> Path:
    """Monta e grava o JSON de importação de uma tabela.

    `questao_por_variavel` já vem resolvido por `executar`: o casamento
    descrição↔questão é caro (O(variáveis × questões)) e antes era refeito
    do zero aqui, depois de já ter sido calculado só para contar acertos no
    log.
    """
    fid = FID_POR_TABELA.get(nome_arquivo, "F1")
    questao_por_variavel = questao_por_variavel or {}
    conceitos_por_variavel = conceitos_por_variavel or {}
    concept_por_variavel = concept_por_variavel or {}
    # Universo ancorado no ano do DICIONÁRIO, não no ano detectado para nomear
    # a saída: é a planilha que define de que edição são as variáveis descritas.
    universo = universo_publicacao(ano_dicionario or ano)

    vars_montadas = [
        montar_variavel(
            v, i + 1, fid,
            questao_por_variavel.get(v["nome_variavel"], ""),
            conceitos_por_variavel.get(v["nome_variavel"]),
            concept_por_variavel.get(v["nome_variavel"]),
            universo,
            ano_dicionario,
        )
        for i, v in enumerate(variaveis)
    ]

    payload = {
        "datafile":  montar_datafile(nome_arquivo, titulo, len(variaveis), fid, ano),
        "variables": vars_montadas,
    }
    pasta_saida.mkdir(parents=True, exist_ok=True)
    caminho = pasta_saida / nome_saida_json(nome_arquivo, ano)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return caminho


def gravar_relatorio_casamento(
    linhas: list[dict], pasta_saida: Path, ano=None
) -> Path | None:
    """Grava o CSV de auditoria dos casamentos heurísticos.

    Boa parte dos metadados semânticos (var_concept, var_qstn_qstnlit,
    var_txt) vem de casamento por similaridade, e o log só mostrava
    contagens agregadas. Este arquivo permite a um especialista conferir
    variável a variável o que foi atribuído e com que pontuação — a revisão
    que este tipo de produto exige antes de publicar.

    `valores_especiais` lista os códigos que saíram de categoria e viraram
    valor inválido (`88888=imputacao`), para que essa reclassificação seja
    conferível na mesma planilha — ela muda como as estatísticas do Metadata
    Editor leem a variável.
    """
    if not linhas:
        return None
    colunas = ["tabela", "variavel", "descricao", "conceito", "tem_var_txt",
               "questao", "score_questao", "valores_especiais"]
    caminho = pasta_saida / f"{prefixo_edicao(ano)}relatorio_casamento.csv"
    try:
        # utf-8-sig: o Excel em pt-BR abre o CSV com acentuação correta.
        with open(caminho, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=colunas, delimiter=";")
            writer.writeheader()
            for linha in linhas:
                writer.writerow({c: linha.get(c, "") for c in colunas})
    except OSError as exc:
        print(f"  [aviso] Não foi possível gravar o relatório de casamento: {exc}")
        return None
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

def montar_dicionario_html(tabelas: dict[str, dict]) -> list[dict]:
    """Estrutura o dicionário de variáveis para o bloco `app-data` do censo.html.

    Mesma fonte que alimenta os JSONs do Metadata Editor (a leitura do .xlsx em
    `ler_dicionario`) — o HTML não reparseia a planilha. Só entram as tabelas já
    filtradas, então o censo.html reflete exatamente o que foi enviado.
    """
    return [
        {
            "id":     nome_arquivo,
            "titulo": ROTULO_TABELA.get(nome_arquivo, nome_arquivo),
            "fonte":  info["titulo"],
            "variaveis": [
                {
                    "ordem":      v["ordem"],
                    "nome":       v["nome_variavel"],
                    "descricao":  v["descricao"],
                    "tipo":       v["tipo"],
                    "tamanho":    v["tamanho"],
                    "universo":   _anos_coletados(v),
                    "notas":      "\n".join(
                        t for t in (
                            v.get("notas_importantes") or "",
                            nota_descontinuada(v, info.get("ano_dicionario")),
                        ) if t
                    ),
                    "categorias": [
                        {"valor": str(codigo), "rotulo": texto}
                        for codigo, texto in sorted(v["rotulos_valor"].items())
                    ],
                    "aplicabilidade": v.get("notas_aplicabilidade_categoria") or [],
                }
                for v in info["variaveis"]
            ],
        }
        for nome_arquivo, info in tabelas.items()
    ]


def executar(
    caminho_xlsx: Path,
    pasta_saida: Path,
    pasta_questionarios: Path | None = None,
    caminho_caderno: Path | None = None,
    gerar_html: bool = True,
    incluir_questionarios: bool = True,
    tabelas_alvo: list[str] | None = None,
    ano: str | int | None = None,
) -> None:
    if not caminho_xlsx.exists():
        sys.exit(f'Arquivo não encontrado: "{caminho_xlsx}"')
    print(f'Lendo dicionário: "{caminho_xlsx}"')

    # A saída é nomeada pela convenção do INEP (ceb2025_microdados_tabela_*).
    # Sem `ano` informado pelo chamador, tenta deduzi-lo dos nomes dos insumos
    # — no pipeline completo quem detecta é o app, que tem acesso aos CSVs e
    # portanto à coluna NU_ANO_CENSO. Ver censo_lib §5 e `detectar_ano_censo`.
    if ano is None:
        ano = detectar_ano_censo(
            nomes_extra=[caminho_xlsx, caminho_caderno, pasta_questionarios]
        )
    if ano:
        print(f"  Edição detectada: {ano} — saída como {prefixo_edicao(ano)}microdados_tabela_*")
    else:
        print("  [aviso] Ano da edição não determinado; a saída sai sem ano "
              f"({prefixo_edicao(None)}microdados_tabela_*).")

    # O dicionário é sempre lido por inteiro: ele é uma das fontes do
    # censo.html e a base do alinhamento com o Caderno (cache estável,
    # independente do recorte). `tabelas_alvo` restringe apenas quais tabelas
    # viram JSON/.sav — ver o laço final.
    tabelas_todas = ler_dicionario(caminho_xlsx)
    if not tabelas_todas:
        sys.exit("Nenhuma aba reconhecida no dicionário.")
    alvo = list(tabelas_alvo) if tabelas_alvo else list(tabelas_todas)
    tabelas = {nome: info for nome, info in tabelas_todas.items() if nome in alvo}
    faltantes = [t for t in alvo if t not in tabelas_todas]
    if faltantes:
        print(f"  [aviso] Sem aba no dicionário para: {', '.join(faltantes)}")
    if not tabelas:
        sys.exit("Nenhuma aba do dicionário correspondeu às tabelas solicitadas.")
    print(f"  Abas lidas: {', '.join(tabelas_todas)}")
    print(f"  JSONs a gerar: {', '.join(tabelas)}")
    pasta_saida.mkdir(parents=True, exist_ok=True)

    usar_pdfs = pasta_questionarios is not None and pasta_questionarios.is_dir()
    if usar_pdfs:
        print(f'Questionários: "{pasta_questionarios.resolve()}"')
    else:
        print("[aviso] Pasta de questionários não informada; var_qstn_qstnlit ficará vazio.")

    # Resolve uma vez o PDF de cada tabela (nome ano-agnóstico) e reaproveita
    # tanto no casamento de var_qstn_qstnlit quanto na aba do censo.html.
    # Resolve para todas as tabelas do dicionário: os questionários enviados
    # entram inteiros no censo.html, mesmo os de tabelas fora do recorte.
    # Um mesmo PDF serve mais de uma tabela (Turma alimenta turma e
    # curso_tecnico) e é lido tanto para o censo.html quanto para o
    # casamento — memoriza para não reparsear o arquivo a cada uso.
    cache_perguntas: dict[Path, list[dict]] = {}

    def perguntas_do_pdf(pdf_path: Path) -> list[dict]:
        if pdf_path not in cache_perguntas:
            cache_perguntas[pdf_path] = extrair_questionario_html(pdf_path)
        return cache_perguntas[pdf_path]

    pdf_por_tabela: dict[str, Path] = {}
    if usar_pdfs:
        for nome_arquivo in tabelas_todas:
            pdf = localizar_questionario(pasta_questionarios, nome_arquivo)
            if pdf:
                pdf_por_tabela[nome_arquivo] = pdf
            elif nome_arquivo in tabelas:
                print(f"  [aviso] Questionário PDF não encontrado para {nome_arquivo}.")

    # Estrutura os conceitos/orientações do Caderno alinhados por variável,
    # antes de montar qualquer JSON. Se já existir um cache estruturado em
    # `pasta_saida`, o scraping do PDF é ignorado.
    caminho_cache_caderno = pasta_saida / "caderno_conceitos_metadados.json"
    tabelas_variaveis = {nome: info["variaveis"] for nome, info in tabelas_todas.items()}
    print("Metadados do Caderno de Conceitos:")
    metadados_caderno = obter_metadados_caderno(
        caminho_caderno, caminho_cache_caderno, tabelas_variaveis
    )
    if not metadados_caderno:
        print("  [aviso] Nenhum metadado do Caderno disponível; var_txt/var_qstn_ivuinstr do Caderno ficarão vazios.")

    # ---- Conceitos estruturados do Caderno (mesma fonte do censo.html) -----
    # Extração rica por CONCEITO (ver extrair_conceitos_html), independente
    # da flag `gerar_html`: além de alimentar o censo.html, é a fonte usada
    # abaixo para casar conceito↔variável e popular var_concept (ver
    # INSTRUCOES_ALTERACAO_ETL.md). Falha graciosa: sem Caderno, segue com
    # listas vazias.
    conceitos_html: list[dict] = []
    quadros_html: list[dict] = []
    if caminho_caderno and caminho_caderno.is_file():
        caminho_cache_censo = pasta_saida / "censo_html_dados.json"
        # Este cache depende só do PDF (a extração por conceito não olha o
        # dicionário), mas passa pelo mesmo controle de versão.
        fp_censo = fingerprint_fontes(caminho_caderno)
        try:
            dados_censo = ler_cache_versionado(caminho_cache_censo, fp_censo)
            if dados_censo is not None:
                print(f"  Dados de conceitos já estruturados: {caminho_cache_censo.name} (scraping do PDF ignorado)")
                conceitos_html = dados_censo["conceitos"]
                quadros_html = dados_censo["quadros"]
            else:
                conceitos_html = extrair_conceitos_html(caminho_caderno)
                quadros_html = extrair_quadros_pdf(caminho_caderno)
                gravar_cache_versionado(
                    caminho_cache_censo, fp_censo,
                    {"conceitos": conceitos_html, "quadros": quadros_html},
                )
        except Exception as exc:
            print(f"  [aviso] Não foi possível extrair conceitos/quadros do Caderno: {exc}")

    # ---- Questionários (PDF) — estrutura para o censo.html -------------------
    # Reaproveita a extração já usada para casar var_qstn_qstnlit (ver
    # extrair_questionario_html/extrair_questoes_pdf) — não reparseia o PDF.
    # Um mesmo arquivo usado por mais de uma tabela (ex. "Turma 2025.pdf",
    # usado por turma e curso_tecnico) aparece uma única vez no censo.html.
    questionarios_html: list[dict] = []
    if not incluir_questionarios:
        print("  [info] Questionários (PDF) não serão incluídos no censo.html.")
    elif pdf_por_tabela:
        pdfs_vistos: set[str] = set()
        for nome_arquivo, pdf_path in pdf_por_tabela.items():
            if pdf_path.name in pdfs_vistos:
                continue
            pdfs_vistos.add(pdf_path.name)
            perguntas = perguntas_do_pdf(pdf_path)
            if perguntas:
                titulo_pdf = re.sub(r"\s*\d{4}$", "", pdf_path.stem).strip() or pdf_path.stem
                questionarios_html.append({"id": nome_arquivo, "titulo": titulo_pdf, "perguntas": perguntas})
        if questionarios_html:
            n_perguntas = sum(len(q["perguntas"]) for q in questionarios_html)
            print(f"  Questionários estruturados: {n_perguntas} pergunta(s) em {len(questionarios_html)} questionário(s).")

    # ---- censo.html — Caderno de Conceitos navegável ------------------------
    # Artefato independente (sem backend). Falha graciosa: sem conceitos
    # extraídos, avisa e segue o pipeline sem gerar o HTML.
    # As três fontes de metadados (dicionário, Caderno e questionários) vão
    # juntas para o censo.html — é o mesmo material que alimenta os JSONs.
    dicionario_html = montar_dicionario_html(tabelas_todas)
    if not gerar_html:
        print("  [info] Geração de censo.html desativada pelo usuário.")
    elif conceitos_html or quadros_html or questionarios_html or dicionario_html:
        print("Gerando censo.html (dicionário + Caderno de Conceitos + questionários)...")
        try:
            caminho_censo_html = gerar_censo_html(
                conceitos_html, quadros_html,
                pasta_saida / f"{prefixo_edicao(ano)}censo.html",
                questionarios_html, dicionario=dicionario_html,
            )
            n_vars_html = sum(len(t["variaveis"]) for t in dicionario_html)
            print(
                f"  OK: {caminho_censo_html.name} ({len(conceitos_html)} conceitos, {len(quadros_html)} quadros, "
                f"{len(questionarios_html)} questionário(s), "
                f"{n_vars_html} variáveis em {len(dicionario_html)} tabela(s)) -> {caminho_censo_html}"
            )
        except Exception as exc:
            print(f"  [aviso] Não foi possível gerar censo.html: {exc}")
    else:
        print("  [aviso] Nenhuma fonte disponível; censo.html não será gerado.")

    # ---- var_concept — casamento conceito↔variável --------------------------
    mapa_concept = mapear_conceitos_para_concept(conceitos_html, tabelas_variaveis)
    if conceitos_html:
        n_concept = sum(len(v) for v in mapa_concept.values())
        print(f"  Conceitos casados a {n_concept} variável(is) em {len(mapa_concept)} tabela(s) (var_concept).")

    linhas_relatorio: list[dict] = []
    for nome_arquivo, info in tabelas.items():
        pdf_path = pdf_por_tabela.get(nome_arquivo)
        questoes = [p["texto"] for p in perguntas_do_pdf(pdf_path)] if pdf_path else []
        n_questoes = len(questoes)
        n_vars = len(info["variaveis"])

        # Casamento resolvido UMA vez e reaproveitado no log, no JSON e no
        # relatório de auditoria.
        casamento = {
            v["nome_variavel"]: encontrar_questao_com_score(v["descricao"], questoes)
            for v in info["variaveis"]
        }
        questao_por_variavel = {nome: texto for nome, (texto, _) in casamento.items()}
        n_com_match = sum(1 for texto, _ in casamento.values() if texto)

        conceitos_tabela = metadados_caderno.get(nome_arquivo, {})
        concept_tabela = mapa_concept.get(nome_arquivo, {})
        caminho = gerar_json_importacao(
            nome_arquivo, info["titulo"], info["variaveis"], pasta_saida,
            questao_por_variavel, conceitos_tabela, concept_tabela, ano,
            info.get("ano_dicionario"),
        )

        for v in info["variaveis"]:
            nome_var = v["nome_variavel"]
            texto_q, score_q = casamento[nome_var]
            conceito_casado = concept_tabela.get(nome_var) or {}
            _, especiais_var = separar_codigos_especiais(v["rotulos_valor"])
            linhas_relatorio.append({
                "tabela":          nome_arquivo,
                "variavel":        nome_var,
                "descricao":       v["descricao"],
                "conceito":        rotulo_conceito(conceito_casado.get("conceito", "")),
                "tem_var_txt":     "sim" if conceitos_tabela.get(nome_var, {}).get("var_txt") else "",
                "questao":         texto_q,
                "score_questao":   f"{score_q:.3f}" if texto_q else "",
                "valores_especiais": " ".join(
                    f"{cod}={tipo}" for cod, (tipo, _) in sorted(especiais_var.items())
                ),
            })

        # Valores especiais: quantos códigos deixaram de ser categoria e
        # viraram valor inválido, e — o que mais importa — quais tinham cara
        # de sentinela e NÃO foram reconhecidos pelo rótulo. Este segundo caso
        # é o sinal de que o INEP mudou a redação e a regra precisa de
        # ajuste; sem o aviso, o código passaria como categoria real.
        n_imput = n_naoresp = 0
        nao_reconhecidos: list[str] = []
        for v in info["variaveis"]:
            reais_v, especiais_v = separar_codigos_especiais(v["rotulos_valor"])
            for _, (tipo_v, _rot) in especiais_v.items():
                if tipo_v == "imputacao":
                    n_imput += 1
                else:
                    n_naoresp += 1
            for cod_v, rot_v in reais_v.items():
                if parece_sentinela(cod_v):
                    nao_reconhecidos.append(f"{v['nome_variavel']}:{cod_v}=“{rot_v[:60]}”")

        match_info = f", {n_com_match}/{n_vars} vars com questão" if n_questoes else ""
        conceito_info = f", {len(conceitos_tabela)}/{n_vars} vars com conceito" if conceitos_tabela else ""
        concept_info = f", {len(concept_tabela)}/{n_vars} vars com var_concept" if concept_tabela else ""
        print(f"  OK: {caminho.name}  ({n_vars} vars, {n_questoes} questões PDF{match_info}{conceito_info}{concept_info})")

        # Uma tabela que sai sem nenhum metadado semântico é sempre sintoma
        # de problema (questionário não numerado, seção do Caderno que não
        # corresponde à tabela) — antes isso passava como um "0" discreto.
        rotulo = ROTULO_TABELA.get(nome_arquivo, nome_arquivo)
        if n_questoes == 0:
            print(f"    [AVISO] {rotulo}: nenhuma questão disponível — "
                  f"var_qstn_qstnlit ficará vazio nas {n_vars} variáveis.")
        elif n_com_match == 0:
            print(f"    [AVISO] {rotulo}: {n_questoes} questões extraídas, mas "
                  f"nenhuma casou com as variáveis — var_qstn_qstnlit vazio.")
        if not concept_tabela:
            print(f"    [AVISO] {rotulo}: nenhum conceito do Caderno casou — "
                  f"var_concept ficará vazio nas {n_vars} variáveis.")
        if n_imput or n_naoresp:
            print(f"    Valores especiais: {n_imput + n_naoresp} código(s) em "
                  f"var_invalrng + var_imputation "
                  f"({n_imput} de tratamento de consistência, "
                  f"{n_naoresp} de não-resposta).")
        if nao_reconhecidos:
            print(f"    [AVISO] {rotulo}: {len(nao_reconhecidos)} código(s) com "
                  f"forma de sentinela seguem valendo como CATEGORIA REAL porque "
                  f"o rótulo não casou com nenhum marcador conhecido — confira e, "
                  f"se for o caso, estenda censo_lib._MARCADORES_*: "
                  + "; ".join(nao_reconhecidos[:5])
                  + (f" (+{len(nao_reconhecidos) - 5})" if len(nao_reconhecidos) > 5 else ""))

    caminho_relatorio = gravar_relatorio_casamento(linhas_relatorio, pasta_saida, ano)
    if caminho_relatorio:
        print(f"  Relatório de casamento: {caminho_relatorio.name} "
              f"({len(linhas_relatorio)} linhas) — revise antes de publicar.")

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
