#!/usr/bin/env python3
"""app.py — Interface Streamlit para o pipeline do Censo Escolar 2025."""
import io
import sys
import tempfile
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

import streamlit as st

# Garante que os módulos do projeto sejam importáveis ao rodar de outro diretório
PROJECT_DIR = Path(__file__).parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from censo_lib import TABELAS

# ---------------------------------------------------------------------------
# Configuração da página
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Censo Escolar 2025 — Gerador de SAV",
    page_icon="📊",
    layout="centered",
)

st.title("Censo Escolar 2025 — Gerador de .sav")
st.markdown(
    "Envie o arquivo **.zip** oficial do INEP com os microdados do Censo Escolar. "
    "O pipeline gera os arquivos **.sav** prontos para uso no SPSS/Stata."
)

# ---------------------------------------------------------------------------
# Estado da sessão
# ---------------------------------------------------------------------------
if "resultado_zip" not in st.session_state:
    st.session_state.resultado_zip = None
if "arquivo_processado" not in st.session_state:
    st.session_state.arquivo_processado = None

# ---------------------------------------------------------------------------
# Controles de entrada
# ---------------------------------------------------------------------------
arquivo_zip = st.file_uploader(
    "Arquivo .zip dos microdados",
    type="zip",
    help="Arquivo baixado do site do INEP — estrutura padrão com Anexos/ e dados/.",
)

tabelas_opcoes = list(TABELAS.keys())
tabelas_selecionadas = st.multiselect(
    "Tabelas a processar",
    options=tabelas_opcoes,
    default=tabelas_opcoes,
    help="Desmarque tabelas grandes (ex: matricula, docente) para execução mais rápida.",
)

# Resetar resultado se o arquivo mudar
if arquivo_zip and arquivo_zip.name != st.session_state.arquivo_processado:
    st.session_state.resultado_zip = None

if not arquivo_zip:
    st.info("Aguardando upload do arquivo .zip.")
    st.stop()

if not tabelas_selecionadas:
    st.warning("Selecione pelo menos uma tabela.")
    st.stop()

