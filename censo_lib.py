#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
censo_lib.py — Módulo compartilhado do pipeline do Censo Escolar 2025.

Expõe constantes, utilitários de leitura de CSV/JSON, extração de questões
de PDFs, extração/alinhamento de conceitos do Caderno de Conceitos e
construção de metadados SAV usados por gerar_json_metadata_editor,
criar_sav_vazio e popular_sav.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import pandas as pd
import pyreadstat

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

ABA_PARA_ARQUIVO: dict[str, str] = {
    "Tabela_de_Escola":     "escola",
    "Tabela_de_Matrícula":  "matricula",
    "Tabela_de_Docente":    "docente",
    "Tabela_de_Turma":      "turma",
    "Tabela_de_Gestor":     "gestor",
    "Tabela_Curso_Técnico": "curso_tecnico",
}

FID_POR_TABELA: dict[str, str] = {
    "escola":        "F1",
    "matricula":     "F2",
    "docente":       "F3",
    "turma":         "F4",
    "gestor":        "F5",
    "curso_tecnico": "F6",
}

TABELAS: dict[str, str] = {
    "escola":        "Tabela_Escola_2025.csv",
    "matricula":     "Tabela_Matricula_2025.csv",
    "docente":       "Tabela_Docente_2025.csv",
    "turma":         "Tabela_Turma_2025.csv",
    "gestor":        "Tabela_Gestor_Escolar_2025.csv",
    "curso_tecnico": "Tabela_Curso_Tecnico_2025.csv",
}

NOME_TABELA: dict[str, str] = {
    "escola":        "Tabela_Escola",
    "matricula":     "Tabela_Matricula",
    "docente":       "Tabela_Docente",
    "turma":         "Tabela_Turma",
    "gestor":        "Tabela_Gestor",
    "curso_tecnico": "Tabela_Curso_Tecnico",
}

# Questionário (PDF) correspondente a cada tabela
QUESTIONARIO_POR_TABELA: dict[str, str] = {
    "escola":        "Escola 2025.pdf",
    "matricula":     "Aluno 2025.pdf",
    "docente":       "Profissional Escolar 2025.pdf",
    "turma":         "Turma 2025.pdf",
    "gestor":        "Gestor Escolar 2025.pdf",
    "curso_tecnico": "Turma 2025.pdf",
}

LIMITE_ROTULO_VARIAVEL = 256
LIMITE_ROTULO_VALOR    = 120

# ---------------------------------------------------------------------------
# Utilitários de CSV
# ---------------------------------------------------------------------------

def detectar_encoding(caminho: Path) -> str:
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            with open(caminho, "r", encoding=enc) as fh:
                fh.read(65536)
            return enc
        except UnicodeDecodeError:
            continue
    return "latin-1"


def detectar_delimitador(caminho: Path, encoding: str) -> str:
    with open(caminho, "r", encoding=encoding, errors="replace") as fh:
        cabecalho = fh.readline()
    return ";" if cabecalho.count(";") >= cabecalho.count(",") else ","


def ler_csv(caminho: Path) -> pd.DataFrame:
    encoding = detectar_encoding(caminho)
    sep = detectar_delimitador(caminho, encoding)
    return pd.read_csv(
        caminho,
        sep=sep,
        encoding=encoding,
        low_memory=False,
        dtype=str,
    )


# ---------------------------------------------------------------------------
# Extração de questões dos PDFs dos questionários
# ---------------------------------------------------------------------------

_QUESTAO_RE = re.compile(r"^\s*\d+[a-z]?\s*[-–]\s+(.+)", re.IGNORECASE)
# Detecta linhas com múltiplas questões mescladas (ex: "CEP 10 – UF 11 – Município")
_MULTI_QUESTAO_RE = re.compile(r"\s\d{1,2}[a-z]?\s*[-–]", re.IGNORECASE)

_STOPWORDS = {
    "a", "o", "e", "ou", "em", "de", "da", "do", "das", "dos",
    "no", "na", "nos", "nas", "ao", "aos", "um", "uma", "uns", "umas",
    "para", "com", "por", "pelo", "pela", "pelos", "pelas", "que",
    "se", "este", "esta", "esse", "essa", "seu", "sua", "seus", "suas",
    "mais", "mas", "nao", "como", "ate", "apos", "sobre", "entre",
    "cujo", "cuja", "cujos", "cujas", "the", "of", "and",
}

