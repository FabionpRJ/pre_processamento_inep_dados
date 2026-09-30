# Especificação

O que o ETL recebe, o que produz e as regras que definem cada campo. É o
contrato do serviço: mudar qualquer coisa aqui muda o metadado publicado. O
motivo de cada regra está em [decisoes.md](decisoes.md) e em
[historico.md](historico.md).

## 1. Visão geral

```
dicionário .xlsx  (obrigatório) ─┐
Caderno de Conceitos .pdf (opc.) ├─► ETL ─► json/ceb2025_microdados_tabela_<t>_import_metadata_editor.json
questionários .pdf (opcionais)  ─┘          ceb2025_censo.html
                                            ceb2025_relatorio_casamento.csv
```

O ETL produz os metadados consumidos pelo **World Bank Metadata Editor**. É um
produtor de arquivos independente: não conhece o endereço do Metadata Editor;
sua saída é um `.zip` importado depois por outro processo ou pessoa.

- **Só o dicionário é obrigatório.** Caderno e questionários enriquecem os
  metadados; sem eles o pipeline roda e os campos correspondentes ficam vazios.
- **Os microdados (CSVs) não são insumo.** Do ZIP oficial do INEP só saem
  `.xlsx`, `.xls` e `.pdf`. Por isso `case_count` sai **0** em todos os JSONs.
- As ferramentas standalone de `.sav` (§9) partem dos JSONs e, para popular, dos
  CSVs. Não fazem parte do serviço.

## 2. As seis tabelas

Descritas em [censo_etl/tabelas.py](../censo_etl/tabelas.py). A ordem abaixo é
a canônica (abas lidas, JSONs, desempate da identificação).

| Chave | Aba do dicionário | Questionário | FID | Rótulo | Base do nome de saída |
|---|---|---|---|---|---|
| `escola` | Tabela_de_Escola | Escola | F1 | Escola | `tabela_escola` |
| `matricula` | Tabela_de_Matrícula | Aluno | F2 | Matrícula | `tabela_matricula` |
| `docente` | Tabela_de_Docente | Profissional Escolar | F3 | Docente | `tabela_docente` |
| `turma` | Tabela_de_Turma | Turma | F4 | Turma | `tabela_turma` |
| `gestor` | Tabela_de_Gestor | Gestor Escolar | F5 | Gestor Escolar | `tabela_gestor_escolar` |
| `curso_tecnico` | Tabela_Curso_Técnico | Turma | F6 | Curso Técnico | `tabela_curso_tecnico` |

`curso_tecnico` compartilha o questionário de Turma, o único não numerado do
conjunto (§6.2). A identificação de arquivos e abas não depende dos nomes acima
— ver [identificacao.md](identificacao.md).

## 3. Interface (`app.py`)

`streamlit run app.py`. Coleta os insumos, gera os metadados em diretório
temporário e devolve `censo_escolar_metadados.zip`.

**Modos de entrada**

- **ZIP oficial do INEP** — um upload. A prévia lê só o índice central do zip
  (`insumos.inspecionar_zip`) com a mesma função da extração real
  (`classificar_nomes`), então não pode discordar dela. O dicionário é lido de
  dentro do zip (`ler_membro_zip`) para listar as tabelas. Na execução, só
  `.xlsx`/`.xls`/`.pdf` são extraídos; os CSVs aparecem na prévia como
  ignorados. Zip corrompido ou sem dicionário → erro explícito.
