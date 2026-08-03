#!/usr/bin/env python3
"""app.py — Interface Streamlit para o pipeline do Censo Escolar."""
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

from censo_lib import ROTULO_TABELA, TABELAS, identificar_tabela

MODO_ZIP      = "ZIP oficial do INEP"
MODO_ARQUIVOS = "Arquivos separados"

MODO_COLUNAS_TODAS      = "Todas as variáveis do dicionário"
MODO_COLUNAS_DISPONIVEL = "Apenas as colunas presentes no CSV"

LOG_MAX = 50  # linhas mantidas visíveis na janela de log

# Faixas da barra de progresso. O passo 3 (popular .sav) é o mais demorado e
# por isso fica com a maior fatia — antes todos os passos tinham peso parecido
# e a barra parecia travar em 65%.
P_ENTRADAS, P_PASSO1, P_PASSO2, P_PASSO3 = 5, 40, 50, 92

# ---------------------------------------------------------------------------
# Configuração da página
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Censo Escolar — Gerador de SAV",
    page_icon="📊",
    layout="centered",
)

st.title("Censo Escolar — Gerador de .sav")

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

    O nome importa: a identificação de tabela e de questionário é feita pelo
    nome do arquivo (ver censo_lib.identificar_tabela / localizar_questionario).
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
        return (f"Campo esperado ausente: {exc}. Verifique se o dicionário e os "
                "CSVs são da mesma edição do Censo.")
    if isinstance(exc, UnicodeDecodeError):
        return ("Não foi possível ler o texto de um arquivo (codificação não "
                "reconhecida). Salve o CSV em UTF-8 e tente novamente.")
    if isinstance(exc, MemoryError):
        return ("Memória insuficiente para as tabelas selecionadas. Processe "
                "menos tabelas por vez — matrícula e docente são as maiores.")
    if isinstance(exc, FileNotFoundError):
        return f"Arquivo esperado não encontrado: {exc.filename or exc}"
    if isinstance(exc, PermissionError):
        return f"Sem permissão de acesso ao arquivo: {exc.filename or exc}"
    if type(exc).__name__ == "ParserError":  # pandas — evita importar aqui
        return (f"CSV malformado e não pôde ser lido: {exc}. Confira o "
                "delimitador e se o arquivo não foi truncado.")
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

    def basename(n: str) -> str:
        return Path(n).name.lower()

    dicionario = next(
        (n for n in nomes
         if n.lower().endswith(".xlsx")
         and not Path(n).name.startswith("~$")
         and "dicion" in basename(n)),
        None,
    )
    caderno = next(
        (n for n in nomes
         if n.lower().endswith(".pdf")
         and "caderno" in basename(n) and "conceito" in basename(n)),
        None,
    )
    questionarios = [
        n for n in nomes
        if n.lower().endswith(".pdf")
        and any("question" in parte.lower() for parte in Path(n).parts[:-1])
    ]
    tabelas: dict[str, str] = {}
    for n in nomes:
        if not n.lower().endswith(".csv"):
            continue
        tabela = identificar_tabela(Path(n).name)
        if tabela and tabela not in tabelas:
            tabelas[tabela] = Path(n).name
    return {
        "dicionario": dicionario,
        "caderno": caderno,
        "questionarios": questionarios,
        "tabelas": tabelas,
    }


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


# ---------------------------------------------------------------------------
# Escolha do modo de entrada
# ---------------------------------------------------------------------------
modo_entrada = st.radio(
    "Forma de envio dos insumos",
    [MODO_ZIP, MODO_ARQUIVOS],
    horizontal=True,
    help="O ZIP oficial traz tudo junto. O modo por arquivos permite combinar "
         "insumos de origens/anos diferentes — por exemplo, dicionário e tabelas "
         "novos com o Caderno e os questionários já em mãos.",
)

limite_mb = st.get_option("server.maxUploadSize")
st.caption(f"Limite de upload por arquivo: **{limite_mb} MB**.")

arquivo_zip = None
dicionario_up = caderno_up = None
csvs_up: list = []
questionarios_up: list = []
tabelas_selecionadas: list[str] = []
uploads: list = []
usar_caderno = usar_questionarios = True
info_zip: dict | None = None

