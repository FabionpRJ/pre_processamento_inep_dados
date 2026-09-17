#!/usr/bin/env python3
"""app.py — Interface Streamlit para o gerador de metadados do Censo Escolar."""
import io
import sys
import tempfile
import time
import traceback
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

import streamlit as st

# Garante que os módulos do projeto sejam importáveis ao rodar de outro diretório
PROJECT_DIR = Path(__file__).parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from censo_lib import (
    ROTULO_TABELA,
    classificar_nomes, detectar_ano_censo, localizar_insumos, prefixo_edicao,
    tabelas_do_dicionario,
)

MODO_ZIP      = "ZIP oficial do INEP"
MODO_ARQUIVOS = "Arquivos separados"

# Extensões dos insumos de metadados. Só elas saem do zip: os CSVs de
# microdados não são lidos pelo pipeline (ver `extrair_insumos_zip`).
EXT_INSUMOS = (".xlsx", ".xls", ".pdf")

LOG_MAX = 50  # linhas mantidas visíveis na janela de log

# Faixas da barra de progresso. A geração dos metadados é praticamente todo o
# trabalho — leitura do dicionário, dos PDFs e o casamento por similaridade.
P_ENTRADAS, P_PASSO1, P_EMPACOTE = 10, 90, 95

# ---------------------------------------------------------------------------
# Configuração da página
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Censo Escolar — Gerador de metadados",
    page_icon="📊",
    layout="centered",
)

st.title("Censo Escolar — Gerador de metadados")
st.markdown(
    "Gera os `.json` de importação do **World Bank Metadata Editor**, o "
    "`censo.html` navegável e o relatório de casamento. **O único insumo "
    "obrigatório é o dicionário de variáveis** — os microdados não são lidos."
)

# ---------------------------------------------------------------------------
# Estado da sessão
# ---------------------------------------------------------------------------
st.session_state.setdefault("resultado_zip", None)
st.session_state.setdefault("assinatura_processada", None)
st.session_state.setdefault("avisos", [])       # falhas parciais do último run
st.session_state.setdefault("duracao", None)    # segundos do último run


def assinatura(uploads: list, opcoes: tuple) -> tuple:
    """Identidade da execução (arquivos + opções), para invalidar o resultado."""
    return (tuple(sorted((u.name, u.size) for u in uploads if u is not None)), opcoes)


def gravar_upload(upload, destino: Path) -> Path:
    """Materializa um upload em disco preservando o nome original.

    O nome importa: a identificação de questionário é feita pelo nome do
    arquivo (ver censo_lib.localizar_questionario), e o ano da edição é
    deduzido dos nomes dos insumos.
    """
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / Path(upload.name).name
    caminho.write_bytes(upload.getbuffer())
    return caminho


def explicar_erro(exc: BaseException) -> str:
    """Traduz falhas conhecidas em orientação acionável.

    Sem isso o usuário via só a mensagem crua da exceção (ex: `KeyError:
    'Tabela_de_Escola'`), que não diz o que corrigir.
    """
    if isinstance(exc, SystemExit):
        # Os módulos do pipeline sinalizam entrada inválida com sys.exit(msg).
        return str(exc.code) if exc.code not in (None, 0) else "Passo interrompido."
    if isinstance(exc, zipfile.BadZipFile):
        return ("O arquivo .zip está corrompido ou veio incompleto. Baixe de novo "
                "no site do INEP e refaça o upload.")
    if isinstance(exc, KeyError):
        return (f"Campo esperado ausente: {exc}. Verifique se o dicionário é de "
                "uma edição reconhecida do Censo.")
    if isinstance(exc, UnicodeDecodeError):
        return ("Não foi possível ler o texto de um arquivo (codificação não "
                "reconhecida).")
    if isinstance(exc, MemoryError):
        return ("Memória insuficiente. Processe menos tabelas por vez — "
                "matrícula e docente são as maiores.")
    if isinstance(exc, FileNotFoundError):
        return f"Arquivo esperado não encontrado: {exc.filename or exc}"
    if isinstance(exc, PermissionError):
        return f"Sem permissão de acesso ao arquivo: {exc.filename or exc}"
    return f"{type(exc).__name__}: {exc}"


