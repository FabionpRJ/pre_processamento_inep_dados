"""Orquestração do serviço: insumos → JSONs + censo.html + relatório de casamento.

    resultado = gerar_metadados(dicionario, pasta_saida, pasta_questionarios,
                                caminho_caderno, ano="2025")

Só o dicionário é obrigatório. O dicionário é sempre lido inteiro: o recorte
(`tabelas_alvo`) vale só para os JSONs e o relatório; o censo.html recebe tudo
o que foi fornecido. O progresso vai para o logger `censo_etl`; os avisos
também são devolvidos em `ResultadoExecucao.avisos`.
"""
from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

from censo_etl import cache
from censo_etl.casamento import (
    mapear_conceitos_por_variavel,
    mapear_secoes_por_variavel,
    melhor_questao,
    rotulo_conceito,
)
from censo_etl.censo_html import gerar_censo_html, montar_dicionario, montar_questionario
from censo_etl.dicionario import TabelaDicionario, ler_dicionario
from censo_etl.edicao import nome_censo_html, prefixo_edicao
from censo_etl.erros import EntradaInvalida
from censo_etl.insumos import localizar_questionario
from censo_etl.metadata_editor import EnriquecimentoVariavel, gravar_json
from censo_etl.pdf.caderno_conceitos import extrair_conceitos
from censo_etl.pdf.caderno_quadros import extrair_quadros
from censo_etl.pdf.caderno_secoes import extrair_secoes
from censo_etl.pdf.questionarios import LeitorQuestionarios
from censo_etl.relatorio import LinhaRelatorio, gravar_relatorio
from censo_etl.tabelas import rotulo
from censo_etl.valores_especiais import IMPUTACAO, parece_sentinela, separar_codigos_especiais

log = logging.getLogger(__name__)


@dataclass
class ResultadoTabela:
    chave: str
    json: Path
    n_variaveis: int
    n_questoes: int
    n_com_questao: int
    n_com_caderno: int
    n_com_conceito: int
    n_imputacao: int
    n_nao_resposta: int


@dataclass
class ResultadoExecucao:
    ano: str | None
    jsons: list[Path] = field(default_factory=list)
    censo_html: Path | None = None
    relatorio: Path | None = None
    tabelas: list[ResultadoTabela] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


@dataclass
class _FontesCaderno:
    secoes_por_variavel: dict[str, dict[str, dict]]   # var_txt / var_qstn_ivuinstr
    conceitos: list[dict]                             # censo.html e var_concept
    quadros: list[dict]


def gerar_metadados(
    caminho_dicionario: Path,
    pasta_saida: Path,
    pasta_questionarios: Path | None = None,
    caminho_caderno: Path | None = None,
    *,
    ano: str | None = None,
    tabelas_alvo: list[str] | None = None,
    gerar_html: bool = True,
    incluir_questionarios: bool = True,
) -> ResultadoExecucao:
    """Gera os metadados. `ano` já detectado pelo chamador (None = saída sem ano)."""
    with _coletar_avisos() as avisos:
        resultado = _executar(caminho_dicionario, pasta_saida, pasta_questionarios,
                              caminho_caderno, ano, tabelas_alvo, gerar_html, incluir_questionarios)
    resultado.avisos = avisos
    return resultado


