# ETL do Censo Escolar

Transforma os insumos oficiais do INEP nos metadados consumidos pelo
**World Bank Metadata Editor**: os `.json` de importação e um `censo.html`
navegável.

```
                 ┌── dicionário .xlsx ──┐  (obrigatório)
insumos INEP ────┼── Caderno .pdf ──────┤  (opcional)   ──► ETL ──► json/ ceb2025_microdados_tabela_escola_import_metadata_editor.json
                 └── questionários .pdf ┘  (opcional)                    ceb2025_censo.html
                                                                         ceb2025_relatorio_casamento.csv
```

**O único insumo obrigatório é o dicionário de variáveis.** Os microdados
(CSVs) não são lidos: o serviço produz metadados, não dados. Enviando o ZIP
oficial do INEP, os CSVs de dentro dele são ignorados — só o dicionário, o
Caderno e os questionários são extraídos.

A saída segue a convenção da publicação do INEP
(`ceb2025_microdados_tabela_gestor_escolar_import_metadata_editor.json`). O ano
vem do nome dos insumos (dicionário, Caderno, questionários ou o nome do
pacote); sem nenhum deles, sai `ceb_microdados_tabela_*` e a interface avisa.
Vale para qualquer insumo — um pacote no formato antigo produz saída nesta
mesma convenção. Ver [DOCUMENTACAO.md §4.0](DOCUMENTACAO.md).

Como o ETL não lê os dados, o `case_count` de cada tabela sai **0** nos JSONs.
O campo `datafile.file_name` continua declarando o nome do `.sav`
correspondente — é por ele que o Metadata Editor amarra o metadado ao arquivo
de dados publicado.

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

A interface pede os insumos, gera os metadados em um diretório temporário e
devolve um `.zip` para download. Aceita o **ZIP oficial do INEP** (um único
upload, com detecção automática do conteúdo) ou os **arquivos separados** —
útil para combinar um dicionário novo com o Caderno e os questionários de um
ano anterior.

As tabelas processadas são escolhidas em um multiselect alimentado pelas
**abas do dicionário**. O Caderno de Conceitos e os questionários enriquecem
os metadados (`var_concept`, `var_txt`, `var_qstn_qstnlit`); sem eles o
pipeline roda e esses campos ficam vazios — a interface mostra essa
consequência **antes** de processar, num painel de cobertura.

### Execução standalone

```bash
python gerar_json_metadata_editor.py dicionario.xlsx pasta_saida pasta_questionarios "Caderno.pdf"
```

### Gerar .sav (fora do serviço)

O serviço não produz mais `.sav`. Os dois scripts que os geram continuam no
repositório e funcionam a partir dos JSONs acima, para quem tiver os
microdados em mãos:

```bash
python criar_sav_vazio.py pasta_json pasta_saida --tabelas escola turma
python popular_sav.py dados sav --modo 1 --tabelas escola turma
```

`popular_sav.py` também regrava o `case_count` nos JSONs — o número de linhas
só é conhecido por quem lê os dados.

## Estrutura

| Arquivo | Papel |
|---|---|
| `app.py` | interface Streamlit; gera os metadados |
| `censo_lib.py` | biblioteca compartilhada (identificação de arquivos, extração de PDF, casamento conceito↔variável, gravação de SAV) |
| `gerar_json_metadata_editor.py` | JSONs de metadados + `censo.html` + relatório de casamento |
| `gerar_caderno_html.py` | injeta os dados no template do `censo.html` |
| `templates/censo_template.html` | página autocontida, sem backend |
| `criar_sav_vazio.py` | **standalone** — `.sav` vazios, só estrutura e metadados |
| `popular_sav.py` | **standalone** — `.sav` populados; regrava o `case_count` nos JSONs |
| `testar_identificacao.py` | regressão da identificação de insumos |
| `testar_valores_especiais.py` | regressão dos códigos especiais do dicionário |

## Resistência a mudanças de forma