def inspecionar_zip(upload) -> dict | None:
    """Prevê, só pelos nomes dentro do zip, o que o pipeline vai encontrar.

    Lê apenas o índice central do zip — não extrai nada. Os critérios são os
    mesmos usados na extração mais abaixo, para o painel de cobertura nunca
    discordar do resultado real. Devolve None se o zip estiver ilegível.
    """
    try:
        with zipfile.ZipFile(upload) as zf:
            nomes = zf.namelist()
    except zipfile.BadZipFile:
        return None
    finally:
        upload.seek(0)

    # Mesma função que a extração real usa (censo_lib.classificar_nomes), para
    # que a prévia não possa discordar do resultado.
    return classificar_nomes(nomes)


def ler_membro_zip(upload, nome: str) -> bytes | None:
    """Lê um único arquivo de dentro do zip, sem extrair o resto.

    Serve para abrir o dicionário e descobrir quais tabelas ele traz antes de
    qualquer processamento — o `.xlsx` tem alguns MB, enquanto o pacote
    inteiro tem vários GB de microdados.
    """
    try:
        with zipfile.ZipFile(upload) as zf:
            return zf.read(nome)
    except (zipfile.BadZipFile, KeyError):
        return None
    finally:
        upload.seek(0)


def extrair_insumos_zip(upload, destino: Path) -> None:
    """Extrai do zip apenas os insumos de metadados (`.xlsx`/`.xls`/`.pdf`).

    Os CSVs de microdados ficam no arquivo: o pipeline não lê mais os dados,
    e extrair tudo custaria dezenas de minutos e vários GB de disco temporário
    para produzir exatamente os mesmos metadados.
    """
    with zipfile.ZipFile(upload) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            if Path(info.filename).suffix.lower() in EXT_INSUMOS:
                zf.extract(info, destino)
    upload.seek(0)


def painel_cobertura(tem_caderno: bool, tem_questionarios: bool) -> None:
    """Mostra, ANTES de processar, quais metadados a seleção atual preenche.

    Sem esse painel o usuário só descobria que `var_concept` veio vazio ao
    abrir o resultado.
    """
    def item(ok: bool, texto: str, fonte: str) -> str:
        marca = "✅" if ok else "❌"
        sufixo = "" if ok else " — **ficará vazio**"
        return f"- {marca} {texto} — *{fonte}*{sufixo}"

    with st.container(border=True):
        st.markdown("**Cobertura de metadados com a seleção atual**")
        st.markdown(
            "\n".join([
                item(True, "nomes, tipos, rótulos e categorias", "dicionário"),
                item(tem_caderno, "conceitos e definições (`var_concept`)",
                     "Caderno de Conceitos"),
                item(tem_questionarios, "perguntas literais (`var_qstn_qstnlit`)",
                     "questionários"),
            ])
        )
        st.caption(
            "`case_count` sai **0** em todos os JSONs: o ETL não lê os microdados "
            "e portanto não conhece o número de linhas de cada tabela."
        )


# ---------------------------------------------------------------------------
# Escolha do modo de entrada
# ---------------------------------------------------------------------------
modo_entrada = st.radio(
    "Forma de envio dos insumos",
    [MODO_ZIP, MODO_ARQUIVOS],
    horizontal=True,
    help="O ZIP oficial traz tudo junto (os CSVs de microdados são ignorados). "
         "O modo por arquivos permite combinar insumos de origens/anos "
         "diferentes — por exemplo, um dicionário novo com o Caderno e os "
         "questionários já em mãos.",
)

