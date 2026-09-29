"""Interface Streamlit do gerador de metadados do Censo Escolar.

    streamlit run app.py

Só desenha e coleta: a lógica está em `censo_etl` (pipeline, insumos e servico).
"""
from __future__ import annotations

import logging
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

import streamlit as st

# Permite `streamlit run` a partir de outro diretório.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from censo_etl.dicionario import tabelas_do_dicionario
from censo_etl.edicao import detectar_ano_em_cascata, prefixo_edicao
from censo_etl.erros import EntradaInvalida
from censo_etl.insumos import (
    NomesClassificados,
    extrair_insumos_zip,
    inspecionar_zip,
    ler_membro_zip,
    localizar_insumos,
)
from censo_etl.logs import registrar_saida, remover_saida
from censo_etl.pipeline import gerar_metadados
from censo_etl.servico import (
    NOME_PACOTE,
    ResultadoApp,
    assinatura,
    avisos_de_lacunas,
    empacotar,
    explicar_erro,
    mensagem_sucesso,
)
from censo_etl.tabelas import rotulo

MODO_ZIP = "ZIP oficial do INEP"
MODO_ARQUIVOS = "Arquivos separados"
LOG_MAX = 50                                     # linhas visíveis na janela de log
P_ENTRADAS, P_METADADOS, P_EMPACOTE = 10, 90, 95  # faixas da barra de progresso


@dataclass
class Entradas:
    """O que o usuário enviou, em qualquer dos dois modos."""
    modo: str
    uploads: list = field(default_factory=list)          # para a assinatura
    dicionario_bytes: bytes | None = None
    zip: object | None = None
    zip_info: NomesClassificados | None = None
    dicionario: object | None = None
    caderno: object | None = None
    questionarios: list = field(default_factory=list)
    usar_caderno: bool = True
    usar_questionarios: bool = True

    @property
    def tem_caderno(self) -> bool:
        """O insumo foi pedido E existe (no zip, é o que a varredura achou)."""
        if self.modo == MODO_ZIP:
            return bool(self.zip_info and self.zip_info.caderno)
        return self.usar_caderno and self.caderno is not None

    @property
    def tem_questionarios(self) -> bool:
        if self.modo == MODO_ZIP:
            return bool(self.zip_info and self.zip_info.questionarios)
        return self.usar_questionarios and bool(self.questionarios)


@dataclass
class Opcoes:
    tabelas: list[str]
    gerar_html: bool
    incluir_questionarios: bool


# ---------------------------------------------------------------------------
# Entradas
# ---------------------------------------------------------------------------

def coletar_entradas() -> Entradas:
    modo = st.radio(
        "Forma de envio dos insumos", [MODO_ZIP, MODO_ARQUIVOS], horizontal=True,
        help="O ZIP oficial traz tudo junto (os CSVs de microdados são ignorados). O modo por "
             "arquivos permite combinar insumos de origens/anos diferentes — por exemplo, um "
             "dicionário novo com o Caderno e os questionários já em mãos.",
    )
    st.caption(f"Limite de upload por arquivo: **{st.get_option('server.maxUploadSize')} MB**.")
    return _entradas_zip() if modo == MODO_ZIP else _entradas_arquivos()


def _entradas_zip() -> Entradas:
    arquivo = st.file_uploader(
        "Arquivo .zip dos microdados", type="zip",
        help="Arquivo baixado do site do INEP — a estrutura interna de pastas não importa; os "
             "insumos são localizados pelos próprios arquivos. Só o dicionário, o Caderno e os "
             "questionários são extraídos.",
    )
    entradas = Entradas(MODO_ZIP, uploads=[arquivo], zip=arquivo)
    if arquivo is None:
        return entradas
    info = inspecionar_zip(arquivo)
    if info is None:
        st.error("O .zip não pôde ser lido — arquivo corrompido ou incompleto.")
        st.stop()
    if not info.dicionario:
        st.error("Nenhum dicionário encontrado dentro do zip. É esperado um `.xlsx` com "
                 "'dicionário' no nome — ou, na falta dele, um único `.xlsx` no pacote.")
        st.stop()
    entradas.zip_info = info
    entradas.dicionario_bytes = ler_membro_zip(arquivo, info.dicionario)
    with st.expander("Conteúdo identificado no zip", expanded=False):
        linhas = [
            f"- **Dicionário:** `{Path(info.dicionario).name}`",
            "- **Caderno de Conceitos:** "
            + (f"`{Path(info.caderno).name}`" if info.caderno else "_não encontrado_"),
            f"- **Questionários:** {len(info.questionarios)} PDF(s)",
        ]
        if info.csvs:
            linhas.append(f"- **CSVs de microdados:** {len(info.csvs)} — **ignorados**, "
                          "o pipeline não lê os dados.")
        st.markdown("\n".join(linhas))
    return entradas