O INEP muda a forma dos insumos sem aviso. Para o **mesmo** Censo 2025 já
circularam `Tabela_Escola_2025.csv` (`;`, iso-8859-1, pasta `Anexos/`) e
`ceb2025_microdados_tabela_escola.csv` (`,`, UTF-8 com BOM, pasta `dicionario
de dados/`) — e o Caderno de Conceitos saiu como *"cadastro* de conceitos",
erro de digitação da fonte.

A identificação é feita em **três camadas**:

1. **Nome** — vira um *conjunto* de tokens significativos; ano, prefixo de
   edição (`ceb2025_`), `microdados`, `tabela`, `quest` e marcadores de versão
   (`_V2`, `_retificado`) são descartados **em qualquer posição**.
2. **Conteúdo** — se o nome não bastar, o PDF é aberto e o texto decide (é
   assim que o Caderno é achado mesmo com o nome errado na fonte). Para CSVs,
   o cabeçalho é comparado com as variáveis do dicionário — caminho usado
   pelos scripts standalone de `.sav`, já que o serviço não lê dados.
3. **Relatório** — cada resolução registra por qual camada passou e com que
   pontuação; nome e cabeçalho em desacordo geram aviso, e o cabeçalho vence.

Estrutura de pastas é deduzida dos arquivos encontrados, nunca do nome das
pastas. Nos scripts standalone de `.sav`, o delimitador (`;` `,` tab `|`) e a
codificação (`utf-8`/`utf-8-sig`/`cp1252`/`latin-1`) também são detectados, não
configurados.

```bash
python testar_identificacao.py   # fixa esse comportamento
```

Detalhes e pontos de extensão em [DOCUMENTACAO.md §5](DOCUMENTACAO.md).

## Valores especiais do dicionário

O dicionário lista, junto das categorias, códigos que **não são categorias**:
em 2025, `88888` ("registro com marcação de valor extremo"), `9` ("Não
informado") e `99999999999999` ("Sem declaração"). Eles são separados das
categorias reais e declarados em `var_invalrng` **e** `var_imputation`: todos
são valores que o produtor grava no lugar da observação. A natureza de cada um
(tratamento de consistência × ausência de declaração) fica explícita no texto
gerado e na coluna `valores_especiais` do relatório.

Importa porque `88888` entrando na média de "quantidade de televisões" é a
diferença entre **3,4 e 4.317,0**.

**Quem decide é o rótulo, não o número** — no mesmo dicionário o código `8` é
categoria real ("Área onde se localizam povos e comunidades tradicionais") e o
`9` é "Não informado". A regra conhece redações, não números, então generaliza
para outros anos e outros dicionários; uma redação que ela não conheça vira
`[AVISO]` no log, nomeando variável, código e rótulo.

A coluna `valores_especiais` do `relatorio_casamento.csv` mostra o que foi
reclassificado, variável a variável. Detalhes em
[DOCUMENTACAO.md §4.1](DOCUMENTACAO.md); o diagnóstico, em §8.12.

```bash
python testar_valores_especiais.py   # fixa esse comportamento
```

> A leitura dos códigos especiais como resultado de **imputação** (regra de
> consistência do INEP) segue posição registrada em reunião e está **pendente
> de validação** com as áreas responsáveis. A distinção entre os dois tipos
> continua registrada no código e no relatório, então voltar atrás é mexer em
> `censo_lib.descrever_imputacao` — uma função.

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
- **§5 — Identificação resiliente de insumos**, as três camadas e como
  estendê-las quando o INEP mudar de convenção outra vez.
- **§4.1 — Valores especiais**, por que o rótulo decide e não o número.
- **§8 — Histórico de alterações**, com o diagnóstico de cada correção.
- **§8.5 — Item em aberto:** `Tabela_Escola.sav` ainda retorna HTTP 500 no
  Metadata Editor. Há um kit de bisecção descrito lá.

## Dados

Os insumos do INEP, arquivos de diagnóstico e artefatos gerados **não são
versionados** — ficam em `OUTROS/`, ignorada pelo Git. O app recebe os insumos
por upload; nada é lido do repositório.