limite_mb = st.get_option("server.maxUploadSize")
st.caption(f"Limite de upload por arquivo: **{limite_mb} MB**.")

arquivo_zip = None
dicionario_up = caderno_up = None
questionarios_up: list = []
uploads: list = []
usar_caderno = usar_questionarios = True
info_zip: dict | None = None
dicionario_bytes: bytes | None = None

if modo_entrada == MODO_ZIP:
    arquivo_zip = st.file_uploader(
        "Arquivo .zip dos microdados",
        type="zip",
        help="Arquivo baixado do site do INEP — a estrutura interna de pastas "
             "não importa; os insumos são localizados pelos próprios arquivos. "
             "Só o dicionário, o Caderno e os questionários são extraídos.",
    )
    uploads = [arquivo_zip]

    if arquivo_zip is not None:
        info_zip = inspecionar_zip(arquivo_zip)
        if info_zip is None:
            st.error("O .zip não pôde ser lido — arquivo corrompido ou incompleto.")
            st.stop()
        if not info_zip["dicionario"]:
            st.error(
                "Nenhum dicionário encontrado dentro do zip. É esperado um `.xlsx` "
                "com 'dicionário' no nome — ou, na falta dele, um único `.xlsx` "
                "no pacote."
            )
            st.stop()
        dicionario_bytes = ler_membro_zip(arquivo_zip, info_zip["dicionario"])
        usar_caderno = info_zip["caderno"] is not None
        usar_questionarios = bool(info_zip["questionarios"])

        with st.expander("Conteúdo identificado no zip", expanded=False):
            st.markdown(
                f"- **Dicionário:** `{Path(info_zip['dicionario']).name}`\n"
                + "- **Caderno de Conceitos:** "
                + (f"`{Path(info_zip['caderno']).name}`" if usar_caderno else "_não encontrado_")
                + f"\n- **Questionários:** {len(info_zip['questionarios'])} PDF(s)"
                + (f"\n- **CSVs de microdados:** {len(info_zip['csvs'])} — "
                   "**ignorados**, o pipeline não lê os dados."
                   if info_zip["csvs"] else "")
            )
else:
    st.subheader("Insumo obrigatório")
    dicionario_up = st.file_uploader(
        "1. Dicionário de variáveis (.xlsx)",
        type="xlsx",
        help="Planilha com uma aba por tabela (Tabela_de_Escola, Tabela_de_Matrícula, …). "
             "Fonte dos nomes, tipos, rótulos e categorias das variáveis, e a "
             "única entrada obrigatória do serviço.",
    )

    st.subheader("Metadados opcionais")
    usar_caderno = st.checkbox(
        "Incluir Caderno de Conceitos",
        value=True,
        help="Preenche `var_concept` (conceitos e definições) e alimenta o "
             "glossário e os quadros de referência do censo.html. Sem ele o "
             "pipeline roda normalmente, mas esses campos ficam vazios.",
    )
    if usar_caderno:
        caderno_up = st.file_uploader(
            "2. Caderno de Conceitos e Orientações (.pdf)",
            type="pdf",
            help="Fonte dos conceitos (var_concept), definições e quadros de referência.",
        )

    usar_questionarios = st.checkbox(
        "Incluir questionários",
        value=True,
        help="Preenche `var_qstn_qstnlit` (pergunta literal de cada variável). "
             "Sem eles o pipeline roda normalmente, mas esse campo fica vazio.",
    )
    if usar_questionarios:
        questionarios_up = st.file_uploader(
            "3. Questionários (.pdf)",
            type="pdf",
            accept_multiple_files=True,
            help="PDFs no padrão '<Nome> <ano>.pdf' (Escola, Aluno, Turma, Gestor Escolar, "
                 "Profissional Escolar). Fonte das questões literais (var_qstn_qstnlit).",
        ) or []

    uploads = [dicionario_up, caderno_up, *questionarios_up]

    if dicionario_up is not None:
        dicionario_bytes = bytes(dicionario_up.getbuffer())

