# ETL do Censo Escolar

Transforma os insumos oficiais do INEP nos artefatos consumidos pelo
**World Bank Metadata Editor**: arquivos `.sav` (SPSS/Stata) com metadados
completos, os `.json` de importação e um `censo.html` navegável.

```
                 ┌── dicionário .xlsx ──┐  (obrigatório)
insumos INEP ────┼── CSVs de dados ─────┤  (obrigatório)   ──► ETL ──► sav/*.sav
                 ├── Caderno .pdf ──────┤  (opcional)              json/*_import_metadata_editor.json
                 └── questionários .pdf ┘  (opcional)              censo.html
                                                                   relatorio_casamento.csv
```

O ETL é um **produtor de arquivos independente**: não conhece o endereço do
Metadata Editor. Sua saída é um `.zip` que depois é importado por outro
processo ou pessoa.

## Instalação

Testado com Python 3.13.

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Uso

```bash
streamlit run app.py
```

A interface pede os insumos, executa os três passos em um diretório temporário
e devolve um `.zip` para download. Aceita o **ZIP oficial do INEP** (um único
upload, com detecção automática do conteúdo) ou os **arquivos separados** — útil
para combinar um dicionário e tabelas novos com o Caderno e os questionários de
um ano anterior.

Só o dicionário e os CSVs são obrigatórios. O Caderno de Conceitos e os
questionários enriquecem os metadados (`var_concept`, `var_txt`,
`var_qstn_qstnlit`); sem eles o pipeline roda e esses campos ficam vazios — a
interface mostra essa consequência **antes** de processar, num painel de
cobertura.

### Execução standalone

```bash
python gerar_json_metadata_editor.py dicionario.xlsx pasta_saida pasta_questionarios "Caderno.pdf"
python criar_sav_vazio.py pasta_json pasta_saida --tabelas escola turma
python popular_sav.py dados sav --modo 1 --tabelas escola turma
```

## Estrutura

| Arquivo | Papel |
|---|---|
| `app.py` | interface Streamlit; orquestra os três passos |
| `censo_lib.py` | biblioteca compartilhada (identificação de arquivos, extração de PDF, casamento conceito↔variável, gravação de SAV) |
| `gerar_json_metadata_editor.py` | **passo 1** — JSONs de metadados + `censo.html` + relatório de casamento |
| `criar_sav_vazio.py` | **passo 2** — `.sav` vazios, só estrutura e metadados |
| `popular_sav.py` | **passo 3** — `.sav` populados; regrava o `case_count` nos JSONs |
| `gerar_caderno_html.py` | injeta os dados no template do `censo.html` |
| `templates/censo_template.html` | página autocontida, sem backend |

As seis tabelas do Censo (escola, matrícula, docente, turma, gestor, curso
técnico) são identificadas de forma **ano-agnóstica**: `Tabela_Escola_2025.csv`,
`Tabela_Escola_2026.csv` e `Tabela_Curso_Tecnico_2025_V2.csv` são todos
reconhecidos sem alterar código.

## Revisão antes de publicar

Boa parte dos metadados semânticos vem de **casamento por similaridade** entre
as descrições do dicionário, os conceitos do Caderno e as questões dos
questionários. O pipeline gera um `relatorio_casamento.csv` (uma linha por
variável, com a pontuação de cada casamento) justamente para que isso seja
auditável. **Revise-o antes de importar os metadados em produção.**

## Documentação

[DOCUMENTACAO.md](DOCUMENTACAO.md) é a referência do programa — escrita a
partir do código e revalidada a cada alteração. Vale a leitura antes de mexer
em qualquer coisa; em especial:

- **§7 — Bytes vs. caracteres no SPSS.** Toda largura do formato SPSS é medida
  em bytes; todo `tamanho` do dicionário do INEP, em caracteres. Com acentos os
  dois divergem, e essa divergência já causou duas falhas de importação.
- **§5 — Identificação ano-agnóstica de arquivos**, incluindo os marcadores de
  versão (`_V2`, `_retificado`) que o INEP acrescenta ao republicar.
- **§8 — Histórico de alterações**, com o diagnóstico de cada correção.
- **§8.5 — Item em aberto:** `Tabela_Escola.sav` ainda retorna HTTP 500 no
  Metadata Editor. Há um kit de bisecção descrito lá.

## Dados

Os insumos do INEP, arquivos de diagnóstico e artefatos gerados **não são
versionados** — ficam em `OUTROS/`, ignorada pelo Git. O app recebe os insumos
por upload; nada é lido do repositório.