if modo_entrada == MODO_ZIP:
    st.markdown(
        "Envie o arquivo **.zip** oficial do INEP com os microdados do Censo Escolar. "
        "O pipeline gera os arquivos **.sav** prontos para uso no SPSS/Stata."
    )
    arquivo_zip = st.file_uploader(
        "Arquivo .zip dos microdados",
        type="zip",
        help="Arquivo baixado do site do INEP — estrutura padrão com Anexos/ e dados/.",
    )
    uploads = [arquivo_zip]

    tabelas_opcoes = list(TABELAS.keys())
    if arquivo_zip is not None:
        info_zip = inspecionar_zip(arquivo_zip)
        if info_zip is None:
            st.error("O .zip não pôde ser lido — arquivo corrompido ou incompleto.")
            st.stop()
        if not info_zip["dicionario"]:
            st.error(
                "Nenhum dicionário `.xlsx` encontrado dentro do zip. O arquivo deve "
                "ter 'dicion' no nome (ex: `dicionario_dados_censo_escolar.xlsx`)."
            )
            st.stop()
        if info_zip["tabelas"]:
            # Restringe as opções ao que existe de fato no zip: oferecer uma
            # tabela sem CSV só produziria um .sav vazio ao final.
            tabelas_opcoes = list(info_zip["tabelas"])
        else:
            st.warning(
                "Nenhum CSV no padrão `Tabela_<Nome>_<ano>.csv` foi reconhecido "
                "dentro do zip. As tabelas abaixo são as do dicionário — os .sav "
                "podem sair vazios."
            )
        usar_caderno = info_zip["caderno"] is not None
        usar_questionarios = bool(info_zip["questionarios"])

        with st.expander("Conteúdo identificado no zip", expanded=False):
            st.markdown(
                f"- **Dicionário:** `{Path(info_zip['dicionario']).name}`\n"
                f"- **Tabelas (CSV):** "
                + (", ".join(f"`{n}`" for n in info_zip["tabelas"].values()) or "_nenhuma_")
                + "\n- **Caderno de Conceitos:** "
                + (f"`{Path(info_zip['caderno']).name}`" if usar_caderno else "_não encontrado_")
                + f"\n- **Questionários:** {len(info_zip['questionarios'])} PDF(s)"
            )

    # A seleção vive em session_state (e não em `default=`) para que os botões
    # abaixo possam alterá-la. Como as opções encolhem quando o zip é lido,
    # a seleção guardada é filtrada para nunca conter uma tabela fora da lista.
    if "tabelas_zip" not in st.session_state:
        st.session_state.tabelas_zip = list(tabelas_opcoes)
    else:
        valida = [t for t in st.session_state.tabelas_zip if t in tabelas_opcoes]
        if valida != list(st.session_state.tabelas_zip):
            st.session_state.tabelas_zip = valida

    st.markdown("**Tabelas a processar**")
    col_todas, col_limpar, _ = st.columns([1, 1, 2])
    if col_todas.button("Selecionar todas", use_container_width=True):
        st.session_state.tabelas_zip = list(tabelas_opcoes)
        st.rerun()
    if col_limpar.button("Limpar seleção", use_container_width=True):
        st.session_state.tabelas_zip = []
        st.rerun()

    tabelas_selecionadas = st.multiselect(
        "Tabelas a processar",
        options=tabelas_opcoes,
        key="tabelas_zip",
        label_visibility="collapsed",
        format_func=lambda t: ROTULO_TABELA.get(t, t),
        help="Desmarque tabelas grandes (ex: matrícula, docente) para execução mais rápida.",
    )
else:
    st.markdown(
        "Envie cada insumo separadamente. **Os JSONs gerados serão apenas os das "
        "tabelas cujos CSVs você enviar.** O dicionário é obrigatório; o Caderno "
        "de Conceitos e os questionários são opcionais e apenas enriquecem os "
        "metadados."
    )

    st.subheader("Insumos obrigatórios")
    dicionario_up = st.file_uploader(
        "1. Dicionário de variáveis (.xlsx)",
        type="xlsx",
        help="Planilha com uma aba por tabela (Tabela_de_Escola, Tabela_de_Matrícula, …). "
             "Fonte dos nomes, tipos, rótulos e categorias das variáveis.",
    )
    csvs_up = st.file_uploader(
        "2. Tabelas de dados (.csv)",
        type="csv",
        accept_multiple_files=True,
        help="Um ou mais CSVs no padrão Tabela_<Nome>_<ano>.csv. Definem quais "
             "tabelas serão processadas.",
    ) or []

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
            "3. Caderno de Conceitos e Orientações (.pdf)",
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
            "4. Questionários (.pdf)",
            type="pdf",
            accept_multiple_files=True,
            help="PDFs no padrão '<Nome> <ano>.pdf' (Escola, Aluno, Turma, Gestor Escolar, "
                 "Profissional Escolar). Fonte das questões literais (var_qstn_qstnlit).",
        ) or []

    uploads = [dicionario_up, caderno_up, *csvs_up, *questionarios_up]

    # As tabelas vêm exclusivamente dos CSVs enviados.
    reconhecidos: dict[str, str] = {}
    nao_reconhecidos: list[str] = []
    for up in csvs_up:
        tabela = identificar_tabela(up.name)
        if tabela and tabela not in reconhecidos:
            reconhecidos[tabela] = up.name
        elif not tabela:
            nao_reconhecidos.append(up.name)
    tabelas_selecionadas = list(reconhecidos)

    if reconhecidos:
        st.success(
            "Tabelas identificadas: "
            + ", ".join(f"**{ROTULO_TABELA.get(t, t)}** (`{n}`)" for t, n in reconhecidos.items())
        )
    if nao_reconhecidos:
        st.warning(
            "CSV(s) não reconhecido(s) e que serão ignorados: "
            + ", ".join(f"`{n}`" for n in nao_reconhecidos)
            + ". Use o padrão `Tabela_<Nome>_<ano>.csv`."
        )