# ---------------------------------------------------------------------------
# Sem dicionário não há o que oferecer: ele define as tabelas e todo o resto.
# ---------------------------------------------------------------------------
if dicionario_bytes is None:
    st.info("Aguardando o dicionário de variáveis (.xlsx).")
    st.stop()

# ---------------------------------------------------------------------------
# Recorte por tabela — as opções vêm das abas do dicionário
# ---------------------------------------------------------------------------
tabelas_opcoes = tabelas_do_dicionario(dicionario_bytes)
if not tabelas_opcoes:
    st.error(
        "Nenhuma aba do arquivo foi reconhecida como tabela do Censo. Confira se "
        "o `.xlsx` enviado é mesmo o Dicionário de Variáveis do INEP (abas no "
        "padrão `Tabela_de_Escola`, `Tabela_de_Matrícula`, …)."
    )
    st.stop()

# A seleção vive em session_state (e não em `default=`) para que os botões
# abaixo possam alterá-la. Como as opções mudam quando outro dicionário é
# enviado, a seleção guardada é filtrada para nunca conter uma tabela fora
# da lista.
if "tabelas" not in st.session_state:
    st.session_state.tabelas = list(tabelas_opcoes)
else:
    valida = [t for t in st.session_state.tabelas if t in tabelas_opcoes]
    if valida != list(st.session_state.tabelas):
        st.session_state.tabelas = valida

st.subheader("Tabelas a processar")
col_todas, col_limpar, _ = st.columns([1, 1, 2])
if col_todas.button("Selecionar todas", use_container_width=True):
    st.session_state.tabelas = list(tabelas_opcoes)
    st.rerun()
if col_limpar.button("Limpar seleção", use_container_width=True):
    st.session_state.tabelas = []
    st.rerun()

tabelas_selecionadas = st.multiselect(
    "Tabelas a processar",
    options=tabelas_opcoes,
    key="tabelas",
    label_visibility="collapsed",
    format_func=lambda t: ROTULO_TABELA.get(t, t),
    help="Um JSON de importação por tabela marcada. O dicionário é lido por "
         "inteiro de qualquer forma — o recorte afeta só os JSONs gerados.",
)

# ---------------------------------------------------------------------------
# Opções de saída
# ---------------------------------------------------------------------------
st.subheader("Opções de saída")

# Cobertura efetiva: o insumo foi pedido E existe de fato.
if modo_entrada == MODO_ZIP:
    # No modo ZIP a cobertura é o que a varredura encontrou dentro do arquivo.
    tem_caderno       = bool(info_zip and info_zip["caderno"])
    tem_questionarios = bool(info_zip and info_zip["questionarios"])
else:
    tem_caderno       = usar_caderno and caderno_up is not None
    tem_questionarios = usar_questionarios and bool(questionarios_up)

gerar_html = st.checkbox(
    "Gerar censo.html (dicionário + Caderno de Conceitos + questionários)",
    value=True,
    help="Arquivo HTML autocontido com o dicionário de variáveis das tabelas "
         "processadas, o glossário de conceitos e os quadros de referência do Censo.",
)

incluir_questionarios = st.checkbox(
    "Incluir questionários (PDF) no censo.html",
    value=True,
    disabled=not (gerar_html and tem_questionarios),
    help="Adiciona uma aba com as perguntas numeradas extraídas dos questionários em PDF."
         if tem_questionarios else
         "Indisponível: nenhum questionário foi fornecido.",
)
# Trava o valor efetivo — sem questionário não há aba a gerar, e deixar a flag
# ligada faria o painel de cobertura discordar do censo.html produzido.
incluir_questionarios = bool(incluir_questionarios and gerar_html and tem_questionarios)

painel_cobertura(tem_caderno, tem_questionarios)