# Prefixos de campo muito genéricos que sozinhos não definem a variável
_PALAVRAS_GENERICAS = {"nome", "codigo", "numero", "sigla", "data", "indicador"}


def _texto_garbled(texto: str) -> bool:
    """Detecta texto com caracteres duplicados resultante de PDF mal renderizado."""
    alfa = [c for c in texto if c.isalpha()]
    if len(alfa) < 6:
        return False
    pares = sum(1 for i in range(len(alfa) - 1) if alfa[i] == alfa[i + 1])
    return pares / len(alfa) > 0.25


def _palavras_significativas(texto: str) -> set[str]:
    """Normaliza texto e retorna conjunto de palavras sem stopwords."""
    t = unicodedata.normalize("NFD", texto)
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = t.lower()
    t = re.sub(r"[^\w\s]", " ", t)
    return {w for w in t.split() if len(w) > 2 and w not in _STOPWORDS}


def _score_match(descricao: str, questao: str) -> float:
    """
    Score F1 entre palavras específicas da descrição e palavras da questão.

    Regras de qualidade mínima:
    - descrições com 1-2 palavras específicas: todas devem coincidir na questão
    - descrições com 3+ palavras específicas: ao menos 2 devem coincidir
    - a questão não pode ter mais de 8× mais palavras que a descrição (baixa precisão)
    """
    if _texto_garbled(questao):
        return 0.0

    d_words = _palavras_significativas(descricao)
    q_words = _palavras_significativas(questao)
    if not d_words or not q_words:
        return 0.0

    d_especificas = d_words - _PALAVRAS_GENERICAS or d_words

    inter = d_especificas & q_words
    n_match = len(inter)
    n_desc = len(d_especificas)
    n_ques = len(q_words)

    if n_desc <= 2 and n_match < n_desc:
        return 0.0
    if n_desc >= 3 and n_match < 2:
        return 0.0
    if n_ques > n_desc * 8:
        return 0.0

    recall    = n_match / n_desc
    precision = n_match / n_ques
    if recall + precision == 0:
        return 0.0
    return 2 * recall * precision / (recall + precision)


def extrair_questoes_pdf(pdf_path: Path) -> list[str]:
    """Extrai textos de questões numeradas de um PDF de questionário."""
    try:
        import pdfplumber
    except ImportError:
        print("[aviso] pdfplumber não instalado; instale com: pip install pdfplumber")
        return []

    questoes: list[str] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                texto = page.extract_text() or ""
                for linha in texto.split("\n"):
                    m = _QUESTAO_RE.match(linha)
                    if m:
                        texto_questao = m.group(1).strip()
                        if _texto_garbled(texto_questao):
                            continue
                        if _MULTI_QUESTAO_RE.search(texto_questao):
                            continue
                        questoes.append(texto_questao)
    except Exception as exc:
        print(f"[aviso] Erro ao ler {pdf_path.name}: {exc}")

    return questoes


def encontrar_questao(descricao: str, questoes: list[str], limiar: float = 0.50) -> str:
    """
    Retorna o texto da questão mais similar à descrição da variável.
    Retorna '' se nenhuma questão superar o limiar de qualidade.
    """
    if not questoes or not descricao:
        return ""
    melhor_score = 0.0
    melhor_texto = ""
    for q in questoes:
        score = _score_match(descricao, q)
        if score > melhor_score:
            melhor_score = score
            melhor_texto = q
    return melhor_texto if melhor_score >= limiar else ""


# ---------------------------------------------------------------------------
# Extração de conceitos do Caderno de Conceitos e Orientações (PDF)
# ---------------------------------------------------------------------------

# Seções do Caderno que alimentam cada tabela do dicionário
TABELA_PARA_SECAO: dict[str, list[str]] = {
    "escola":        ["escola"],
    "matricula":     ["pessoa_fisica"],
    "docente":       ["pessoa_fisica"],
    "gestor":        ["pessoa_fisica"],
    "turma":         ["turma"],
    "curso_tecnico": ["turma"],
}