def _executar(caminho_dicionario, pasta_saida, pasta_questionarios, caminho_caderno,
              ano, tabelas_alvo, gerar_html, incluir_questionarios) -> ResultadoExecucao:
    if not caminho_dicionario.exists():
        raise EntradaInvalida(f'Arquivo não encontrado: "{caminho_dicionario}"')
    log.info('Lendo dicionário: "%s"', caminho_dicionario)
    if ano:
        log.info("  Edição: %s — saída como %smicrodados_tabela_*", ano, prefixo_edicao(ano))
    else:
        log.warning("Ano da edição não determinado; a saída sai sem ano (%smicrodados_tabela_*).",
                    prefixo_edicao(None))

    todas, alvo = _ler_e_recortar(caminho_dicionario, tabelas_alvo)
    pasta_saida.mkdir(parents=True, exist_ok=True)
    resultado = ResultadoExecucao(ano=ano)

    leitor = LeitorQuestionarios()
    pdf_por_tabela = _localizar_questionarios(pasta_questionarios, todas, alvo)
    caderno = _ler_caderno(caminho_caderno, pasta_saida, todas)

    questionarios_html = _questionarios_html(pdf_por_tabela, leitor) if incluir_questionarios else []
    if not incluir_questionarios:
        log.info("  Questionários (PDF) não serão incluídos no censo.html.")
    if gerar_html:
        resultado.censo_html = _gravar_censo_html(pasta_saida / nome_censo_html(ano), caderno,
                                                  questionarios_html, montar_dicionario(todas))
    else:
        log.info("  Geração de censo.html desativada pelo usuário.")

    variaveis_por_tabela = {chave: t.variaveis for chave, t in todas.items()}
    conceito_por_variavel = mapear_conceitos_por_variavel(caderno.conceitos, variaveis_por_tabela)
    if caderno.conceitos:
        log.info("  Conceitos casados a %d variável(is) em %d tabela(s) (var_concept).",
                 sum(len(m) for m in conceito_por_variavel.values()), len(conceito_por_variavel))

    linhas_relatorio: list[LinhaRelatorio] = []
    for chave, tabela in alvo.items():
        pdf = pdf_por_tabela.get(chave)
        questoes = [p["texto"] for p in leitor.perguntas(pdf)] if pdf else []
        resumo, linhas = _processar_tabela(
            tabela, pasta_saida, ano, questoes,
            caderno.secoes_por_variavel.get(chave, {}), conceito_por_variavel.get(chave, {}))
        resultado.tabelas.append(resumo)
        resultado.jsons.append(resumo.json)
        linhas_relatorio.extend(linhas)

    resultado.relatorio = gravar_relatorio(linhas_relatorio, pasta_saida, ano)
    if resultado.relatorio:
        log.info("  Relatório de casamento: %s (%d linhas) — revise antes de publicar.",
                 resultado.relatorio.name, len(linhas_relatorio))
    log.info('JSONs gravados em: "%s"', pasta_saida.resolve())
    return resultado


# ---------------------------------------------------------------------------
# Etapas
# ---------------------------------------------------------------------------

def _ler_e_recortar(
    caminho: Path, tabelas_alvo: list[str] | None
) -> tuple[dict[str, TabelaDicionario], dict[str, TabelaDicionario]]:
    todas = ler_dicionario(caminho)
    if not todas:
        raise EntradaInvalida("Nenhuma aba reconhecida no dicionário.")
    pedidas = list(tabelas_alvo) if tabelas_alvo else list(todas)
    alvo = {chave: t for chave, t in todas.items() if chave in pedidas}
    if faltantes := [t for t in pedidas if t not in todas]:
        log.warning("Sem aba no dicionário para: %s", ", ".join(faltantes))
    if not alvo:
        raise EntradaInvalida("Nenhuma aba do dicionário correspondeu às tabelas solicitadas.")
    log.info("  Abas lidas: %s", ", ".join(todas))
    log.info("  JSONs a gerar: %s", ", ".join(alvo))
    return todas, alvo


def _localizar_questionarios(pasta: Path | None, todas: dict, alvo: dict) -> dict[str, Path]:
    """PDF de cada tabela do dicionário (os de fora do recorte vão para o censo.html)."""
    if pasta is None or not pasta.is_dir():
        log.warning("Pasta de questionários não informada; var_qstn_qstnlit ficará vazio.")
        return {}
    log.info('Questionários: "%s"', pasta.resolve())
    pdfs = {}
    for chave in todas:
        if pdf := localizar_questionario(pasta, chave):
            pdfs[chave] = pdf
        elif chave in alvo:
            log.warning("Questionário PDF não encontrado para %s.", chave)
    return pdfs