# ---------------------------------------------------------------------------
# Opções comuns
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

modo_colunas = st.radio(
    "Colunas nos arquivos .sav",
    [MODO_COLUNAS_TODAS, MODO_COLUNAS_DISPONIVEL],
    help="**Todas as variáveis**: o .sav traz toda a estrutura do dicionário e as "
         "colunas ausentes no CSV ficam vazias. **Apenas as presentes**: o .sav traz "
         "só o que existe no CSV (colunas extras entram sem metadados).",
)

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

# No modo ZIP a cobertura só é conhecida depois da varredura do arquivo.
if modo_entrada == MODO_ARQUIVOS or info_zip is not None:
    painel_cobertura(tem_caderno, tem_questionarios)

# Resetar resultado se o conjunto de arquivos OU as opções mudarem
opcoes_atuais = (modo_entrada, modo_colunas, gerar_html, incluir_questionarios,
                 usar_caderno, usar_questionarios, tuple(sorted(tabelas_selecionadas)))
assinatura_atual = assinatura(uploads, opcoes_atuais)
if any(u is not None for u in uploads) and assinatura_atual != st.session_state.assinatura_processada:
    st.session_state.resultado_zip = None

# ---------------------------------------------------------------------------
# Validação das entradas
# ---------------------------------------------------------------------------
if modo_entrada == MODO_ZIP:
    if not arquivo_zip:
        st.info("Aguardando upload do arquivo .zip.")
        st.stop()
    if not tabelas_selecionadas:
        st.warning("Selecione pelo menos uma tabela.")
        st.stop()
else:
    # Só dicionário e CSVs bloqueiam. Caderno e questionários ausentes são
    # estado válido — reduzem a cobertura, não impedem a execução.
    faltando = [
        rotulo for rotulo, ok in [
            ("dicionário (.xlsx)", dicionario_up is not None),
            ("tabelas (.csv)", bool(csvs_up)),
        ] if not ok
    ]
    if faltando:
        st.info("Aguardando: " + ", ".join(faltando) + ".")
        st.stop()
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
        st.warning(
            "Nenhum CSV enviado foi reconhecido como tabela do Censo. "
            "Renomeie para o padrão `Tabela_<Nome>_<ano>.csv`."
        )
        st.stop()

# ---------------------------------------------------------------------------
# Processamento
# ---------------------------------------------------------------------------
processar_disabled = st.session_state.resultado_zip is not None
if processar_disabled:
    st.caption(
        "Resultado já gerado abaixo — use **Processar novo arquivo** para recomeçar."
    )
elif {"matricula", "docente"} & set(tabelas_selecionadas):
    st.caption(
        "As tabelas de matrícula e docente são as maiores do Censo: a execução "
        "pode levar vários minutos."
    )