_STOPWORDS_CONCEITO = {
    "a", "ao", "aos", "as", "com", "da", "das", "de", "do", "dos",
    "e", "em", "entre", "esta", "este", "eu", "na", "nas", "no", "nos",
    "o", "os", "ou", "para", "pela", "pelas", "pelo", "pelos", "por",
    "qual", "que", "se", "sua", "suas", "seu", "seus", "um", "uma",
    "uns", "umas", "nao", "so", "ja", "mais", "mas", "nem",
}

# Linhas de boilerplate do PDF (exceto CONCEITOS/ORIENTAÇÕES, que têm papel funcional)
_LINHA_BOILERPLATE_CADERNO = re.compile(
    r"^(\d{1,3}|"
    r"CADERNO DE CONCEITOS.*|"
    r"1ª ETAPA DA COLETA|"
    r"MENU)$"
)


def _normalizar_conceito(texto: str) -> str:
    """Remove acentos, converte para minúsculas, remove pontuação."""
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = texto.lower()
    texto = re.sub(r"[^\w\s]", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _eh_all_caps(linha: str) -> bool:
    """True se a linha for toda em maiúsculas (letras) e tiver mais de 4 chars."""
    s = linha.strip()
    if len(s) < 5:
        return False
    letras = [c for c in s if c.isalpha()]
    return bool(letras) and all(c == c.upper() for c in letras)


def _secoes_vazias() -> dict[str, dict[str, list]]:
    return {
        "escola":        {"conceitos": [], "orientacoes": []},
        "turma":         {"conceitos": [], "orientacoes": []},
        "pessoa_fisica": {"conceitos": [], "orientacoes": []},
    }


def extrair_conceitos_pdf(caminho_pdf: Path) -> dict[str, dict[str, list]]:
    """
    Extrai do Caderno de Conceitos e Orientações os blocos de definições
    (CONCEITOS) e instruções de preenchimento (ORIENTAÇÕES), agrupados por
    seção do questionário:
      {
        'escola':        {'conceitos': [(titulo, definicao, nota)], 'orientacoes': [(titulo, texto)]},
        'turma':         {...},
        'pessoa_fisica': {...},
      }
    """
    try:
        import pdfplumber
    except ImportError:
        print("[aviso] pdfplumber não instalado; instale com: pip install pdfplumber")
        return _secoes_vazias()

    resultado = _secoes_vazias()

    all_lines: list[str] = []
    with pdfplumber.open(caminho_pdf) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for raw in text.split("\n"):
                s = raw.strip()
                if s:
                    all_lines.append(s)

    secao_atual: str | None = None
    modo_atual: str | None = None   # 'conceito' ou 'orientacao'
    titulo_atual: str | None = None
    texto_linhas: list[str] = []
    nota_linhas: list[str] = []
    em_nota = False

    def flush() -> None:
        if not (titulo_atual and secao_atual and modo_atual):
            return
        texto = " ".join(texto_linhas).strip()
        nota  = " ".join(nota_linhas).strip()
        if not texto:
            return
        if modo_atual == "conceito":
            resultado[secao_atual]["conceitos"].append((titulo_atual, texto, nota))
        else:
            resultado[secao_atual]["orientacoes"].append((titulo_atual, texto))

    i = 0
    while i < len(all_lines):
        linha = all_lines[i]

        if _LINHA_BOILERPLATE_CADERNO.match(linha):
            i += 1
            continue

        if "QUESTIONÁRIO DE ESCOLA" in linha and "PESSOA" not in linha:
            flush()
            secao_atual = "escola"
            modo_atual = titulo_atual = None
            texto_linhas, nota_linhas = [], []
            i += 1
            continue

        if "QUESTIONÁRIO DE TURMA" in linha:
            flush()
            secao_atual = "turma"
            modo_atual = titulo_atual = None
            texto_linhas, nota_linhas = [], []
            i += 1
            continue

        if "QUESTIONÁRIOS DE PESSOA" in linha or "QUESTIONÁRIO DE PESSOA" in linha:
            flush()
            secao_atual = "pessoa_fisica"
            modo_atual = titulo_atual = None
            texto_linhas, nota_linhas = [], []
            i += 1
            continue

        if linha == "CONCEITOS":
            flush()
            titulo_atual = None
            texto_linhas, nota_linhas = [], []
            em_nota = False
            modo_atual = "conceito"
            i += 1
            continue

        if linha == "ORIENTAÇÕES":
            flush()
            titulo_atual = None
            texto_linhas, nota_linhas = [], []
            em_nota = False
            modo_atual = "orientacao"
            i += 1
            continue

        if secao_atual is None or modo_atual is None:
            i += 1
            continue

        if _eh_all_caps(linha):
            partes: list[str] = [linha]
            j = i + 1
            while (
                j < len(all_lines)
                and _eh_all_caps(all_lines[j])
                and not _LINHA_BOILERPLATE_CADERNO.match(all_lines[j])
                and "QUESTIONÁRIO" not in all_lines[j]
                and all_lines[j] not in ("CONCEITOS", "ORIENTAÇÕES")
            ):
                candidato = all_lines[j]
                if candidato not in partes:   # deduplicar linhas repetidas de layout
                    partes.append(candidato)
                else:
                    break
                j += 1

            flush()
            titulo_atual = " ".join(partes)
            texto_linhas, nota_linhas = [], []
            em_nota = False
            i = j
            continue

        if titulo_atual:
            if linha.startswith("Importante!") or linha.startswith("Você sabia?"):
                em_nota = True
                nota_linhas.append(linha)
            elif em_nota:
                nota_linhas.append(linha)
            else:
                texto_linhas.append(linha)

        i += 1

    flush()  # último bloco
    return resultado


def _tokens_significativos_conceito(texto: str) -> set[str]:
    """Tokens normalizados sem stopwords."""
    return {
        t for t in _normalizar_conceito(texto).split()
        if t not in _STOPWORDS_CONCEITO and len(t) > 2
    }


def _score_match_conceito(label: str, titulo_pdf: str) -> float:
    """
    Pontuação de similaridade entre o rótulo de uma variável e um título de
    conceito do Caderno. Retorna valor em [0, 1].
    """
    base_label = label.split(" - ")[0] if " - " in label else label

    toks_label = _tokens_significativos_conceito(label)
    toks_base  = _tokens_significativos_conceito(base_label)
    toks_pdf   = _tokens_significativos_conceito(titulo_pdf)

    if not toks_pdf or (not toks_label and not toks_base):
        return 0.0

    melhor_toks = toks_label if len(toks_label) > len(toks_base) else toks_base
    intersecao  = melhor_toks & toks_pdf
    cob_label   = len(intersecao) / len(melhor_toks) if melhor_toks else 0
    cob_pdf     = len(intersecao) / len(toks_pdf)    if toks_pdf   else 0

    if cob_label + cob_pdf == 0:
        return 0.0
    f1 = 2 * cob_label * cob_pdf / (cob_label + cob_pdf)

    prefix_pdf = _normalizar_conceito(titulo_pdf)[:30]
    prefix_lbl = _normalizar_conceito(base_label)[:30]
    if prefix_pdf and prefix_lbl and prefix_pdf == prefix_lbl:
        f1 = max(f1, 0.85)

    return f1


def _melhor_match_conceito(
    label: str,
    blocos: list[tuple],
    limiar: float = 0.55,
) -> tuple | None:
    """Retorna o bloco com maior pontuação acima do limiar, ou None."""
    melhor_score = limiar
    melhor = None
    for bloco in blocos:
        score = _score_match_conceito(label, bloco[0])
        if score > melhor_score:
            melhor_score = score
            melhor = bloco
    return melhor


def mapear_conceitos_por_variavel(
    secoes: dict[str, dict[str, list]],
    tabelas_variaveis: dict[str, list[dict]],
) -> dict[str, dict[str, dict]]:
    """
    Alinha os blocos de conceitos/orientações extraídos do Caderno com as
    variáveis do dicionário .xlsx, tabela a tabela — antes de qualquer JSON
    de metadados ser montado.

    Parâmetros
    ----------
    secoes            : retorno de `extrair_conceitos_pdf`
    tabelas_variaveis : {tabela: [variaveis do dicionário]}, cada variável
                        com as chaves "nome_variavel" e "descricao"

    Retorna
    -------
    {tabela: {nome_variavel: {var_txt?, var_notes?, var_qstn_ivuinstr?}}}
    """
    resultado: dict[str, dict[str, dict]] = {}
    for tabela, variaveis in tabelas_variaveis.items():
        secoes_tabela = TABELA_PARA_SECAO.get(tabela, [])
        blocos_conceito: list[tuple] = []
        blocos_orientacao: list[tuple] = []
        for s in secoes_tabela:
            blocos_conceito.extend(secoes.get(s, {}).get("conceitos", []))
            blocos_orientacao.extend(secoes.get(s, {}).get("orientacoes", []))
        if not blocos_conceito and not blocos_orientacao:
            continue

        mapa_tabela: dict[str, dict] = {}
        for var in variaveis:
            label = var.get("descricao", "")
            nome  = var.get("nome_variavel", "")
            if not label or not nome:
                continue

            entrada: dict[str, str] = {}

            match_c = _melhor_match_conceito(label, blocos_conceito)
            if match_c:
                _, definicao, nota_imp = match_c
                if definicao:
                    entrada["var_txt"] = definicao
                if nota_imp:
                    entrada["var_notes"] = nota_imp

            match_o = _melhor_match_conceito(label, [(t, txt, "") for t, txt in blocos_orientacao])
            if match_o:
                _, instrucao, _ = match_o
                if instrucao:
                    entrada["var_qstn_ivuinstr"] = instrucao

            if entrada:
                mapa_tabela[nome] = entrada

        if mapa_tabela:
            resultado[tabela] = mapa_tabela

    return resultado


def obter_metadados_caderno(
    caminho_caderno: Path | None,
    caminho_cache: Path,
    tabelas_variaveis: dict[str, list[dict]],
) -> dict[str, dict[str, dict]]:
    """
    Retorna os metadados do Caderno de Conceitos já estruturados e alinhados
    por variável/tabela (ver `mapear_conceitos_por_variavel`).

    Se `caminho_cache` já existir, reaproveita o JSON estruturado e não faz
    scraping do PDF novamente. Caso contrário, extrai do PDF, monta o
    mapeamento e grava `caminho_cache` para reuso futuro.
    """
    if caminho_cache.exists():
        print(f"  Metadados do Caderno já estruturados: {caminho_cache.name} (scraping do PDF ignorado)")
        with open(caminho_cache, encoding="utf-8") as fh:
            return json.load(fh)

    if not caminho_caderno or not caminho_caderno.is_file():
        return {}

    print(f"  Extraindo conceitos do Caderno: {caminho_caderno.name} ...")
    try:
        secoes = extrair_conceitos_pdf(caminho_caderno)
    except Exception as exc:
        print(f"  [ERRO] Não foi possível ler o Caderno: {exc}")
        return {}

    mapa = mapear_conceitos_por_variavel(secoes, tabelas_variaveis)
    n_vars = sum(len(v) for v in mapa.values())
    print(f"  Conceitos alinhados a {n_vars} variável(is) em {len(mapa)} tabela(s).")

    caminho_cache.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho_cache, "w", encoding="utf-8") as fh:
        json.dump(mapa, fh, ensure_ascii=False, indent=2)
    print(f"  Metadados do Caderno estruturados salvos em: {caminho_cache.name}")

    return mapa