def _ler_caderno(caminho: Path | None, pasta_saida: Path, todas: dict) -> _FontesCaderno:
    """As duas leituras do Caderno, cada uma com seu cache versionado."""
    variaveis = {chave: t.variaveis for chave, t in todas.items()}
    nomes = {chave: [v.nome for v in vs] for chave, vs in variaveis.items()}

    log.info("Metadados do Caderno de Conceitos:")
    caminho_cache = pasta_saida / cache.CACHE_SECOES
    impressao = cache.impressao_digital(caminho, nomes)
    secoes = cache.ler(caminho_cache, impressao)
    if secoes is not None:
        log.info("  Metadados do Caderno já estruturados: %s (leitura do PDF dispensada)", caminho_cache.name)
    elif caminho and caminho.is_file():
        log.info("  Extraindo conceitos do Caderno: %s ...", caminho.name)
        try:
            secoes = mapear_secoes_por_variavel(extrair_secoes(caminho), variaveis)
        except Exception as exc:
            log.error("Não foi possível ler o Caderno: %s", exc)
        else:
            log.info("  Conceitos alinhados a %d variável(is) em %d tabela(s).",
                     sum(len(m) for m in secoes.values()), len(secoes))
            cache.gravar(caminho_cache, impressao, secoes)
    if not secoes:
        log.warning("Nenhum metadado do Caderno disponível; "
                    "var_txt/var_qstn_ivuinstr do Caderno ficarão vazios.")

    conceitos: list[dict] = []
    quadros: list[dict] = []
    if caminho and caminho.is_file():
        caminho_cache = pasta_saida / cache.CACHE_CONCEITOS
        impressao = cache.impressao_digital(caminho)   # depende só do PDF
        try:
            dados = cache.ler(caminho_cache, impressao)
            if dados is not None:
                log.info("  Conceitos já estruturados: %s (leitura do PDF dispensada)", caminho_cache.name)
            else:
                dados = {"conceitos": extrair_conceitos(caminho), "quadros": extrair_quadros(caminho)}
                cache.gravar(caminho_cache, impressao, dados)
            conceitos, quadros = dados["conceitos"], dados["quadros"]
        except Exception as exc:
            log.warning("Não foi possível extrair conceitos/quadros do Caderno: %s", exc)
    return _FontesCaderno(secoes or {}, conceitos, quadros)


def _questionarios_html(pdf_por_tabela: dict[str, Path], leitor: LeitorQuestionarios) -> list[dict]:
    """Um bloco por PDF (o de Turma serve duas tabelas e aparece uma vez)."""
    blocos, vistos = [], set()
    for chave, pdf in pdf_por_tabela.items():
        if pdf.name in vistos:
            continue
        vistos.add(pdf.name)
        if perguntas := leitor.perguntas(pdf):
            blocos.append(montar_questionario(chave, pdf, perguntas))
    if blocos:
        log.info("  Questionários estruturados: %d pergunta(s) em %d questionário(s).",
                 sum(len(b["perguntas"]) for b in blocos), len(blocos))
    return blocos


def _gravar_censo_html(destino: Path, caderno: _FontesCaderno,
                       questionarios: list[dict], dicionario: list[dict]) -> Path | None:
    if not (caderno.conceitos or caderno.quadros or questionarios or dicionario):
        log.warning("Nenhuma fonte disponível; censo.html não será gerado.")
        return None
    log.info("Gerando censo.html (dicionário + Caderno de Conceitos + questionários)...")
    try:
        caminho = gerar_censo_html(destino, caderno.conceitos, caderno.quadros, questionarios, dicionario)
    except Exception as exc:
        log.warning("Não foi possível gerar censo.html: %s", exc)
        return None
    log.info("  OK: %s (%d conceitos, %d quadros, %d questionário(s), %d variáveis em %d tabela(s))",
             caminho.name, len(caderno.conceitos), len(caderno.quadros), len(questionarios),
             sum(len(t["variaveis"]) for t in dicionario), len(dicionario))
    return caminho