def _entradas_arquivos() -> Entradas:
    st.subheader("Insumo obrigatório")
    dicionario = st.file_uploader(
        "1. Dicionário de variáveis (.xlsx)", type="xlsx",
        help="Planilha com uma aba por tabela (Tabela_de_Escola, Tabela_de_Matrícula, …). Fonte "
             "dos nomes, tipos, rótulos e categorias das variáveis, e a única entrada obrigatória.",
    )
    st.subheader("Metadados opcionais")
    usar_caderno = st.checkbox(
        "Incluir Caderno de Conceitos", value=True,
        help="Preenche `var_concept` (conceitos e definições) e alimenta o glossário e os quadros "
             "de referência do censo.html. Sem ele o pipeline roda, mas esses campos ficam vazios.",
    )
    caderno = st.file_uploader(
        "2. Caderno de Conceitos e Orientações (.pdf)", type="pdf",
        help="Fonte dos conceitos (var_concept), definições e quadros de referência.",
    ) if usar_caderno else None
    usar_questionarios = st.checkbox(
        "Incluir questionários", value=True,
        help="Preenche `var_qstn_qstnlit` (pergunta literal de cada variável). Sem eles o "
             "pipeline roda, mas esse campo fica vazio.",
    )
    questionarios = (st.file_uploader(
        "3. Questionários (.pdf)", type="pdf", accept_multiple_files=True,
        help="PDFs no padrão '<Nome> <ano>.pdf' (Escola, Aluno, Turma, Gestor Escolar, "
             "Profissional Escolar). Fonte das questões literais (var_qstn_qstnlit).",
    ) or []) if usar_questionarios else []
    return Entradas(
        MODO_ARQUIVOS, uploads=[dicionario, caderno, *questionarios],
        dicionario_bytes=bytes(dicionario.getbuffer()) if dicionario else None,
        dicionario=dicionario, caderno=caderno, questionarios=questionarios,
        usar_caderno=usar_caderno, usar_questionarios=usar_questionarios,
    )


# ---------------------------------------------------------------------------
# Tabelas e opções
# ---------------------------------------------------------------------------

def escolher_tabelas(dicionario_bytes: bytes) -> list[str]:
    """Multiselect alimentado pelas abas do dicionário."""
    opcoes = tabelas_do_dicionario(dicionario_bytes)
    if not opcoes:
        st.error("Nenhuma aba do arquivo foi reconhecida como tabela do Censo. Confira se o `.xlsx` "
                 "enviado é mesmo o Dicionário de Variáveis do INEP (abas no padrão "
                 "`Tabela_de_Escola`, `Tabela_de_Matrícula`, …).")
        st.stop()
    # A seleção vive em session_state para os botões poderem alterá-la; outro
    # dicionário pode trazer outras abas, então ela é filtrada.
    if "tabelas" not in st.session_state:
        st.session_state.tabelas = list(opcoes)
    elif (validas := [t for t in st.session_state.tabelas if t in opcoes]) != list(st.session_state.tabelas):
        st.session_state.tabelas = validas

    st.subheader("Tabelas a processar")
    todas, limpar, _ = st.columns([1, 1, 2])
    if todas.button("Selecionar todas", width="stretch"):
        st.session_state.tabelas = list(opcoes)
        st.rerun()
    if limpar.button("Limpar seleção", width="stretch"):
        st.session_state.tabelas = []
        st.rerun()
    return st.multiselect(
        "Tabelas a processar", options=opcoes, key="tabelas", label_visibility="collapsed",
        format_func=rotulo,
        help="Um JSON de importação por tabela marcada. O dicionário é lido por inteiro de "
             "qualquer forma — o recorte afeta só os JSONs gerados.",
    )


def escolher_opcoes(entradas: Entradas, tabelas: list[str]) -> Opcoes:
    st.subheader("Opções de saída")
    gerar_html = st.checkbox(
        "Gerar censo.html (dicionário + Caderno de Conceitos + questionários)", value=True,
        help="Arquivo HTML autocontido com o dicionário de variáveis das tabelas processadas, o "
             "glossário de conceitos e os quadros de referência do Censo.",
    )
    incluir = st.checkbox(
        "Incluir questionários (PDF) no censo.html", value=True,
        disabled=not (gerar_html and entradas.tem_questionarios),
        help="Adiciona uma aba com as perguntas numeradas extraídas dos questionários em PDF."
             if entradas.tem_questionarios else "Indisponível: nenhum questionário foi fornecido.",
    )
    # Sem questionário não há aba a gerar: travar evita que o painel de
    # cobertura discorde do censo.html produzido.
    return Opcoes(tabelas, gerar_html, bool(incluir and gerar_html and entradas.tem_questionarios))