- **Arquivos separados** — dicionário obrigatório; Caderno e questionários,
  cada um atrás de um checkbox que mostra/esconde o uploader. Checkbox marcado
  sem arquivo **bloqueia** ("Aguardando: … Envie o(s) arquivo(s) ou desmarque a
  opção correspondente."). Uploads vão para disco com o **nome original**, que
  identifica questionário e ano.

**Fluxo**

1. Sem dicionário a tela para em "Aguardando o dicionário de variáveis (.xlsx)."
2. As tabelas oferecidas vêm das **abas do dicionário**
   (`tabelas_do_dicionario`: só os nomes das abas, ordem canônica). Nenhuma aba
   reconhecida → erro. Multiselect com "Selecionar todas"/"Limpar seleção";
   a seleção é filtrada quando outro dicionário traz outras abas. Nenhuma
   tabela → aviso e parada.
3. Opções: gerar o `censo.html` (padrão ligado) e incluir os questionários
   nele — desabilitado e **travado em falso** sem questionário ou sem HTML.
4. **Painel de cobertura**: ✅/❌ para dicionário, Caderno (`var_concept`) e
   questionários (`var_qstn_qstnlit`), e a nota fixa de que `case_count` sai 0.
5. **Processar**. Barra de progresso em faixas (10/90/95/100) com tempo
   decorrido; botão **Cancelar** (interrompe no próximo ponto de verificação —
   exceções de controle do Streamlit não são capturadas); janela de log com as
   últimas 50 linhas e indicador das omitidas. Erro → mensagem acionável
   (`servico.explicar_erro`) e traceback no log.
6. **Resultado**: mensagem com nº de JSONs, presença do HTML e duração; avisos
   **persistentes** para ano não determinado, Caderno ausente e questionários
   ausentes; botão de download; "Processar novo arquivo".

Mudar qualquer arquivo ou opção depois de processar **descarta o resultado**
(`servico.assinatura`). O pacote contém só `json/*_import_metadata_editor.json`,
o `censo.html` e o relatório — os caches ficam de fora.

## 4. Ano da edição e nomes de saída

```
ceb2025_microdados_tabela_gestor_escolar_import_metadata_editor.json
└┬┘└─┬┘ └────┬───┘ └────────┬──────────┘
 │   │       │              └─ base de saída da tabela
 │   │       └─ fixo
 │   └─ ano da edição (vazio se não determinado)
 └─ "ceb" (Censo da Educação Básica)
```

| Artefato | Nome | Gerado pelo serviço |
|---|---|---|
| metadados | `ceb2025_microdados_tabela_<base>_import_metadata_editor.json` | sim |
| glossário | `ceb2025_censo.html` | sim |
| auditoria | `ceb2025_relatorio_casamento.csv` | sim |
| dados | `ceb2025_microdados_tabela_<base>.sav` | não — só declarado em `datafile.file_name` |

Vale para qualquer insumo: um pacote no formato antigo (`Tabela_Escola_2025.csv`)
também sai nesta convenção. Sem ano: `ceb_microdados_tabela_*`, **nunca um ano
inventado**, com aviso pedindo que o dicionário seja renomeado.

**De onde vem o ano** (`edicao.detectar_ano_censo`): `NU_ANO_CENSO` nos dados
(qualquer coluna com `ANO_CENSO`, lendo só a 1ª linha) → ano no nome dos CSVs →
ano nos nomes extras; entre candidatos vence o mais frequente. O serviço não lê
CSV, então só o último passo se aplica.

**Cascata** (`detectar_ano_em_cascata`), usada pela interface e pelo CLI:
primeiro **só o dicionário**; se ele não tiver ano, Caderno, questionários e o
nome do zip. O ano é detectado uma vez e passado ao pipeline.

## 5. Leitura do dicionário

Em [censo_etl/dicionario.py](../censo_etl/dicionario.py).

- Cabeçalho: primeira linha cuja coluna 0 é `"N"`. Título: primeira célula
  acima contendo "Dicionário de Variáveis" (espaços normalizados), senão esse
  texto.
- Linha seguinte ao cabeçalho: anos de coleta a partir da coluna 6 até a
  primeira vazia, lidos como `"20" + valor`. A coluna seguinte é "Notas".
- Linha de variável: coluna 0 numérica e nome não vazio. Tipo padrão `"Num"`;
  tamanho só se numérico; descrição e notas com espaço normalizado; anos de
  coleta em minúsculas (`"s"`/`"n"`).
- Categorias (`parse_categoria`): `1 - Federal` vira código; `- Não se aplica…`
  vira nota de aplicabilidade; linha sem padrão continua a anterior (ou vira
  nota, se for a primeira).
- `ano_dicionario` = última coluna de anos de coleta.
- Abas não reconhecidas: aviso e ignoradas.
- O dicionário é **sempre lido inteiro**; o recorte vem depois (§8).

## 6. Fontes opcionais

### 6.1 Caderno de Conceitos

Duas leituras do mesmo PDF, cada uma com seu cache (§8):

| Leitura | Módulo | Estrutura | Alimenta |
|---|---|---|---|
| por seção | `pdf/caderno_secoes.py` | blocos CONCEITOS/ORIENTAÇÕES das seções escola, turma, pessoa física | `var_txt`, `var_qstn_ivuinstr` |
| por conceito | `pdf/caderno_conceitos.py` + `pdf/caderno_quadros.py` | conceitos com seção, definição, categorias e destaques (pela tipografia); 6 quadros de referência | `censo.html`, `var_concept` |

Cada tabela casa com as seções do Caderno que lhe correspondem (escola →
escola; matrícula, docente, gestor → pessoa física; turma, curso técnico →
turma). Falha na extração é graciosa: segue sem Caderno, com aviso.

### 6.2 Questionários

`pdf/questionarios.py` devolve `[{"numero", "texto"}]`:

- Questões numeradas (`1 - Nome completo`), descartando texto ilegível e linhas
  com várias questões mescladas.
- Sem nenhuma numerada: **extração por layout** — o corpo de fonte dos rótulos
  é o tamanho, entre os maiores que o mais frequente, que rende mais linhas
  substantivas. `numero` fica vazio. (Turma rende 16 rótulos.)
- Nada extraído → aviso.
- A leitura é memorizada por caminho (o PDF de Turma serve três usos).

### 6.3 Casamentos

Em [censo_etl/casamento.py](../censo_etl/casamento.py). Todos por
similaridade; sem casamento acima do limiar, a variável fica sem o campo.

| Casamento | Pontuação | Limiar |
|---|---|---|
| descrição ↔ questão | F1 entre palavras específicas; exige todas (≤ 2 palavras) ou 2 (≥ 3); questão ≤ 8× a descrição | ≥ 0,50 |
| descrição ↔ bloco/conceito do Caderno | F1 de tokens; mesmo começo (30 caracteres normalizados) garante 0,85 | > 0,55 |

Para `var_concept`, título idêntico (normalizado) à descrição vence antes da
similaridade. O casamento com as questões é resolvido **uma vez** por variável e
reaproveitado no JSON, no log e no relatório.

## 7. Saídas

### 7.1 JSON de importação

`{"datafile": {...}, "variables": [...]}`, `ensure_ascii=False`, `indent=2`.

`datafile`: `file_id` e `fid` (F1–F6), `file_name` (nome do `.sav` na
convenção — é por ele que o Metadata Editor amarra o metadado ao arquivo de
dados), `labl` (título da aba), `var_count`, `case_count: 0`.

Cada variável tem **35 campos**, nesta ordem: `uid`, `sid`, `fid`, `vid`,
`name`, `labl`, `sort_order`, `var_intrvl`, `loc_width`, `var_invalrng`,
`var_valrng`, `var_sumstat`, `var_catgry`, `var_catgry_labels`, `var_format`,
`var_format_original`, `file_id`, `interval_type`, `sum_stats_options`,
`var_concept`, `var_wgt_id`, `var_universe`, `var_txt`, `var_security`,
`var_notes`, `var_respunit`, `var_qstn_preqtxt`, `var_qstn_qstnlit`,
`var_qstn_postqtxt`, `var_forward`, `var_backward`, `var_qstn_ivuinstr`,
`var_codinstr`, `var_imputation`, `var_derivation`.

| Campo | Regra |
|---|---|
| `uid` / `vid` / `sort_order` | índice 1-based / `V{i}` / `i-1`, como texto |
| `sid` | `fid` sem o `F` |
| `name`, `labl` | nome e descrição do dicionário |
| `var_format` (= `var_format_original`) | `Char`/`Data` → `A{tamanho or 1}`, `is_date` só em `Data`; numérico → `F{largura}.{casas}` (`formato.formato_numerico`; LATITUDE/LONGITUDE com 6 casas, largura ≥ casas + 2) |
| `loc_width` | tamanho do dicionário (padrão 8, mínimo 1) |
| `var_catgry_labels` | **todos** os códigos, inclusive os especiais, ordenados |
| `var_invalrng.values` | códigos especiais (§7.2), como texto, ordenados |
| `var_imputation` | descrição dos códigos especiais (§7.2) |
| `sum_stats_options` | na ordem: `Data` → min/max; `NO_ENTIDADE` → nada; LATITUDE/LONGITUDE ou prefixo `QT_` → min/max/mean/stdev; alguma categoria **real** → freq; `Num` sem prefixo `CO_`/`NU_`/`ID_` → min/max/mean/stdev. `missing`/`vald` sempre; pesos nunca |
| `var_intrvl` / `interval_type` | `"contin"` se `mean`, senão `"discrete"` |
| `var_universe` | `"Escola de Educação Básica declarada em {ano do dicionário}"`; sem ano, `"Escola de Educação Básica declarada no Censo Escolar"` |
| `var_notes` | por `\n`: notas do dicionário; `"Coletado em 2025"` ou `"Coletado em: 2019–2025"`; `"Variável descontinuada no ano de {ano}."` se a coluna do ano do dicionário for `"n"` |
| `var_txt` | definição do Caderno; na falta, a descrição do dicionário |
| `var_qstn_ivuinstr` | orientação do Caderno e destaque "Importante!"/"Você sabia?", nessa ordem, por `\n` |
| `var_concept` | `[[{"concept": <título em Title Case>, "vocab": "", "vocabURI": ""}]]`, ou `[[]]` |
| `var_qstn_qstnlit` | questão casada |
| demais | vazios fixos |

### 7.2 Valores especiais

O dicionário lista, na coluna de categorias, códigos que **não são
categoria**. Em 2025:

| Código | Rótulo no dicionário | Variáveis | Tipo |
|---|---|---:|---|
| `88888` | "registro com marcação de valor extremo (…)" | 26 `QT_*` | imputação |
| `9` | "Não informado" | 20 `TP_*` | não-resposta |
| `99999999999999` | "Sem declaração" | 2 de CNPJ | não-resposta |

- **O rótulo decide, nunca o número** (`classificar_codigo_especial`): sem
  acento, sem caixa, espaço normalizado, contra `MARCADORES_IMPUTACAO` e depois
  `MARCADORES_NAO_RESPOSTA`. Os marcadores são específicos (`"nao informad"`,
  não `"nao"` — "Não oferece" é categoria real).
- Os dois tipos vão para `var_invalrng` **e** `var_imputation`; o rótulo
  continua em `var_catgry_labels`.
- `var_imputation`: para cada código, `Código {c}: {natureza}; no dicionário de
  variáveis, “{rótulo}”.`, unidos por espaço, sem frase de abertura.
- Códigos especiais não contam como categoria em `sum_stats_options` (os CNPJ
  não pedem frequência).
- **Auditoria**: código com cara de sentinela (repetição de 8 ou 9 com 2+
  dígitos) cujo rótulo não casou com nenhum marcador gera aviso nomeando
  variável, código e rótulo.

Efeito: 88888 dentro da média de "quantidade de televisões" é a diferença
entre 3,4 e 4.317,0.

### 7.3 Relatório de casamento

`ceb<ano>_relatorio_casamento.csv`, `;`, `utf-8-sig` (abre direto no Excel
pt-BR), uma linha por variável das tabelas processadas:

```
tabela;variavel;descricao;conceito;tem_var_txt;questao;score_questao;valores_especiais
```

`tem_var_txt` é `sim` ou vazio; `score_questao` tem 3 casas (vazio sem
questão); `valores_especiais` é `88888=imputacao 9=nao_resposta`. **Revise
antes de publicar**: boa parte dos metadados semânticos vem de similaridade.

### 7.4 censo.html

Página autocontida (template em `censo_etl/templates/censo_template.html`). Os
dados vão em `<script id="app-data" type="application/json">`, com `</`
escapado:

| Chave | Item | Origem |
|---|---|---|
| `conceitos` | `conceito`, `secao`, `definicao`, `categorias`, `destaques` | Caderno |
| `quadros` | `id`, `titulo`, `cols`, `labels`, `rows` | Caderno (anexos) |
| `questionarios` | `id`, `titulo`, `perguntas` | PDFs, um por arquivo (Turma aparece uma vez) |
| `dicionario` | `id`, `titulo`, `fonte`, `variaveis` | dicionário (todas as abas) |

Cada modo da página só aparece se sua fonte veio preenchida; a página abre no
primeiro disponível.

### 7.5 Avisos por tabela

Além da linha de resumo, o log avisa quando uma tabela fica sem questão
disponível, tem questões mas nenhuma casou, fica sem nenhum conceito, e resume
os valores especiais. É por esses avisos que se percebe uma mudança do INEP.

## 8. Recorte e caches

**O recorte vale para os artefatos por tabela, não para o documento de
consulta.** `tabelas_alvo` restringe os JSONs e o relatório; o `censo.html`
recebe todas as abas, o Caderno inteiro e todos os questionários. Tabela pedida
sem aba → aviso; nenhuma → erro.

Os dois caches do Caderno ficam na pasta de saída:

| Arquivo | Conteúdo | Impressão digital |
|---|---|---|
| `caderno_conceitos_metadados.json` | blocos por seção alinhados por variável | PDF + nomes das variáveis |
| `censo_html_dados.json` | `conceitos` + `quadros` | PDF |

Formato `{"_fingerprint": "<16 hex>", "dados": ...}`. A impressão digital
(SHA-256 de `VERSAO_CACHE_CADERNO`, dos bytes do PDF e dos nomes) é conferida;
cache antigo, corrompido ou de outras entradas é refeito. Como o dicionário é
lido inteiro, o cache não depende do recorte.

## 9. Ferramentas standalone de `.sav`

Fora do serviço, em `censo_etl/sav/`:

- **`criar-sav-vazio`** — um `.sav` de 0 linhas por JSON, com os tipos e
  metadados.
- **`popular-sav`** — lê os CSVs (codificação validada no arquivo inteiro;
  delimitador `;`, `,`, tab ou `|` contado fora de aspas; tudo como texto) e
  grava o `.sav`. Modo 1: todas as variáveis do dicionário (ausentes ficam
  vazias). Modo 2: só as colunas do CSV, extras no fim com tipo inferido. Sem
  `--modo`, pergunta. **Regrava `case_count`** no JSON — o único caminho que o
  preenche.
- O nome do `.sav` vem de `datafile.file_name` do JSON, nunca recalculado. O
  JSON é achado pelo nome da tabela, sem saber o ano. Os CSVs são identificados
  por nome e, se preciso, pelo cabeçalho ([identificacao.md](identificacao.md)).
- Callback opcional `progresso(indice, total, tabela)`.
- Larguras e rótulos medidos em bytes: ver [operacao.md](operacao.md).