def _processar_tabela(
    tabela: TabelaDicionario,
    pasta_saida: Path,
    ano: str | None,
    questoes: list[str],
    caderno: dict[str, dict],
    conceitos: dict[str, dict],
) -> tuple[ResultadoTabela, list[LinhaRelatorio]]:
    """JSON da tabela, linhas do relatório e avisos. O casamento com as questões
    (caro: variáveis × questões) é resolvido uma vez e reaproveitado."""
    casamento = {v.nome: melhor_questao(v.descricao, questoes) for v in tabela.variaveis}
    enriquecimento = {
        v.nome: EnriquecimentoVariavel(casamento[v.nome][0], caderno.get(v.nome), conceitos.get(v.nome))
        for v in tabela.variaveis
    }
    caminho = gravar_json(tabela, pasta_saida, ano, enriquecimento)

    linhas: list[LinhaRelatorio] = []
    n_imputacao = n_nao_resposta = 0
    sentinelas_sem_marcador: list[str] = []
    for v in tabela.variaveis:
        reais, especiais = separar_codigos_especiais(v.rotulos_valor)
        n_imputacao += sum(1 for tipo, _ in especiais.values() if tipo == IMPUTACAO)
        n_nao_resposta += sum(1 for tipo, _ in especiais.values() if tipo != IMPUTACAO)
        sentinelas_sem_marcador += [f"{v.nome}:{c}=“{r[:60]}”" for c, r in reais.items() if parece_sentinela(c)]
        questao, pontos = casamento[v.nome]
        linhas.append(LinhaRelatorio(
            tabela=tabela.chave,
            variavel=v.nome,
            descricao=v.descricao,
            conceito=rotulo_conceito((conceitos.get(v.nome) or {}).get("conceito", "")),
            tem_var_txt="sim" if caderno.get(v.nome, {}).get("var_txt") else "",
            questao=questao,
            score_questao=f"{pontos:.3f}" if questao else "",
            valores_especiais=" ".join(f"{c}={tipo}" for c, (tipo, _) in sorted(especiais.items())),
        ))

    resumo = ResultadoTabela(
        chave=tabela.chave, json=caminho, n_variaveis=len(tabela.variaveis),
        n_questoes=len(questoes), n_com_questao=sum(1 for q, _ in casamento.values() if q),
        n_com_caderno=len(caderno), n_com_conceito=len(conceitos),
        n_imputacao=n_imputacao, n_nao_resposta=n_nao_resposta,
    )
    _registrar_tabela(resumo, sentinelas_sem_marcador)
    return resumo, linhas


def _registrar_tabela(r: ResultadoTabela, sentinelas_sem_marcador: list[str]) -> None:
    """Linha de resumo e avisos da tabela. Tabela sem nenhum metadado semântico
    é sempre sintoma de problema, por isso é avisada."""
    n = r.n_variaveis
    detalhes = [f"{n} vars", f"{r.n_questoes} questões PDF"]
    if r.n_questoes:
        detalhes.append(f"{r.n_com_questao}/{n} vars com questão")
    if r.n_com_caderno:
        detalhes.append(f"{r.n_com_caderno}/{n} vars com conceito")
    if r.n_com_conceito:
        detalhes.append(f"{r.n_com_conceito}/{n} vars com var_concept")
    log.info("  OK: %s  (%s)", r.json.name, ", ".join(detalhes))

    nome = rotulo(r.chave)
    if r.n_questoes == 0:
        log.warning("%s: nenhuma questão disponível — var_qstn_qstnlit ficará vazio nas %d variáveis.",
                    nome, n)
    elif r.n_com_questao == 0:
        log.warning("%s: %d questões extraídas, mas nenhuma casou com as variáveis — "
                    "var_qstn_qstnlit vazio.", nome, r.n_questoes)
    if r.n_com_conceito == 0:
        log.warning("%s: nenhum conceito do Caderno casou — var_concept ficará vazio nas %d variáveis.",
                    nome, n)
    if r.n_imputacao or r.n_nao_resposta:
        log.info("    Valores especiais: %d código(s) em var_invalrng + var_imputation "
                 "(%d de tratamento de consistência, %d de não-resposta).",
                 r.n_imputacao + r.n_nao_resposta, r.n_imputacao, r.n_nao_resposta)
    if sentinelas_sem_marcador:
        extra = len(sentinelas_sem_marcador) - 5
        log.warning("%s: %d código(s) com forma de sentinela seguem valendo como CATEGORIA REAL "
                    "porque o rótulo não casou com nenhum marcador conhecido — confira e, se for o "
                    "caso, estenda censo_etl.valores_especiais.MARCADORES_*: %s%s",
                    nome, len(sentinelas_sem_marcador), "; ".join(sentinelas_sem_marcador[:5]),
                    f" (+{extra})" if extra > 0 else "")


# ---------------------------------------------------------------------------
# Avisos
# ---------------------------------------------------------------------------

class _ColetorAvisos(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.mensagens: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.mensagens.append(record.getMessage())


@contextlib.contextmanager
def _coletar_avisos():
    """Guarda as mensagens de aviso emitidas por qualquer módulo do pacote."""
    coletor = _ColetorAvisos()
    raiz = logging.getLogger("censo_etl")
    raiz.addHandler(coletor)
    try:
        yield coletor.mensagens
    finally:
        raiz.removeHandler(coletor)