# ---------------------------------------------------------------------------
# Leitura e normalização de metadados JSON
# ---------------------------------------------------------------------------

def _tipo_do_var_format(var_format: dict) -> str:
    if var_format.get("type") == "character":
        return "Data" if var_format.get("is_date") else "Char"
    return "Num"


def _normalizar_novo_formato(variables: list[dict]) -> list[dict]:
    result = []
    for i, v in enumerate(variables):
        tipo = _tipo_do_var_format(v.get("var_format") or {})
        rotulos: dict = {}
        for cat in v.get("var_catgry_labels") or []:
            val_str = str(cat.get("value", ""))
            texto   = cat.get("labl", "")
            if tipo == "Num":
                try:
                    rotulos[int(val_str)] = texto
                except ValueError:
                    rotulos[val_str] = texto
            else:
                rotulos[val_str] = texto
        result.append({
            "ordem":              i + 1,
            "nome_variavel":      v["name"],
            "descricao_completa": v.get("labl", ""),
            "tipo":               tipo,
            "tamanho":            v.get("loc_width"),
            "rotulos_valor":      rotulos,
        })
    return result


def encontrar_json(nome: str, pastas: list[Path]) -> Path | None:
    nome_longo = NOME_TABELA[nome]
    padroes = [
        f"{nome}_import_metadata_editor.json",
        f"{nome_longo}_import_metadata_editor.json",
        f"{nome}_metadados.json",
        f"{nome_longo}_metadados.json",
    ]
    for pasta in pastas:
        for padrao in padroes:
            p = pasta / padrao
            if p.exists():
                return p
    return None