def painel_cobertura(entradas: Entradas) -> None:
    """Antes de processar: quais campos a seleção atual preenche."""
    def item(ok: bool, texto: str, fonte: str) -> str:
        return f"- {'✅' if ok else '❌'} {texto} — *{fonte}*" + ("" if ok else " — **ficará vazio**")

    with st.container(border=True):
        st.markdown("**Cobertura de metadados com a seleção atual**")
        st.markdown("\n".join([
            item(True, "nomes, tipos, rótulos e categorias", "dicionário"),
            item(entradas.tem_caderno, "conceitos e definições (`var_concept`)", "Caderno de Conceitos"),
            item(entradas.tem_questionarios, "perguntas literais (`var_qstn_qstnlit`)", "questionários"),
        ]))
        st.caption("`case_count` sai **0** em todos os JSONs: o ETL não lê os microdados e portanto "
                   "não conhece o número de linhas de cada tabela.")


def validar(entradas: Entradas, opcoes: Opcoes) -> None:
    if entradas.modo == MODO_ARQUIVOS:
        # Opção marcada sem arquivo é ambígua: exige a decisão.
        pendentes = [rotulo for rotulo, pendente in [
            ("Caderno de Conceitos (.pdf)", entradas.usar_caderno and entradas.caderno is None),
            ("questionários (.pdf)", entradas.usar_questionarios and not entradas.questionarios),
        ] if pendente]
        if pendentes:
            st.info("Aguardando: " + ", ".join(pendentes)
                    + ". Envie o(s) arquivo(s) ou desmarque a opção correspondente.")
            st.stop()
    if not opcoes.tabelas:
        st.warning("Selecione pelo menos uma tabela.")
        st.stop()


# ---------------------------------------------------------------------------
# Processamento
# ---------------------------------------------------------------------------

class _JanelaLog(logging.Handler):
    """Mostra as últimas `LOG_MAX` linhas do log numa caixa de código."""

    def __init__(self, destino) -> None:
        super().__init__()
        self.destino = destino
        self.linhas: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.escrever(self.format(record))

    def escrever(self, texto: str) -> None:
        self.linhas.extend(texto.splitlines() or [""])
        visiveis = self.linhas[-LOG_MAX:]
        omitidas = len(self.linhas) - len(visiveis)
        cabecalho = [f"… ({omitidas} linha(s) anterior(es) omitida(s))"] if omitidas else []
        self.destino.code("\n".join(cabecalho + visiveis), language="text")


def _gravar_upload(upload, pasta: Path) -> Path:
    """Em disco com o nome original: o nome identifica o questionário e o ano."""
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / Path(upload.name).name
    caminho.write_bytes(upload.getbuffer())
    return caminho


def _materializar(entradas: Entradas, pasta: Path) -> tuple[Path, Path | None, Path | None, list]:
    """(dicionário, caderno, pasta de questionários, nomes extras para o ano)."""
    if entradas.modo == MODO_ZIP:
        extrair_insumos_zip(entradas.zip, pasta)
        # Nada depende do nome das pastas do INEP: são deduzidas dos arquivos.
        insumos = localizar_insumos(pasta)
        if insumos.dicionario is None:
            raise EntradaInvalida("Dicionário .xlsx não encontrado dentro do zip.")
        extras = [Path(entradas.zip.name)]
        return insumos.dicionario, insumos.caderno, insumos.pasta_questionarios, extras
    dicionario = _gravar_upload(entradas.dicionario, pasta / "dicionario")
    caderno = _gravar_upload(entradas.caderno, pasta / "caderno") if entradas.tem_caderno else None
    pasta_q = None
    if entradas.tem_questionarios:
        pasta_q = pasta / "questionarios"
        for upload in entradas.questionarios:
            _gravar_upload(upload, pasta_q)
    return dicionario, caderno, pasta_q, []