if st.button("Processar", type="primary", disabled=processar_disabled):

    inicio = time.monotonic()
    col_barra, col_cancelar = st.columns([4, 1])
    barra = col_barra.progress(0, text="Iniciando...")
    col_cancelar.button(
        "Cancelar",
        help="Interrompe no próximo ponto de verificação (entre tabelas). "
             "Nada é gravado — o processamento roda em pasta temporária.",
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
            avancar(P_ENTRADAS, "Extraindo zip...")
            log("Extraindo zip...")
            rodar_passo(
                "Extração do zip",
                lambda: zipfile.ZipFile(arquivo_zip).extractall(pasta_entrada),
            )
            log("Extração concluída.")

            # Dicionário .xlsx (ignora arquivos temporários do Excel)
            candidatos_xlsx = [
                p for p in pasta_entrada.rglob("*.xlsx")
                if not p.name.startswith("~$") and "dicion" in p.name.lower()
            ]
            if not candidatos_xlsx:
                st.error("Dicionário .xlsx não encontrado dentro do zip.")
                st.stop()
            caminho_xlsx = candidatos_xlsx[0]

            # Pasta de questionários (PDFs)
            candidatos_q = [
                p for p in pasta_entrada.rglob("*")
                if p.is_dir() and "question" in p.name.lower()
            ]
            pasta_q = candidatos_q[0] if candidatos_q else None

            # Pasta de dados (CSVs)
            candidatos_dados = [p for p in pasta_entrada.rglob("dados") if p.is_dir()]
            if not candidatos_dados:
                # fallback: pasta-mãe dos CSVs com nome padrão do INEP
                candidatos_dados = sorted({csv.parent for csv in pasta_entrada.rglob("Tabela_*.csv")})
            if not candidatos_dados:
                st.error("Pasta com os CSVs não encontrada dentro do zip.")
                st.stop()
            pasta_csv = candidatos_dados[0]

            # Caderno de Conceitos (PDF em leia-me/)
            candidatos_caderno = [
                p for p in pasta_entrada.rglob("*.pdf")
                if "caderno" in p.name.lower() and "conceito" in p.name.lower()
            ]
            caminho_caderno = candidatos_caderno[0] if candidatos_caderno else None
        else:
            avancar(P_ENTRADAS, "Gravando arquivos enviados...")
            log("Gravando arquivos enviados...")
            caminho_xlsx    = gravar_upload(dicionario_up, pasta_entrada / "dicionario")
            caminho_caderno = (gravar_upload(caderno_up, pasta_entrada / "caderno")
                               if tem_caderno else None)
            pasta_csv       = pasta_entrada / "dados"
            pasta_q         = pasta_entrada / "questionarios" if tem_questionarios else None
            for up in csvs_up:
                gravar_upload(up, pasta_csv)
            for up in (questionarios_up if tem_questionarios else []):
                gravar_upload(up, pasta_q)
            log(f"  {len(csvs_up)} CSV(s), "
                f"{len(questionarios_up) if tem_questionarios else 0} questionário(s) gravados.")

        log(f"Dicionário  : {caminho_xlsx.name}")
        log(f"Dados (CSVs): {pasta_csv.relative_to(pasta_entrada)}")
        log(f"Questionários: {pasta_q.name if pasta_q else 'não fornecidos (var_qstn ficará vazio)'}")
        log(f"Caderno     : {caminho_caderno.name if caminho_caderno else 'não fornecido (var_concept ficará vazio)'}")
        log(f"Tabelas     : {', '.join(tabelas_selecionadas)}")

        if not caminho_caderno:
            avisos.append("Caderno de Conceitos ausente — `var_concept` ficou vazio.")
        if not pasta_q:
            avisos.append("Questionários ausentes — `var_qstn_qstnlit` ficou vazio.")

        # ---- PASSO 1/3 — Gerar JSONs (dicionário + questionários + Caderno) -
        avancar(P_PASSO1, "Passo 1/3 — Gerando JSONs de metadados...")
        log("\n=== PASSO 1/3 — Gerando JSONs de metadados ===")

        def passo1():
            from gerar_json_metadata_editor import executar as gerar_jsons
            return gerar_jsons(
                caminho_xlsx, pasta_saida, pasta_q, caminho_caderno,
                gerar_html=gerar_html, incluir_questionarios=incluir_questionarios,
                tabelas_alvo=tabelas_selecionadas,
            )

        rodar_passo("Passo 1/3 — geração dos JSONs", passo1)

        # ---- PASSO 2/3 — SAV vazios -----------------------------------------
        avancar(P_PASSO2, "Passo 2/3 — Criando .sav vazios...")
        log("\n=== PASSO 2/3 — Criando .sav vazios ===")

        def passo2():
            from criar_sav_vazio import executar as criar_vazios
            return criar_vazios(tabelas_selecionadas, pasta_saida, pasta_saida)

        erros_vazio = rodar_passo("Passo 2/3 — criação dos .sav vazios", passo2)
        if erros_vazio:
            log(f"[aviso] Erros em: {', '.join(erros_vazio)}")
            avisos.append(
                "Não foi possível criar a estrutura .sav de: "
                + ", ".join(ROTULO_TABELA.get(t, t) for t in erros_vazio)
            )

        # ---- PASSO 3/3 — Popular SAV ----------------------------------------
        # Passo mais lento: a barra acompanha tabela a tabela.
        avancar(P_PASSO2, "Passo 3/3 — Populando .sav com dados...")
        log("\n=== PASSO 3/3 — Populando .sav com dados ===")

        def progresso_pop(i: int, total: int, nome: str) -> None:
            pct = P_PASSO2 + int((P_PASSO3 - P_PASSO2) * (i / max(total, 1)))
            avancar(pct, f"Passo 3/3 — {ROTULO_TABELA.get(nome, nome)} ({i + 1}/{total})")

        def passo3():
            from popular_sav import executar as popular
            return popular(
                tabelas_selecionadas, pasta_csv, pasta_saida,
                modo=1 if modo_colunas == MODO_COLUNAS_TODAS else 2,
                progresso=progresso_pop,
            )

        erros_pop = rodar_passo("Passo 3/3 — população dos .sav", passo3)
        if erros_pop:
            log(f"[aviso] Erros em: {', '.join(erros_pop)}")
            avisos.append(
                "Não foi possível popular com dados: "
                + ", ".join(ROTULO_TABELA.get(t, t) for t in erros_pop)
            )

        # ---- Empacotar .sav para download ------------------------------------
        avancar(95, "Empacotando arquivos .sav e .json...")
        log("\n=== Empacotando .sav e .json para download ===")
        arquivos_sav  = sorted(pasta_saida.glob("*.sav"))
        # Só os JSONs de importação das tabelas processadas — os caches
        # intermediários do Caderno ficam de fora do pacote.
        arquivos_json = sorted(pasta_saida.glob("*_import_metadata_editor.json"))
        caminho_censo_html = pasta_saida / "censo.html"
        caminho_relatorio = pasta_saida / "relatorio_casamento.csv"
        if not arquivos_sav:
            st.error(
                "Nenhum arquivo .sav foi gerado. Verifique no log acima se os CSVs "
                "correspondem às tabelas do dicionário."
            )
            st.stop()

        zip_out = io.BytesIO()
        with zipfile.ZipFile(zip_out, "w", zipfile.ZIP_DEFLATED) as zout:
            for sav in arquivos_sav:
                zout.write(sav, f"sav/{sav.name}")
                log(f"  + sav/{sav.name}")
            for js in arquivos_json:
                zout.write(js, f"json/{js.name}")
                log(f"  + json/{js.name}")
            if caminho_censo_html.is_file():
                zout.write(caminho_censo_html, "censo.html")
                log("  + censo.html")
            if caminho_relatorio.is_file():
                zout.write(caminho_relatorio, "relatorio_casamento.csv")
                log("  + relatorio_casamento.csv")
        zip_out.seek(0)

        st.session_state.resultado_zip = zip_out.getvalue()
        st.session_state.assinatura_processada = assinatura_atual
        st.session_state.avisos = avisos
        st.session_state.duracao = time.monotonic() - inicio

        avancar(100, "Concluído!")
        log(f"\nConcluído! {len(arquivos_sav)} .sav + {len(arquivos_json)} .json gerado(s)"
            f"{' + censo.html' if caminho_censo_html.is_file() else ''}.")

    st.rerun()

# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
if st.session_state.resultado_zip:
    nomes = zipfile.ZipFile(io.BytesIO(st.session_state.resultado_zip)).namelist()
    n_sav  = sum(1 for n in nomes if n.endswith(".sav"))
    n_json = sum(1 for n in nomes if n.endswith(".json"))
    tem_censo_html = "censo.html" in nomes
    msg = f"Pipeline concluído — {n_sav} .sav + {n_json} .json"
    msg += " + censo.html" if tem_censo_html else ""
    if st.session_state.duracao:
        segundos = int(st.session_state.duracao)
        msg += f" gerado(s) em {segundos // 60}m{segundos % 60:02d}s."
    else:
        msg += " gerado(s)."
    st.success(msg)

    # Falhas parciais e lacunas de metadados: visíveis mesmo depois que o log
    # rolou, para ninguém sair achando que a execução foi 100% completa.
    for aviso in st.session_state.avisos:
        st.warning(aviso)

    st.download_button(
        label="Baixar .sav (ZIP)",
        data=st.session_state.resultado_zip,
        file_name="censo_escolar_sav.zip",
        mime="application/zip",
    )
    if st.button("Processar novo arquivo"):
        st.session_state.resultado_zip = None
        st.session_state.assinatura_processada = None
        st.session_state.avisos = []
        st.session_state.duracao = None
        st.rerun()