def carregar_metadados(caminho_json: Path) -> list[dict]:
    with open(caminho_json, encoding="utf-8") as fh:
        dados = json.load(fh)
    if "variables" in dados:
        return _normalizar_novo_formato(dados["variables"])
    return dados["variaveis"]


# ---------------------------------------------------------------------------
# Construção de metadados e gravação de SAV
# ---------------------------------------------------------------------------

def truncar(texto: str, limite: int) -> str:
    if len(texto) <= limite:
        return texto
    corte = texto[: limite - 1]
    pos = corte.rfind(" ")
    if pos > limite * 0.6:
        corte = corte[:pos]
    return corte.rstrip(" ,.;-") + "…"


def construir_meta_sav(
    variaveis: list[dict],
    colunas_df: list[str],
) -> tuple[dict, dict, dict, dict, dict]:
    """Retorna (column_labels, value_labels, formatos, display_widths, medidas)."""
    meta_por_nome = {v["nome_variavel"]: v for v in variaveis}

    column_labels:  dict[str, str] = {}
    value_labels:   dict[str, dict] = {}
    formatos:       dict[str, str]  = {}
    display_widths: dict[str, int]  = {}
    medidas:        dict[str, str]  = {}

    for nome in colunas_df:
        var = meta_por_nome.get(nome)
        if var is None:
            medidas[nome] = "unknown"
            continue

        tipo = var["tipo"]

        if var.get("descricao_completa"):
            column_labels[nome] = truncar(var["descricao_completa"], LIMITE_ROTULO_VARIAVEL)

        rotulos_brutos: dict = var.get("rotulos_valor") or {}
        if rotulos_brutos:
            rv: dict = {}
            for chave_str, texto in rotulos_brutos.items():
                texto_ok = truncar(texto, LIMITE_ROTULO_VALOR)
                if tipo in ("Char", "Data"):
                    rv[chave_str] = texto_ok
                else:
                    try:
                        rv[int(chave_str)] = texto_ok
                    except ValueError:
                        rv[chave_str] = texto_ok
            value_labels[nome] = rv

        if tipo in ("Char", "Data") and var.get("tamanho"):
            largura = int(var["tamanho"])
            formatos[nome]       = f"A{largura}"
            display_widths[nome] = largura

        if rotulos_brutos:
            medidas[nome] = "nominal"
        elif tipo == "Num":
            medidas[nome] = "scale"
        else:
            medidas[nome] = "unknown"

    return column_labels, value_labels, formatos, display_widths, medidas


def gravar_sav(df: pd.DataFrame, caminho: Path, variaveis: list[dict]) -> float:
    """Grava df como .sav com metadados. Retorna tamanho em MB."""
    col_labels, val_labels, formatos, disp_widths, medidas = construir_meta_sav(
        variaveis, list(df.columns)
    )
    kwargs: dict = dict(
        column_labels=col_labels,
        variable_value_labels=val_labels,
        variable_measure=medidas,
    )
    if formatos:
        kwargs["variable_format"] = formatos
    if disp_widths:
        kwargs["variable_display_width"] = disp_widths
    pyreadstat.write_sav(df, str(caminho), **kwargs)
    return caminho.stat().st_size / 1_048_576