# ---------------------------------------------------------------------------
# Processamento
# ---------------------------------------------------------------------------
processar_disabled = st.session_state.resultado_zip is not None
if st.button("Processar", type="primary", disabled=processar_disabled):

    log_container = st.empty()
    barra = st.progress(0, text="Iniciando...")
    log_lines: list[str] = []

    def log(msg: str) -> None:
        log_lines.append(msg)
        log_container.code("\n".join(log_lines[-50:]), language="text")

    with tempfile.TemporaryDirectory() as tmp_base:
        tmp = Path(tmp_base)
        pasta_entrada = tmp / "entrada"
        pasta_saida   = tmp / "saida"
        pasta_entrada.mkdir()
        pasta_saida.mkdir()

        # 1. Extrair zip
        barra.progress(5, text="Extraindo zip...")
        log("Extraindo zip...")
        with zipfile.ZipFile(arquivo_zip) as zf:
            zf.extractall(pasta_entrada)
        log("Extração concluída.")

        # 2. Localizar dicionário .xlsx (ignora arquivos temporários do Excel)
        candidatos_xlsx = [
            p for p in pasta_entrada.rglob("*.xlsx")
            if not p.name.startswith("~$") and "dicion" in p.name.lower()
        ]
        if not candidatos_xlsx:
            st.error("Dicionário .xlsx não encontrado dentro do zip.")
            st.stop()
        caminho_xlsx = candidatos_xlsx[0]
        log(f"Dicionário : {caminho_xlsx.name}")

        # 3. Localizar pasta de questionários (PDFs)
        candidatos_q = [
            p for p in pasta_entrada.rglob("*")
            if p.is_dir() and "question" in p.name.lower()
        ]
        pasta_q = candidatos_q[0] if candidatos_q else None
        log(f"Questionários: {pasta_q.name if pasta_q else 'não encontrado (var_qstn ficará vazio)'}")

        # 4. Localizar pasta de dados (CSVs)
        candidatos_dados = [p for p in pasta_entrada.rglob("dados") if p.is_dir()]
        if not candidatos_dados:
            # fallback: pasta-mãe dos CSVs com nome padrão do INEP
            candidatos_dados = sorted({csv.parent for csv in pasta_entrada.rglob("Tabela_*.csv")})
        if not candidatos_dados:
            st.error("Pasta com os CSVs não encontrada dentro do zip.")
            st.stop()
        pasta_csv = candidatos_dados[0]
        log(f"Dados (CSVs): {pasta_csv.relative_to(pasta_entrada)}")

        # 5. Localizar Caderno de Conceitos (PDF em leia-me/)
        candidatos_caderno = [
            p for p in pasta_entrada.rglob("*.pdf")
            if "caderno" in p.name.lower() and "conceito" in p.name.lower()
        ]
        caminho_caderno = candidatos_caderno[0] if candidatos_caderno else None
        log(f"Caderno    : {caminho_caderno.name if caminho_caderno else 'não encontrado'}")

        # ---- PASSO 1/3 — Gerar JSONs (dicionário + questionários + Caderno) -
        barra.progress(10, text="Passo 1/3 — Gerando JSONs de metadados...")
        log("\n=== PASSO 1/3 — Gerando JSONs de metadados ===")
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                from gerar_json_metadata_editor import executar as gerar_jsons
                gerar_jsons(caminho_xlsx, pasta_saida, pasta_q, caminho_caderno)
        except Exception as exc:
            st.error(f"Erro ao gerar JSONs: {exc}")
            log(f"ERRO: {exc}")
            st.stop()
        for line in buf.getvalue().splitlines():
            log(line)

        # ---- PASSO 2/3 — SAV vazios -----------------------------------------
        barra.progress(45, text="Passo 2/3 — Criando .sav vazios...")
        log("\n=== PASSO 2/3 — Criando .sav vazios ===")
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                from criar_sav_vazio import executar as criar_vazios
                erros_vazio = criar_vazios(tabelas_selecionadas, pasta_saida, pasta_saida)
        except Exception as exc:
            st.error(f"Erro ao criar .sav vazios: {exc}")
            log(f"ERRO: {exc}")
            st.stop()
        for line in buf.getvalue().splitlines():
            log(line)
        if erros_vazio:
            log(f"[aviso] Erros em: {', '.join(erros_vazio)}")

        # ---- PASSO 3/3 — Popular SAV ----------------------------------------
        barra.progress(65, text="Passo 3/3 — Populando .sav com dados...")
        log("\n=== PASSO 3/3 — Populando .sav com dados ===")
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                from popular_sav import executar as popular
                erros_pop = popular(tabelas_selecionadas, pasta_csv, pasta_saida, modo=1)
        except Exception as exc:
            st.error(f"Erro ao popular .sav: {exc}")
            log(f"ERRO: {exc}")
            st.stop()
        for line in buf.getvalue().splitlines():
            log(line)
        if erros_pop:
            log(f"[aviso] Erros em: {', '.join(erros_pop)}")

        # ---- Empacotar .sav para download ------------------------------------
        barra.progress(92, text="Empacotando arquivos .sav e .json...")
        log("\n=== Empacotando .sav e .json para download ===")
        arquivos_sav  = sorted(pasta_saida.glob("*.sav"))
        arquivos_json = sorted(pasta_saida.glob("*.json"))
        if not arquivos_sav:
            st.error("Nenhum arquivo .sav foi gerado.")
            st.stop()

        zip_out = io.BytesIO()
        with zipfile.ZipFile(zip_out, "w", zipfile.ZIP_DEFLATED) as zout:
            for sav in arquivos_sav:
                zout.write(sav, f"sav/{sav.name}")
                log(f"  + sav/{sav.name}")
            for js in arquivos_json:
                zout.write(js, f"json/{js.name}")
                log(f"  + json/{js.name}")
        zip_out.seek(0)

        st.session_state.resultado_zip = zip_out.getvalue()
        st.session_state.arquivo_processado = arquivo_zip.name

        barra.progress(100, text="Concluído!")
        log(f"\nConcluído! {len(arquivos_sav)} .sav + {len(arquivos_json)} .json gerado(s).")

    st.rerun()

# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
if st.session_state.resultado_zip:
    nomes = zipfile.ZipFile(io.BytesIO(st.session_state.resultado_zip)).namelist()
    n_sav  = sum(1 for n in nomes if n.endswith(".sav"))
    n_json = sum(1 for n in nomes if n.endswith(".json"))
    st.success(f"Pipeline concluído — {n_sav} .sav + {n_json} .json gerado(s).")
    st.download_button(
        label="Baixar .sav (ZIP)",
        data=st.session_state.resultado_zip,
        file_name="censo_escolar_2025_sav.zip",
        mime="application/zip",
    )
    if st.button("Processar novo arquivo"):
        st.session_state.resultado_zip = None
        st.session_state.arquivo_processado = None
        st.rerun()