def processar(entradas: Entradas, opcoes: Opcoes, assinatura_atual: tuple) -> None:
    inicio = time.monotonic()
    col_barra, col_cancelar = st.columns([4, 1])
    barra = col_barra.progress(0, text="Iniciando...")
    # Qualquer interação interrompe o script no próximo ponto de verificação;
    # como tudo roda em pasta temporária, nada fica gravado.
    col_cancelar.button("Cancelar", help="Interrompe no próximo ponto de verificação. Nada é "
                                         "gravado — o processamento roda em pasta temporária.")
    janela = _JanelaLog(st.empty())

    def avancar(pct: int, texto: str) -> None:
        s = int(time.monotonic() - inicio)
        barra.progress(pct, text=f"{texto}  ·  {s // 60}m{s % 60:02d}s")

    registrar_saida(janela)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            avancar(P_ENTRADAS, "Preparando os insumos...")
            dicionario, caderno, pasta_q, extras = _materializar(entradas, Path(tmp) / "entrada")
            outros = [caderno, *(sorted(pasta_q.glob("*.pdf")) if pasta_q else []), *extras]
            ano = detectar_ano_em_cascata(dicionario, outros)
            janela.escrever(f"Dicionário   : {dicionario.name}\n"
                            f"Questionários: {pasta_q.name if pasta_q else 'não fornecidos'}\n"
                            f"Caderno      : {caderno.name if caderno else 'não fornecido'}\n"
                            f"Tabelas      : {', '.join(opcoes.tabelas)}\n"
                            f"Edição       : {ano or 'não determinada'} "
                            f"(saída como {prefixo_edicao(ano)}microdados_tabela_*)")

            avancar(P_METADADOS, "Gerando os metadados...")
            resultado = gerar_metadados(
                dicionario, Path(tmp) / "saida", pasta_q, caderno, ano=ano,
                tabelas_alvo=opcoes.tabelas, gerar_html=opcoes.gerar_html,
                incluir_questionarios=opcoes.incluir_questionarios,
            )
            avancar(P_EMPACOTE, "Empacotando os metadados...")
            zip_bytes = empacotar(resultado)
    except Exception as exc:
        detalhe = explicar_erro(exc)
        janela.escrever(f"ERRO: {detalhe}\n{traceback.format_exc()}")
        st.error(f"**Processamento falhou.**\n\n{detalhe}")
        st.stop()
    finally:
        remover_saida(janela)

    st.session_state.resultado = ResultadoApp(
        zip_bytes=zip_bytes, n_json=len(resultado.jsons),
        tem_censo_html=resultado.censo_html is not None,
        duracao=time.monotonic() - inicio,
        avisos=avisos_de_lacunas(ano, caderno is not None, pasta_q is not None),
    )
    st.session_state.assinatura = assinatura_atual
    avancar(100, "Concluído!")
    st.rerun()


def mostrar_resultado() -> None:
    resultado: ResultadoApp | None = st.session_state.resultado
    if resultado is None:
        return
    st.success(mensagem_sucesso(resultado))
    for aviso in resultado.avisos:
        st.warning(aviso)
    st.download_button("Baixar metadados (ZIP)", data=resultado.zip_bytes,
                       file_name=NOME_PACOTE, mime="application/zip")
    if st.button("Processar novo arquivo"):
        st.session_state.resultado = None
        st.session_state.assinatura = None
        st.rerun()


# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title="Censo Escolar — Gerador de metadados", page_icon="📊",
                       layout="centered")
    st.title("Censo Escolar — Gerador de metadados")
    st.markdown("Gera os `.json` de importação do **World Bank Metadata Editor**, o `censo.html` "
                "navegável e o relatório de casamento. **O único insumo obrigatório é o dicionário "
                "de variáveis** — os microdados não são lidos.")
    st.session_state.setdefault("resultado", None)
    st.session_state.setdefault("assinatura", None)

    entradas = coletar_entradas()
    if entradas.dicionario_bytes is None:
        st.info("Aguardando o dicionário de variáveis (.xlsx).")
        st.stop()
    tabelas = escolher_tabelas(entradas.dicionario_bytes)
    opcoes = escolher_opcoes(entradas, tabelas)
    painel_cobertura(entradas)

    # Mudar arquivo ou opção descarta o resultado anterior.
    assinatura_atual = assinatura(entradas.uploads, (
        entradas.modo, opcoes.gerar_html, opcoes.incluir_questionarios,
        entradas.usar_caderno, entradas.usar_questionarios, tuple(sorted(opcoes.tabelas))))
    if assinatura_atual != st.session_state.assinatura:
        st.session_state.resultado = None

    validar(entradas, opcoes)
    ja_processado = st.session_state.resultado is not None
    if ja_processado:
        st.caption("Resultado já gerado abaixo — use **Processar novo arquivo** para recomeçar.")
    if st.button("Processar", type="primary", disabled=ja_processado):
        processar(entradas, opcoes, assinatura_atual)
    mostrar_resultado()


main()
