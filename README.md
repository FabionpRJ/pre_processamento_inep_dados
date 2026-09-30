# ETL do Censo Escolar

Transforma os insumos oficiais do INEP nos metadados consumidos pelo
**World Bank Metadata Editor**.

```
dicionário .xlsx  (obrigatório) ─┐
Caderno de Conceitos .pdf (opc.) ├─► ETL ─► json/ceb2025_microdados_tabela_<t>_import_metadata_editor.json
questionários .pdf (opcionais)  ─┘          ceb2025_censo.html          (glossário navegável)
                                            ceb2025_relatorio_casamento.csv  (auditoria)
```

- **Só o dicionário de variáveis é obrigatório.** Caderno e questionários
  preenchem `var_concept`, `var_txt` e `var_qstn_qstnlit`; sem eles, esses
  campos ficam vazios.
- **Os microdados não são lidos.** Do ZIP oficial só saem o dicionário e os
  PDFs; por isso `case_count` sai 0.
- A saída segue a convenção do INEP (`ceb2025_…`), qualquer que seja o formato
  do insumo. O ano vem do nome do dicionário (ou, na falta, dos demais insumos);
  sem ano, sai `ceb_…` com aviso.
- **Revise o relatório de casamento antes de publicar**: boa parte dos
  metadados semânticos vem de casamento por similaridade.

## Instalação

Python 3.13.

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt          # requirements-dev.txt para testes
```

## Uso

```bash
streamlit run app.py
```

A interface aceita o ZIP oficial do INEP ou os arquivos separados (útil para
combinar um dicionário novo com o Caderno e os questionários de um ano
anterior), mostra antes de processar quais campos serão preenchidos e devolve
um `.zip` com os metadados.

Pela linha de comando:

```bash
python -m censo_etl gerar dicionario.xlsx pasta_saida pasta_questionarios caderno.pdf
python -m censo_etl criar-sav-vazio pasta_json            # .sav vazios (fora do serviço)
python -m censo_etl popular-sav pasta_csv pasta_json      # .sav com dados; regrava case_count
```

## Testes

```bash
pytest            # ~1 s
pytest -m lento   # paridade com a saída de referência (precisa de exemplo_input/)
```

## Estrutura

```
app.py                     interface Streamlit
censo_etl/
  pipeline.py              orquestração: gerar_metadados(...) -> ResultadoExecucao
  tabelas.py               as seis tabelas do Censo
  nomes.py, insumos.py     identificação de arquivos e abas; pacote zip
  edicao.py                ano da edição e nomes de saída
  dicionario.py            leitura do dicionário .xlsx
  valores_especiais.py     códigos que não são categoria (88888, 9, …)
  pdf/                     questionários e Caderno de Conceitos
  casamento.py             similaridade entre variáveis e textos dos PDFs
  metadata_editor.py       JSON de importação
  relatorio.py, censo_html.py, cache.py, formato.py
  servico.py               lógica da interface independente do Streamlit
  sav/                     ferramentas standalone de .sav
  cli.py                   python -m censo_etl
tests/                     pytest
docs/                      documentação
```

## Documentação

- [docs/especificacao.md](docs/especificacao.md) — entradas, saídas e a regra
  de cada campo.
- [docs/identificacao.md](docs/identificacao.md) — como os insumos são
  reconhecidos e o que mexer quando o INEP mudar a convenção.
- [docs/decisoes.md](docs/decisoes.md) — decisões de domínio (inclusive as
  pendentes de validação).
- [docs/operacao.md](docs/operacao.md) — comandos, testes, bytes vs.
  caracteres no SPSS e pontos de atenção.
- [docs/historico.md](docs/historico.md) — cada mudança, com diagnóstico e
  números medidos.