# Resetar resultado se o conjunto de arquivos OU as opções mudarem
opcoes_atuais = (modo_entrada, gerar_html, incluir_questionarios,
                 usar_caderno, usar_questionarios, tuple(sorted(tabelas_selecionadas)))
assinatura_atual = assinatura(uploads, opcoes_atuais)
if any(u is not None for u in uploads) and assinatura_atual != st.session_state.assinatura_processada:
    st.session_state.resultado_zip = None

# ---------------------------------------------------------------------------
# Validação das entradas
# ---------------------------------------------------------------------------
if modo_entrada == MODO_ARQUIVOS:
    # Opção marcada mas arquivo não enviado é ambíguo: exigir a decisão.
    pendentes = [
        rotulo for rotulo, pendente in [
            ("Caderno de Conceitos (.pdf)", usar_caderno and caderno_up is None),
            ("questionários (.pdf)", usar_questionarios and not questionarios_up),
        ] if pendente
    ]
    if pendentes:
        st.info(
            "Aguardando: " + ", ".join(pendentes)
            + ". Envie o(s) arquivo(s) ou desmarque a opção correspondente."
        )
        st.stop()

if not tabelas_selecionadas:
    st.warning("Selecione pelo menos uma tabela.")
    st.stop()

# ---------------------------------------------------------------------------
# Processamento
# ---------------------------------------------------------------------------
processar_disabled = st.session_state.resultado_zip is not None
if processar_disabled:
    st.caption(
        "Resultado já gerado abaixo — use **Processar novo arquivo** para recomeçar."
    )

