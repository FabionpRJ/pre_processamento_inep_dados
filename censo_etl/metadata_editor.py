"""JSON de importação do World Bank Metadata Editor (DDI-CodeBook 2.5).

Um arquivo por tabela: `{"datafile": {...}, "variables": [...]}`, com os 35
campos por variável na ordem abaixo. A procedência de cada campo está em
docs/especificacao.md.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from censo_etl import formato
from censo_etl.casamento import rotulo_conceito
from censo_etl.dicionario import TabelaDicionario, Variavel
from censo_etl.edicao import nome_saida_json, nome_saida_sav
from censo_etl.tabelas import POR_CHAVE
from censo_etl.valores_especiais import descrever_imputacao, separar_codigos_especiais

UNIVERSO_SEM_ANO = "Escola de Educação Básica declarada no Censo Escolar"

# Estatísticas-resumo por convenção de nome do INEP.
_PREFIXO_RE = re.compile(r"^([A-Z]+)_")
PREFIXOS_CONTINUOS = {"QT"}                # contagens
NOMES_CONTINUOS = {"LATITUDE", "LONGITUDE"}
PREFIXOS_IDENTIFICADOR = {"CO", "NU", "ID"}  # códigos administrativos
NOMES_IDENTIFICADOR = {"NO_ENTIDADE"}      # "Código da Escola", apesar do prefixo NO_


@dataclass
class EnriquecimentoVariavel:
    """O que as fontes opcionais acrescentam a uma variável."""
    questao: str = ""                    # var_qstn_qstnlit
    caderno: dict | None = None          # {var_txt?, var_destaque?, var_qstn_ivuinstr?}
    conceito: dict | None = None         # conceito casado (var_concept)


def universo_publicacao(ano: str | int | None) -> str:
    """`var_universe`: a população, igual nas seis tabelas (dados agregados por escola)."""
    return f"Escola de Educação Básica declarada em {ano}" if ano else UNIVERSO_SEM_ANO


def anos_coletados(var: Variavel) -> str:
    """"Coletado em 2025" ou "Coletado em: 2019–2025" (anos marcados "s")."""
    anos = sorted(ano for ano, valor in var.anos_coleta.items() if valor == "s")
    if not anos:
        return ""
    if len(anos) == 1:
        return f"Coletado em {anos[0]}"
    return f"Coletado em: {anos[0]}–{anos[-1]}"


def nota_descontinuada(var: Variavel, ano_dicionario: str | None) -> str:
    """"n" na coluna do ano do dicionário = descontinuada naquele ano.

    Critério literal, decidido em reunião (docs/decisoes.md): vale também para
    variáveis com "n" em todos os anos.
    """
    if ano_dicionario and var.anos_coleta.get(ano_dicionario) == "n":
        return f"Variável descontinuada no ano de {ano_dicionario}."
    return ""


def opcoes_estatisticas(var: Variavel) -> dict:
    """`sum_stats_options`. Sem pesos: o Censo é enumeração completa.

    Só categorias REAIS tornam a variável categórica — códigos especiais não
    contam (senão os CNPJ, cuja única "categoria" é "Sem declaração", pediriam
    frequência de 200 mil valores).
    """
    opcoes = {
        "wgt": False, "freq": False, "missing": True, "vald": True,
        "min": False, "max": False, "mean": False, "mean_wgt": False,
        "stdev": False, "stdev_wgt": False,
    }
    continua = {"min": True, "max": True, "mean": True, "stdev": True}
    m = _PREFIXO_RE.match(var.nome)
    prefixo = m.group(1) if m else ""
    categorias_reais, _ = separar_codigos_especiais(var.rotulos_valor)

    if var.tipo == "Data":
        opcoes.update(min=True, max=True)
    elif var.nome in NOMES_IDENTIFICADOR:
        pass
    elif var.nome in NOMES_CONTINUOS or prefixo in PREFIXOS_CONTINUOS:
        opcoes.update(continua)
    elif categorias_reais:
        opcoes["freq"] = True
    elif var.tipo == "Num" and prefixo not in PREFIXOS_IDENTIFICADOR:
        opcoes.update(continua)
    return opcoes


def formato_declarado(var: Variavel) -> dict:
    if var.tipo in ("Char", "Data"):
        return {
            "type": "character", "schema": "other", "readstat_type": "string",
            "data_format": f"A{int(var.tamanho) if var.tamanho else 1}",
            "is_date": var.tipo == "Data",
        }
    return {
        "type": "numeric", "schema": "other", "readstat_type": "double",
        "data_format": formato.formato_numerico(var.tipo, var.nome, var.tamanho),
        "is_date": False,
    }


def _juntar(*partes: str) -> str:
    return "\n".join(p for p in partes if p).strip()


def montar_variavel(
    var: Variavel,
    indice: int,
    fid: str,
    universo: str,
    ano_dicionario: str | None,
    extra: EnriquecimentoVariavel | None = None,
) -> dict:
    extra = extra or EnriquecimentoVariavel()
    caderno = extra.caderno or {}
    _, especiais = separar_codigos_especiais(var.rotulos_valor)
    opcoes = opcoes_estatisticas(var)
    intervalo = "contin" if opcoes["mean"] else "discrete"
    var_format = formato_declarado(var)
    titulo_conceito = rotulo_conceito((extra.conceito or {}).get("conceito", ""))

    return {
        "uid":                  str(indice),
        "sid":                  fid.replace("F", ""),
        "fid":                  fid,
        "vid":                  f"V{indice}",
        "name":                 var.nome,
        "labl":                 var.descricao,
        "sort_order":           str(indice - 1),
        "var_intrvl":           intervalo,
        "loc_width":            formato.largura(var.tamanho),
        # Códigos especiais: declarados como inválidos, mas o rótulo é mantido
        # em var_catgry_labels — quem lê o metadado precisa saber o que 88888 é.
        "var_invalrng":         {"values": [str(c) for c in sorted(especiais)]},
        "var_valrng":           {"range": {"UNITS": "REAL", "count": 0, "min": "", "max": ""}},
        "var_sumstat":          [],
        "var_catgry":           [],
        "var_catgry_labels":    [{"value": str(c), "labl": t} for c, t in sorted(var.rotulos_valor.items())],
        "var_format":           var_format,
        "var_format_original":  var_format,
        "file_id":              fid,
        "interval_type":        intervalo,
        "sum_stats_options":    opcoes,
        "var_concept":          [[{"concept": titulo_conceito, "vocab": "", "vocabURI": ""}]]
                                if titulo_conceito else [[]],
        "var_wgt_id":           "",
        "var_universe":         universo,
        "var_txt":              caderno.get("var_txt") or var.descricao,
        "var_security":         "",
        # Para quem ANALISA: notas do dicionário, anos de coleta, descontinuidade.
        "var_notes":            _juntar(var.notas or "", anos_coletados(var),
                                        nota_descontinuada(var, ano_dicionario)),
        "var_respunit":         "",
        "var_qstn_preqtxt":     "",
        "var_qstn_qstnlit":     extra.questao,
        "var_qstn_postqtxt":    "",
        "var_forward":          "",
        "var_backward":         "",
        # Para quem PREENCHE: orientação e destaques do Caderno.
        "var_qstn_ivuinstr":    _juntar(caderno.get("var_qstn_ivuinstr") or "",
                                        caderno.get("var_destaque") or ""),
        "var_codinstr":         "",
        "var_imputation":       descrever_imputacao(especiais),
        "var_derivation":       "",
    }


def montar_datafile(tabela: TabelaDicionario, ano: str | None) -> dict:
    """Cabeçalho do JSON. `file_name` declara o `.sav` a que o metadado se refere
    (é por ele que o Metadata Editor os amarra); `case_count` sai 0 porque os
    microdados não são lidos."""
    fid = POR_CHAVE[tabela.chave].fid
    return {
        "file_id":    fid,
        "fid":        fid,
        "file_name":  nome_saida_sav(tabela.chave, ano),
        "labl":       tabela.titulo,
        "var_count":  len(tabela.variaveis),
        "case_count": 0,
    }


def gravar_json(
    tabela: TabelaDicionario,
    pasta_saida: Path,
    ano: str | None,
    enriquecimento: dict[str, EnriquecimentoVariavel],
) -> Path:
    fid = POR_CHAVE[tabela.chave].fid
    # O universo segue o ano do DICIONÁRIO, não o ano que nomeia a saída.
    universo = universo_publicacao(tabela.ano_dicionario or ano)
    payload = {
        "datafile": montar_datafile(tabela, ano),
        "variables": [
            montar_variavel(v, i, fid, universo, tabela.ano_dicionario, enriquecimento.get(v.nome))
            for i, v in enumerate(tabela.variaveis, start=1)
        ],
    }
    pasta_saida.mkdir(parents=True, exist_ok=True)
    caminho = pasta_saida / nome_saida_json(tabela.chave, ano)
    with open(caminho, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return caminho