if st.button("Processar", type="primary", disabled=processar_disabled):

    inicio = time.monotonic()
    col_barra, col_cancelar = st.columns([4, 1])
    barra = col_barra.progress(0, text="Iniciando...")
    col_cancelar.button(
        "Cancelar",
        help="Interrompe no próximo ponto de verificação. Nada é gravado — o "
             "processamento roda em pasta temporária.",
    )
    log_container = st.empty()
    log_lines: list[str] = []

    def log(msg: str) -> None:
        log_lines.append(msg)
        visiveis = log_lines[-LOG_MAX:]
        omitidas = len(log_lines) - len(visiveis)
        cabecalho = [f"… ({omitidas} linha(s) anterior(es) omitida(s))"] if omitidas else []
        log_container.code("\n".join(cabecalho + visiveis), language="text")

    def avancar(pct: int, texto: str) -> None:
        decorrido = int(time.monotonic() - inicio)
        barra.progress(pct, text=f"{texto}  ·  {decorrido // 60}m{decorrido % 60:02d}s")

    def rodar_passo(rotulo: str, funcao):
        """Executa uma etapa capturando stdout e traduzindo eventuais falhas.

        Só intercepta Exception e SystemExit (os módulos sinalizam entrada
        inválida com sys.exit) — RerunException/StopException do Streamlit
        continuam propagando, que é o que permite o botão Cancelar funcionar.
        """
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                resultado = funcao()
        except (Exception, SystemExit) as exc:
            for linha in buf.getvalue().splitlines():
                log(linha)
            detalhe = explicar_erro(exc)
            log(f"ERRO em {rotulo}: {detalhe}")
            for linha in traceback.format_exc().splitlines():
                log(f"  {linha}")
            st.error(f"**{rotulo} falhou.**\n\n{detalhe}")
            st.stop()
        for linha in buf.getvalue().splitlines():
            log(linha)
        return resultado

    avisos: list[str] = []

    with tempfile.TemporaryDirectory() as tmp_base:
        tmp = Path(tmp_base)
        pasta_entrada = tmp / "entrada"
        pasta_saida   = tmp / "saida"
        pasta_entrada.mkdir()
        pasta_saida.mkdir()

        # ---- 1. Materializar as entradas ------------------------------------
        if modo_entrada == MODO_ZIP:
            avancar(P_ENTRADAS, "Extraindo os insumos do zip...")
            log("Extraindo do zip apenas dicionário, Caderno e questionários...")
            rodar_passo(
                "Extração do zip",
                lambda: extrair_insumos_zip(arquivo_zip, pasta_entrada),
            )
            log("Extração concluída (CSVs de microdados não extraídos).")

            # Localização dos insumos. Nada aqui depende do nome das PASTAS do
            # INEP (que já mudou de "Anexos/ANEXO I - Dicionário de Dados" para
            # "dicionario de dados"): as pastas são deduzidas de onde os
            # arquivos reconhecidos caíram. Ver censo_lib §5.
            insumos = rodar_passo(
                "Identificação dos insumos",
                lambda: localizar_insumos(pasta_entrada),
            )
            caminho_xlsx    = insumos["dicionario"]
            pasta_q         = insumos["pasta_questionarios"]
            caminho_caderno = insumos["caderno"]

            if caminho_xlsx is None:
                st.error("Dicionário .xlsx não encontrado dentro do zip.")
                st.stop()
        else:
            avancar(P_ENTRADAS, "Gravando arquivos enviados...")
            log("Gravando arquivos enviados...")
            caminho_xlsx    = gravar_upload(dicionario_up, pasta_entrada / "dicionario")
            caminho_caderno = (gravar_upload(caderno_up, pasta_entrada / "caderno")
                               if tem_caderno else None)
            pasta_q         = pasta_entrada / "questionarios" if tem_questionarios else None
            for up in (questionarios_up if tem_questionarios else []):
                gravar_upload(up, pasta_q)
            log(f"  {len(questionarios_up) if tem_questionarios else 0} questionário(s) gravados.")

        log(f"Dicionário   : {caminho_xlsx.name}")
        log(f"Questionários: {pasta_q.name if pasta_q else 'não fornecidos (var_qstn ficará vazio)'}")
        log(f"Caderno      : {caminho_caderno.name if caminho_caderno else 'não fornecido (var_concept ficará vazio)'}")
        log(f"Tabelas      : {', '.join(tabelas_selecionadas)}")

        # ---- Edição (ano) — nomeia toda a saída ------------------------------
        # Sem os microdados não há `NU_ANO_CENSO` a consultar: o ano vem dos
        # NOMES dos insumos. Ver censo_lib §5 e DOCUMENTACAO §4.0.
        #
        # O dicionário decide sozinho, e só na falta de ano no nome dele os
        # demais insumos entram. `detectar_ano_censo` resolve empate por
        # maioria: combinando um dicionário de 2026 com o Caderno e os cinco
        # questionários de 2025 (§5.7), os seis nomes antigos venceriam o
        # único novo e a saída sairia carimbada com o ano errado. Enquanto os
        # CSVs eram lidos, `NU_ANO_CENSO` desempatava isso.
        outros_nomes: list = [caminho_caderno]
        if pasta_q:
            outros_nomes += sorted(pasta_q.glob("*.pdf"))
        if modo_entrada == MODO_ZIP:
            outros_nomes.append(Path(arquivo_zip.name))

        ano_edicao = rodar_passo(
            "Detecção do ano da edição",
            lambda: (detectar_ano_censo(nomes_extra=[caminho_xlsx])
                     or detectar_ano_censo(nomes_extra=outros_nomes)),
        )
        if ano_edicao:
            log(f"Edição       : {ano_edicao} "
                f"(saída como {prefixo_edicao(ano_edicao)}microdados_tabela_*)")
        else:
            log(f"Edição       : não determinada — saída sem ano "
                f"({prefixo_edicao(None)}microdados_tabela_*)")
            avisos.append(
                "Ano da edição não determinado (nenhum insumo traz o ano no nome) "
                "— os arquivos saíram como "
                f"`{prefixo_edicao(None)}microdados_tabela_*`. Renomeie o "
                "dicionário incluindo o ano para corrigir."
            )

        if not caminho_caderno:
            avisos.append("Caderno de Conceitos ausente — `var_concept` ficou vazio.")
        if not pasta_q:
            avisos.append("Questionários ausentes — `var_qstn_qstnlit` ficou vazio.")

        # ---- Geração dos metadados -------------------------------------------
        avancar(P_PASSO1, "Gerando os metadados...")
        log("\n=== Gerando JSONs de metadados ===")

        def gerar():
            from gerar_json_metadata_editor import executar as gerar_jsons
            return gerar_jsons(
                caminho_xlsx, pasta_saida, pasta_q, caminho_caderno,
                gerar_html=gerar_html, incluir_questionarios=incluir_questionarios,
                tabelas_alvo=tabelas_selecionadas, ano=ano_edicao,
            )

        rodar_passo("Geração dos metadados", gerar)

        # ---- Empacotar para download -----------------------------------------
        avancar(P_EMPACOTE, "Empacotando os metadados...")
        log("\n=== Empacotando os metadados para download ===")
        # Só os JSONs de importação das tabelas processadas — os caches
        # intermediários do Caderno ficam de fora do pacote.
        arquivos_json = sorted(pasta_saida.glob("*_import_metadata_editor.json"))
        caminho_censo_html = pasta_saida / f"{prefixo_edicao(ano_edicao)}censo.html"
        caminho_relatorio = pasta_saida / f"{prefixo_edicao(ano_edicao)}relatorio_casamento.csv"
        if not arquivos_json:
            st.error(
                "Nenhum JSON de metadados foi gerado. Verifique no log acima se as "
                "abas do dicionário correspondem às tabelas selecionadas."
            )
            st.stop()

        zip_out = io.BytesIO()
        with zipfile.ZipFile(zip_out, "w", zipfile.ZIP_DEFLATED) as zout:
            for js in arquivos_json:
                zout.write(js, f"json/{js.name}")
                log(f"  + json/{js.name}")
            if caminho_censo_html.is_file():
                zout.write(caminho_censo_html, caminho_censo_html.name)
                log(f"  + {caminho_censo_html.name}")
            if caminho_relatorio.is_file():
                zout.write(caminho_relatorio, caminho_relatorio.name)
                log(f"  + {caminho_relatorio.name}")
        zip_out.seek(0)

        st.session_state.resultado_zip = zip_out.getvalue()
        st.session_state.assinatura_processada = assinatura_atual
        st.session_state.avisos = avisos
        st.session_state.duracao = time.monotonic() - inicio

        avancar(100, "Concluído!")
        log(f"\nConcluído! {len(arquivos_json)} .json gerado(s)"
            f"{' + ' + caminho_censo_html.name if caminho_censo_html.is_file() else ''}.")

    st.rerun()

# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
if st.session_state.resultado_zip:
    nomes = zipfile.ZipFile(io.BytesIO(st.session_state.resultado_zip)).namelist()
    n_json = sum(1 for n in nomes if n.endswith(".json"))
    tem_censo_html = any(n.endswith("censo.html") for n in nomes)
    msg = f"Metadados gerados — {n_json} .json"
    msg += " + censo.html" if tem_censo_html else ""
    if st.session_state.duracao:
        segundos = int(st.session_state.duracao)
        msg += f" em {segundos // 60}m{segundos % 60:02d}s."
    else:
        msg += "."
    st.success(msg)

    # Falhas parciais e lacunas de metadados: visíveis mesmo depois que o log
    # rolou, para ninguém sair achando que a execução foi 100% completa.
    for aviso in st.session_state.avisos:
        st.warning(aviso)

    st.download_button(
        label="Baixar metadados (ZIP)",
        data=st.session_state.resultado_zip,
        file_name="censo_escolar_metadados.zip",
        mime="application/zip",
    )
    if st.button("Processar novo arquivo"):
        st.session_state.resultado_zip = None
        st.session_state.assinatura_processada = None
        st.session_state.avisos = []
        st.session_state.duracao = None
        st.rerun()
