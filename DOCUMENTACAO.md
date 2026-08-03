# ETL do Censo Escolar — Documentação do Programa

Documentação de referência do pipeline que transforma os insumos oficiais do
INEP (dicionário, microdados, Caderno de Conceitos e questionários) nos
artefatos consumidos pelo **World Bank Metadata Editor**: arquivos `.sav`
(SPSS/Stata) com metadados completos, os `.json` de importação e o `censo.html`
navegável.

**Este é o documento de referência do projeto.** Onde ele divergir de qualquer
outro, este vale: foi escrito a partir do código atual e é revalidado a cada
alteração (§9).

O diagnóstico que motivou as alterações mais recentes está resumido no
histórico: **§8.6** (usabilidade da interface), **§8.7** (marcador de versão
nos nomes de arquivo) e **§8.8** (qualidade dos metadados) — cada uma com o
defeito encontrado, a correção e os números medidos.

> Os documentos de análise que originaram essas seções (`RECOMMENDATION.md` e
> `RECOMMENDATION2.md`) ficam em `OUTROS/`, fora do versionamento: são notas
> de trabalho internas. O que interessa deles está aqui.
>
> Versões anteriores desta documentação também citavam
> `INSTRUCOES_ALTERACAO_ETL.md` e `INSTRUCOES_GERADOR_CENSO_HTML.md`, que
> **nunca existiram no repositório** — os links estavam quebrados. O conteúdo
> está absorvido aqui: `var_concept` em §4 e §8.8, `censo.html` em §4 e §8.2.

---

## 1. Visão geral

O ETL é um **produtor de arquivos independente**. Ele não conhece o endereço do
Metadata Editor (que roda em servidor institucional) — sua saída é um pacote
`.zip` que depois é importado por outro processo ou pessoa.

```
                 ┌── dicionário .xlsx ──┐  (obrigatório)
insumos INEP ────┼── CSVs de dados ─────┤  (obrigatório)   ──► ETL ──► sav/*.sav
                 ├── Caderno .pdf ──────┤  (opcional)              json/*_import_metadata_editor.json
                 └── questionários .pdf ┘  (opcional)              censo.html
                                                                   relatorio_casamento.csv
```

Só o dicionário e os CSVs são obrigatórios. O Caderno e os questionários
enriquecem os metadados (`var_concept`, `var_txt`, `var_qstn_qstnlit`); sem
eles o pipeline roda e esses campos ficam vazios — ver §3 (painel de cobertura).

O pipeline tem **três passos**, orquestrados pela interface Streamlit:

| Passo | Módulo | Produz |
|---|---|---|
| 1 | `gerar_json_metadata_editor.py` | `*_import_metadata_editor.json` + `censo.html` + `relatorio_casamento.csv` |
| 2 | `criar_sav_vazio.py` | `.sav` vazios (só estrutura e metadados) |
| 3 | `popular_sav.py` | `.sav` populados + `case_count` regravado nos JSONs |

O passo 2 existe para registrar a estrutura completa das tabelas antes de
carregar dados; o passo 3 sobrescreve os mesmos arquivos já com as linhas.

O passo 3 também **volta nos JSONs do passo 1** para gravar o `case_count`
real: quando o JSON é escrito, ainda não existe nenhuma linha carregada.

---

## 2. As seis tabelas

O Censo Escolar é publicado em seis tabelas. Todas as constantes que as
descrevem ficam em [censo_lib.py](censo_lib.py):

| Chave interna | Aba do dicionário | CSV (padrão INEP) | Questionário | FID | Rótulo |
|---|---|---|---|---|---|
| `escola` | Tabela_de_Escola | `Tabela_Escola_<ano>.csv` | Escola | F1 | Escola |
| `matricula` | Tabela_de_Matrícula | `Tabela_Matricula_<ano>.csv` | Aluno | F2 | Matrícula |
| `docente` | Tabela_de_Docente | `Tabela_Docente_<ano>.csv` | Profissional Escolar | F3 | Docente |
| `turma` | Tabela_de_Turma | `Tabela_Turma_<ano>.csv` | Turma | F4 | Turma |
| `gestor` | Tabela_de_Gestor | `Tabela_Gestor_Escolar_<ano>.csv` | Gestor Escolar | F5 | Gestor Escolar |
| `curso_tecnico` | Tabela_Curso_Técnico | `Tabela_Curso_Tecnico_<ano>.csv` | Turma | F6 | Curso Técnico |

Os nomes de CSV na tabela acima são o **padrão**, não um casamento literal: o
ano e um eventual marcador de versão (`_V2`, `_retificado`) são ignorados na
identificação — ver §5.

`curso_tecnico` compartilha o questionário de Turma — por isso o `censo.html`
deduplica os PDFs antes de montar as abas. Esse questionário é o único **não
numerado** do conjunto, e depende do extrator por layout (§3).

---

## 3. Módulos

### `app.py` — interface Streamlit

Ponto de entrada (`streamlit run app.py`). Coleta os insumos, executa os três
passos em um diretório temporário e devolve um `.zip` para download.

Oferece **dois modos de entrada**:

- **ZIP oficial do INEP** — um único upload. Antes de processar, `inspecionar_zip`
  varre o índice do arquivo (sem extrair) e mostra o que foi identificado; os
  mesmos critérios são usados na extração. O app localiza o dicionário (`*.xlsx`
  com "dicion" no nome, ignorando temporários `~$`), a pasta de questionários
  (diretório com "question" no nome), a pasta `dados/` (ou, na falta dela, a
  pasta-mãe dos `Tabela_*.csv`) e o Caderno (PDF com "caderno" e "conceito" no
  nome). Um `multiselect` — restrito às tabelas que têm CSV dentro do zip —
  escolhe o que processar.
- **Arquivos separados** — dois uploads **obrigatórios** (dicionário `.xlsx` e
  CSVs) e dois **opcionais**, cada um atrás de um checkbox que mostra/esconde o
  uploader: Caderno `.pdf` e questionários `.pdf` (múltiplos). As tabelas
  processadas são **derivadas dos CSVs enviados**, sem multiselect.

Caderno e questionários são apenas fontes de metadados: sem eles o pipeline roda
normalmente, mas `var_concept` e `var_qstn_qstnlit` ficam vazios. O **painel de
cobertura** mostra essa consequência antes da execução, e um `st.warning`
persistente a repete no resultado:

```
Cobertura de metadados com a seleção atual
  ✅ nomes, tipos, rótulos e categorias — dicionário
  ❌ conceitos e definições (var_concept) — Caderno de Conceitos — ficará vazio
  ✅ perguntas literais (var_qstn_qstnlit) — questionários
```

No modo por arquivos, cada opcional fica atrás de um checkbox que **mostra ou
esconde o uploader** — desmarcar é a forma de dizer "não tenho este insumo".
Marcar o checkbox e não enviar o arquivo é ambíguo, então bloqueia com uma
mensagem pedindo o envio ou o desmarque. A validação obrigatória cobre **apenas**
dicionário e CSVs.

Duas opções de saída controlam o pacote: `gerar_html` (censo.html) e o **modo de
colunas**, que expõe o parâmetro `modo` de `popular_sav` — todas as variáveis do
dicionário (modo 1, padrão) ou apenas as colunas presentes no CSV (modo 2).

`incluir_questionarios` é **travado em falso** quando nenhum questionário foi
fornecido: deixar a flag ligada faria o painel de cobertura discordar do
`censo.html` efetivamente gerado.

O pacote final contém `sav/*.sav`, `json/*_import_metadata_editor.json`,
`censo.html` e `relatorio_casamento.csv`. Os caches intermediários do Caderno
ficam de fora.

**Tratamento de erros.** Falhas de passo são traduzidas por `explicar_erro`
(mensagem acionável na tela, traceback completo no log). `rodar_passo`
intercepta `Exception` **e** `SystemExit` — os módulos do pipeline sinalizam
entrada inválida com `sys.exit()`, que `except Exception` não pega. Exceções de
controle do Streamlit (`RerunException`/`StopException`) continuam propagando,
que é o que permite o botão **Cancelar** funcionar.

**Falhas parciais.** As tabelas com erro devolvidas pelos passos 2 e 3, e as
lacunas de cobertura (Caderno/questionários ausentes), viram `st.warning`
persistentes guardados em `session_state` — sobrevivem ao rerun e continuam
visíveis junto do botão de download. Antes só apareciam como uma linha `[aviso]`
dentro da janela de log, que rolava e sumia: era possível ver "Concluído!" em
verde com uma tabela que falhou.

**Progresso.** A barra usa faixas ponderadas (`P_ENTRADAS`/`P_PASSO1`/
`P_PASSO2`/`P_PASSO3`) e acompanha o passo 3 **tabela a tabela** via o callback
`progresso`, porque é ele que domina o tempo. Mostra o tempo decorrido junto do
percentual.

**Outros detalhes da interface:** limite de upload exibido a partir de
`server.maxUploadSize`; botões "Selecionar todas"/"Limpar seleção" no
multiselect de tabelas, com rótulos amigáveis via `ROTULO_TABELA`; aviso de
execução longa quando matrícula ou docente estão selecionadas; legenda
explicando por que o botão "Processar" está desabilitado; indicador de linhas
omitidas quando o log passa de `LOG_MAX` (50) linhas.

A assinatura que invalida um resultado já gerado cobre **arquivos e opções** —
mudar um checkbox depois de processar descarta o resultado anterior, em vez de
deixar disponível um download que não corresponde mais à seleção.

### `censo_lib.py` — biblioteca compartilhada

Módulo mais pesado do projeto. Reúne:

- **Constantes das tabelas** — `ABA_PARA_ARQUIVO`, `TABELAS`, `NOME_TABELA`,
  `FID_POR_TABELA`, `ROTULO_TABELA`, `UNIVERSO_POR_TABELA`,
  `QUESTIONARIO_POR_TABELA` (esta última é **código morto**: quem vale é
  `BASE_QUESTIONARIO_POR_TABELA` — ver §5).
- **Identificação de arquivos** — `_chave_arquivo`, `identificar_tabela`,
  `mapear_csvs`, `localizar_csv`, `localizar_questionario` (ver §5).
- **Formato numérico declarado** — `DECIMAIS_POR_VARIAVEL`, `largura_variavel`,
  `decimais_variavel`, `formato_numerico`. Fonte **única** do formato: usada
  tanto pelo JSON quanto pela gravação do `.sav`, para os dois não divergirem
  (ver §4).
- **Leitura de CSV** — `detectar_encoding` (tenta `utf-8-sig`, `utf-8`,
  `latin-1`), `detectar_delimitador` (`;` vs `,`), `ler_csv`. Tudo lido como
  string; a tipagem vem do dicionário.
- **Extração de questionários (PDF)** — `extrair_questoes_pdf`,
  `extrair_questionario_html`, `extrair_questionario_layout`,
  `encontrar_questao` / `encontrar_questao_com_score` (casamento por
  similaridade entre a descrição da variável e o texto da questão, com limiar
  de 0,50; a variante `_com_score` expõe a pontuação para o
  `relatorio_casamento.csv`).

  Dois formatos de questionário são suportados. O comum é **numerado**
  (`1 - Nome completo`), casado por `_QUESTAO_RE`. Mas o questionário de
  **Turma não numera as perguntas**: é um formulário em que o rótulo do campo
  aparece num corpo de fonte maior que o das alternativas. Quando a extração
  numerada devolve zero, `extrair_questionario_html` recorre a
  `extrair_questionario_layout`, que descobre o corpo dos rótulos por
  estatística — entre os tamanhos maiores que o mais frequente da página,
  vence o que rende mais linhas substantivas. (Fixar o tamanho não funciona: o
  PDF de Turma tem `:` em Times 8,6 sobre um corpo Arial 8,0.) Nas perguntas
  vindas por layout, `numero` fica vazio — o documento não traz numeração e
  inventar uma seria enganoso.

  Se nenhum dos dois caminhos extrair algo, um **aviso explícito** é emitido:
  antes, um questionário ilegível era indistinguível de um não enviado.
- **Extração do Caderno (PDF)** — `extrair_conceitos_pdf` (blocos por seção),
  `extrair_conceitos_html` (rica, por conceito, usada no `censo.html`),
  `extrair_quadros_pdf` (6 quadros de referência: línguas indígenas, cursos
  técnicos, áreas do conhecimento, atividades complementares, cursos superiores,
  pós-graduação).
- **Casamento conceito↔variável** — `obter_metadados_caderno` (alimenta
  `var_txt`/`var_notes`/`var_qstn_ivuinstr`), `indexar_conceitos`,
  `mapear_conceitos_para_concept` (alimenta `var_concept`) e `rotulo_conceito`
  (título em Title Case, só na saída do JSON — os títulos vêm em CAIXA ALTA do
  Caderno e continuam assim no `censo.html`).
- **Caches versionados** — `fingerprint_fontes`, `ler_cache_versionado`,
  `gravar_cache_versionado` (ver §6).
- **Gravação de SAV** — `truncar`, `largura_bytes_colunas`,
  `construir_meta_sav`, `gravar_sav`.
- **Pós-processamento** — `atualizar_case_count`, chamada no passo 3 para
  regravar o total de linhas no JSON do passo 1.

### `gerar_json_metadata_editor.py` — passo 1

Lê o dicionário `.xlsx` e monta um JSON por tabela no schema do Metadata Editor
(DDI-CodeBook 2.5). Também dispara a geração do `censo.html` e grava o
`relatorio_casamento.csv`.

```python
executar(caminho_xlsx, pasta_saida, pasta_questionarios=None, caminho_caderno=None,
         gerar_html=True, incluir_questionarios=True, tabelas_alvo=None)
```

`tabelas_alvo` restringe **apenas** quais tabelas viram JSON. O dicionário é
sempre lido por inteiro — ver §6.

**Casamento resolvido uma única vez.** O par descrição↔questão é caro
(O(variáveis × questões)) e antes era calculado duas vezes: uma só para contar
acertos no log, outra dentro de `gerar_json_importacao`. Agora `executar`
resolve uma vez e o resultado alimenta o log, o JSON e o relatório.

**Leitura de PDF memorizada.** `perguntas_do_pdf` guarda o resultado por
caminho: o questionário de Turma serve duas tabelas (turma e curso_tecnico) e
também o `censo.html`, e era reparseado três vezes por execução.

**Avisos por tabela.** Uma tabela que termina sem nenhum metadado semântico é
sempre sintoma de problema — questionário não numerado, seção do Caderno que não
corresponde à tabela — e antes isso passava como um `0` discreto no log. Hoje
sai avisado:

```
[AVISO] Matrícula: nenhum conceito do Caderno casou — var_concept ficará vazio nas 239 variáveis.
```

Os três casos avisados: nenhuma questão disponível; questões extraídas mas
nenhuma casou; nenhum conceito casado.

### `gerar_caderno_html.py` — geração do `censo.html`

Injeta os dados estruturados no marcador `__APP_DATA__` de
`templates/censo_template.html`. Não reprocessa PDF nem xlsx.

```python
gerar_censo_html(conceitos, quadros, saida_path, questionarios=None,
                 titulo=..., dicionario=None)
```

### `criar_sav_vazio.py` — passo 2

`executar(tabelas_alvo, pasta_json, pasta_saida, progresso=None) -> list[str]`
(tabelas com erro). Monta um DataFrame vazio com os dtypes corretos e grava via
`gravar_sav`.

### `popular_sav.py` — passo 3

`executar(tabelas_alvo, pasta_csv, pasta_sav, modo, progresso=None) -> list[str]`.

- **Modo 1** (padrão da interface): todas as variáveis do dicionário; colunas
  ausentes no CSV ficam vazias (`NaN` para numéricas, `""` para texto).
- **Modo 2**: só as colunas presentes no CSV; extras do CSV vão para o fim com
  tipo inferido.

O modo é escolhido pelo usuário na interface (radio "Colunas nos arquivos .sav").

`processar_tabela` devolve o número de linhas gravadas e chama
`censo_lib.atualizar_case_count`, fechando o `case_count` do JSON do passo 1.

### Callback `progresso` (passos 2 e 3)

Opcional, chamado como `progresso(indice, total, tabela)` antes de cada tabela.
Existe para a interface mostrar avanço **medido** em vez de estimado: o passo 3
lê os CSVs inteiros e domina o tempo de execução, então a barra o acompanha
tabela a tabela. Sendo opcional (`None` por padrão), o uso standalone via CLI
não muda.

---

## 4. Formatos de saída

### JSON de importação

Um arquivo por tabela: `<tabela>_import_metadata_editor.json`.

```json
{
  "datafile": { "file_id": "F5", "fid": "F5", "file_name": "gestor.sav",
                "labl": "Dicionário de Variáveis - Tabela de Gestor",
                "var_count": 65, "case_count": 0 },
  "variables": [ { "...": "35 campos por variável" } ]
}
```

> `case_count` aparece 0 acima porque é assim que o passo 1 o escreve; ao fim
> do passo 3 ele carrega o total real de linhas do `.sav`.

Campos por variável: `uid`, `sid`, `fid`, `vid`, `name`, `labl`, `sort_order`,
`var_intrvl`, `loc_width`, `var_invalrng`, `var_valrng`, `var_sumstat`,
`var_catgry`, `var_catgry_labels`, `var_format`, `var_format_original`,
`file_id`, `interval_type`, `sum_stats_options`, `var_concept`, `var_wgt_id`,
`var_universe`, `var_txt`, `var_security`, `var_notes`, `var_respunit`,
`var_qstn_preqtxt`, `var_qstn_qstnlit`, `var_qstn_postqtxt`, `var_forward`,
`var_backward`, `var_qstn_ivuinstr`, `var_codinstr`, `var_imputation`,
`var_derivation`.

`case_count` nasce 0 (o JSON é escrito no passo 1, antes de existir qualquer
linha) e é **regravado no passo 3** por `censo_lib.atualizar_case_count`, com o
total real de linhas do `.sav`.

**Procedência dos campos preenchidos:**

| Campo | Fonte |
|---|---|
| `name`, `labl`, `var_format`, `loc_width`, `var_catgry_labels` | dicionário `.xlsx` |
| `var_universe` | `UNIVERSO_POR_TABELA` — a população da tabela |
| `var_notes` | notas do dicionário + destaques do Caderno + anos de coleta |
| `var_txt` | Caderno (com a descrição do dicionário como reserva) |
| `var_qstn_ivuinstr` | Caderno (orientações de preenchimento) |
| `var_concept` | Caderno (**título** do conceito casado, em Title Case) |
| `var_qstn_qstnlit` | questionário PDF (questão literal) |
| `sum_stats_options` | heurística por prefixo do nome (`QT_`, `CO_`, `NU_`, `ID_`) e tipo |
| `var_intrvl`, `interval_type` | derivados de `sum_stats_options["mean"]` |

`sum_stats_options` nunca marca peso amostral: o Censo é enumeração completa,
não amostra.

**Coerência interna garantida** (contexto em §8.8):

- `var_intrvl` e `interval_type` valem `"contin"` quando `sum_stats_options`
  marca `mean`, senão `"discrete"` — antes eram `"discrete"` fixo, contradizendo
  as 707 variáveis que o mesmo objeto declarava contínuas.
- `var_format.data_format` sai de `censo_lib.formato_numerico`, **a mesma
  função usada na gravação do `.sav`** — antes o JSON emitia `F{n}.0` e o `.sav`
  saía com o padrão `F8.2` do pyreadstat, divergindo em 100% das numéricas.
  `LATITUDE`/`LONGITUDE` têm casas decimais declaradas via
  `DECIMAIS_POR_VARIAVEL`.
- `loc_width` vem do `tamanho` do dicionário para todos os tipos (era fixo em 8
  nas numéricas, contradizendo o `data_format` do próprio objeto).
- `var_universe` descreve a **população**, não o período: os anos de coleta
  ficam em `var_notes`. ⚠️ Os textos de `UNIVERSO_POR_TABELA` são conservadores
  e merecem revisão de quem conhece o domínio.
- `var_concept` guarda o **título** do conceito (rótulo curto, como pede o DDI),
  não a definição — que continua em `var_txt`. Antes o mesmo parágrafo, de até
  1807 caracteres, ia nos dois campos.

### `relatorio_casamento.csv`

Gerado junto dos JSONs, uma linha por variável, separador `;`, `utf-8-sig`
(abre direto no Excel pt-BR):

```
tabela;variavel;descricao;conceito;tem_var_txt;questao;score_questao
```

Existe porque boa parte dos metadados semânticos vem de casamento por
similaridade e o log só mostra contagens agregadas. É o artefato para conferir,
variável a variável, o que foi atribuído e com que pontuação — **revise antes de
publicar**. Vai junto no `.zip` de download.

### `censo.html`

Página autocontida, sem backend. Os dados vivem em
`<script id="app-data" type="application/json">` com quatro chaves:

| Chave | Item | Origem |
|---|---|---|
| `conceitos` | `conceito`, `secao`, `definicao`, `categorias`, `destaques` | Caderno |
| `quadros` | `id`, `titulo`, `cols`, `labels`, `rows` | Caderno (apêndices) |
| `questionarios` | `id`, `titulo`, `perguntas` | PDFs dos questionários |
| `dicionario` | `id`, `titulo`, `fonte`, `variaveis` | dicionário `.xlsx` |

Cada modo só aparece se sua fonte veio preenchida; sem `conceitos`, por
exemplo, a página abre direto no primeiro modo disponível.

---

## 5. Identificação ano-agnóstica de arquivos

O INEP versiona nomes por ano (`Tabela_Escola_2025.csv`, `Escola 2025.pdf`) e,
quando reedita um arquivo, acrescenta um marcador de versão **depois** do ano
(`Tabela_Curso_Tecnico_2025_V2.csv`). Casar por nome literal quebrava a cada
edição e impedia combinar insumos de anos diferentes.

`_chave_arquivo()` normaliza qualquer nome de arquivo ou aba: remove acentos,
baixa a caixa, colapsa separadores em `_` e **remove ano e marcador de versão
do final**.

```
"Tabela_Gestor_Escolar_2027.csv"      →  "tabela_gestor_escolar"  →  gestor
"TABELA_CURSO_TECNICO_2026.csv"       →  "tabela_curso_tecnico"   →  curso_tecnico
"Tabela_Curso_Tecnico_2025_V2.csv"    →  "tabela_curso_tecnico"   →  curso_tecnico
"Tabela_Escola_2025_retificada_V3.csv"→  "tabela_escola"          →  escola
"Profissional Escolar 2025.pdf"       →  "profissional_escolar"   →  docente
"Cadastro Escola Nova 2025.pdf"       →  "cadastro_escola_nova"   →  (nenhuma)
```

Ano e versão são removidos **em laço**, porque aparecem em qualquer ordem e em
combinação (`..._2025_V2`, `..._V2_2025`, `..._2025_retificado_V3`). Os
marcadores aceitos ficam em `_SUFIXO_FINAL_RE` (`v2`, `ver 2`, `versao 3`,
`rev2`, `revisao 2`, `final`, `retificado/a`, `corrigido/a`, `atualizado/a`).
**Para aceitar um marcador novo, basta acrescentar a alternativa nessa regex** —
nenhum outro ponto do código precisa mudar.

O resultado é consultado em `APELIDOS_TABELA` (nomes de CSV e de aba) e em
`BASE_QUESTIONARIO_POR_TABELA` (questionários). O casamento é por chave
**inteira**, não por substring — por isso "Cadastro Escola Nova" não colide com
"Escola", nem "Gestor Escolar" com "Escola".

Os valores de `TABELAS` e `QUESTIONARIO_POR_TABELA` (com `_2025` no nome) são
**apenas ilustrativos**: nada casa por eles. Só as chaves de `TABELAS` são
usadas no código; `QUESTIONARIO_POR_TABELA` não é lido por ninguém — quem vale
é `BASE_QUESTIONARIO_POR_TABELA`.

Consequência prática: **é possível processar um dicionário e tabelas novos com
o Caderno e os questionários de um ano anterior.**

---

## 6. Recorte por tabela

Regra: **o filtro vale para os artefatos de dados, não para o documento de
consulta.**

- `.sav` e `.json` → só as tabelas selecionadas (no modo ZIP) ou enviadas (no
  modo por arquivos).
- `censo.html` → tudo que foi fornecido: todas as abas do dicionário, o Caderno
  inteiro e todos os questionários.

O dicionário é sempre lido por inteiro em `ler_dicionario`, e o recorte
acontece depois, em `executar`. Isso tem um efeito colateral desejável: o cache
`caderno_conceitos_metadados.json` é construído sempre sobre as seis tabelas,
então **não depende do recorte pedido em cada execução** — não há risco de um
cache "estreito" de uma execução anterior contaminar a seguinte.

### Caches

Ambos ficam na pasta de saída e evitam re-scraping do PDF:

| Arquivo | Conteúdo | Depende de |
|---|---|---|
| `caderno_conceitos_metadados.json` | conceitos alinhados por variável (`var_txt` etc.) | Caderno + dicionário |
| `censo_html_dados.json` | `conceitos` + `quadros` do `app-data` | Caderno |

Os dois são **versionados por impressão digital** (`censo_lib.fingerprint_fontes`,
SHA-256 do PDF + nomes das variáveis do dicionário), gravada no próprio arquivo:

```json
{ "_fingerprint": "3b3d06ccb0e7f1b1", "dados": { "...": "..." } }
```

`ler_cache_versionado` só reaproveita o cache quando a impressão digital bate.
Caches em formato antigo (sem `_fingerprint`) ou corrompidos são recusados e
refeitos — o comportamento seguro, já que podem ter vindo de outra edição.

Antes a invalidação era por **mera existência do arquivo**: na interface isso
ficava mascarado (pasta de saída temporária a cada execução), mas em uso
standalone com pasta fixa, alimentar o Caderno de 2026 reaproveitava
silenciosamente os conceitos de 2025.

---

## 7. Bytes vs. caracteres no SPSS (crítico)

**Toda largura do formato SPSS é medida em bytes; todo `tamanho` do dicionário
do INEP é medido em caracteres.** Em português, com acentos, os dois divergem —
e essa divergência já causou dois incidentes de importação (§8.3 e §8.4).

### 7.1 Rótulos

| Rótulo | Limite | Constante |
|---|---|---|
| de variável | 256 bytes | `LIMITE_ROTULO_VARIAVEL` |
| de valor | 120 bytes | `LIMITE_ROTULO_VALOR` |

Limites confirmados empiricamente contra o readstat: acima deles, ele trunca
por conta própria — no byte exato do limite, **sem respeitar fronteira de
caractere**.

Por isso `truncar()` corta por bytes e reserva espaço para as reticências. A
garantia que ele oferece: o readstat nunca precisa truncar nada, logo nunca
parte um caractere multibyte ao meio.

Um rótulo de 254 caracteres com acentos ocupa 258 bytes.

### 7.2 Dados de texto

O formato `A<n>` de uma variável string também conta **bytes**. Declarar
`A{tamanho}` direto do dicionário faz o formato mentir sobre o dado: o valor
`"2115 ET 4ª"` tem 10 caracteres mas 11 bytes, e um leitor que fatie a string
pela largura declarada corta no meio do `ª` (C2 AA).

Por isso `construir_meta_sav` recebe `larguras_bytes` (de
`largura_bytes_colunas`) e declara sempre
`A{max(tamanho_do_dicionario, bytes_reais)}`. A largura declarada nunca é menor
que o dado.

> Detectar coluna de texto por `dtype == object` **não é confiável**: conforme
> a versão e as opções do pandas, texto pode vir como `object` ou como dtype
> `str`. O código testa `not is_numeric_dtype(...)`.

---

## 8. Histórico de alterações

### 8.1 Modo de entrada por arquivos separados

**Motivação.** Chegou um dicionário novo e tabelas novas, mas o Caderno e os
questionários continuavam sendo os do ano anterior — não havia como montar um
`.zip` no formato oficial para alimentar o ETL.

**O que mudou.**

- `app.py` ganhou um seletor de modo. No modo novo, quatro uploads obrigatórios
  (dicionário, CSVs, Caderno, questionários), materializados em disco
  preservando o **nome original** — o nome é o que identifica a tabela e o
  questionário. *(Caderno e questionários deixaram de ser obrigatórios em
  §8.6.)*
- As tabelas processadas passam a ser derivadas dos CSVs enviados. A interface
  confirma o que reconheceu e avisa sobre CSVs fora do padrão.
- Identificação ano-agnóstica em `censo_lib.py` (§5): `_chave_arquivo`,
  `APELIDOS_TABELA`, `identificar_tabela`, `mapear_csvs`, `localizar_csv`,
  `BASE_QUESTIONARIO_POR_TABELA`, `localizar_questionario`.
- `ler_dicionario` casa as abas pela mesma normalização, tolerando variação de
  grafia entre edições do dicionário.
- `popular_sav.executar` localiza o CSV por `localizar_csv` em vez de montar o
  caminho com o nome fixo de 2025.
- `gerar_json_metadata_editor.executar` recebe `tabelas_alvo` (§6). Isso passou
  a valer **também no modo ZIP**: antes, o multiselect controlava só os `.sav`
  e os seis JSONs saíam sempre.
- O empacotamento passou a filtrar `*_import_metadata_editor.json`, mantendo os
  caches fora do pacote.

### 8.2 Dicionário no `censo.html`

**Motivação.** O Caderno e os questionários já estavam no `censo.html`; o
dicionário, não — apesar de ser a principal fonte dos metadados.

**O que mudou.**

- `montar_dicionario_html()` estrutura as abas do dicionário para o `app-data`
  (reaproveitando a leitura que já alimenta os JSONs — o `.xlsx` não é lido
  duas vezes).
- `gerar_censo_html()` recebe o parâmetro `dicionario`.
- `templates/censo_template.html` ganhou o modo **"Dicionário de Variáveis"**:
  uma aba por tabela, um card por variável com nome, descrição, tipo, tamanho,
  ordem, anos de coleta, categorias/rótulos, notas e aplicabilidade — tudo
  coberto pela busca global e por expandir/recolher.

**Correção de robustez colhida no caminho.** O template inicializava
`activeQuadro = quadros[0].id`, que estourava quando não havia quadros. Agora
cada modo é escondido se sua fonte estiver vazia, e a página abre no primeiro
modo disponível.

### 8.3 Falha de importação no Metadata Editor

**Sintoma.** `Tabela_Escola.sav` retornava HTTP 500; `Tabela_Turma.sav`
retornava *"Failed to read SAV file with any encoding … Unable to convert
string to the requested encoding (invalid byte sequence)"*. As outras quatro
importavam normalmente.

**Causa raiz.** `truncar()` limitava rótulos por **caracteres**, enquanto o
SPSS limita por **bytes** (§7). Com acentos, rótulos passavam do limite e quem
cortava era o readstat — no byte 256 exato, no meio de um caractere multibyte.
O caractere partido era justamente o `…` que o próprio `truncar` acrescentava
(3 bytes: `E2 80 A6`), deixando o `E2` órfão dentro do arquivo:

```
b' em mais \xc3\xa1reas\xe2\x07\x00\x00\x00'
                            ^^^^ byte-líder sem continuação → UTF-8 inválido
```

O pyreadstat tolera isso na leitura (por isso o arquivo abria localmente); um
leitor estrito rejeita.

A correlação com o sintoma fecha: **escola** tinha 15 rótulos de variável acima
de 256 B e 23 rótulos de valor acima de 120 B, dois deles partindo caractere.
**Docente, gestor e curso técnico** tinham zero estouros — e foram exatamente
os que importaram.

**Correção.** `truncar()` passou a cortar por bytes, com reserva para as
reticências, usando `decode(errors="ignore")` para descartar um caractere
partido pela fatia. Resultado verificado: o readstat não trunca mais nada e os
rótulos chegam ao arquivo byte a byte idênticos aos enviados, nas seis tabelas.

**Compressão.** `gravar_sav` passou a usar `row_compress=True` — a compressão
de linha do próprio formato SPSS (o padrão quando o SPSS salva; **não** é
ZSAV). Reduz drasticamente o tamanho sem alterar dados ou metadados, o que
endereça o 500 na escola:

| tabela | antes | depois |
|---|---:|---:|
| escola | 717,5 MB | 157,9 MB |
| matrícula | 326 MB | 54,9 MB |
| turma | 261,9 MB | 36,9 MB |
| docente | 215 MB | 30,0 MB |
| gestor | 90 MB | 15,2 MB |
| curso técnico | 22 MB | 3,7 MB |

**Ponto em aberto — turma.** A falha da escola está provada com reprodução
direta do byte inválido. A da turma **não**: o arquivo dela já era UTF-8 válido
antes da correção (o rótulo de 261 B era truncado pelo readstat, mas o corte
caía por sorte numa fronteira limpa) e lia sem erro. A hipótese é que a
mensagem exibida seja secundária — o Metadata Editor tenta uma lista de
encodings e reporta o *último* erro, e uma tentativa em cp1252 **sempre** falha
com essa exata mensagem num arquivo UTF-8 válido (confirmado em teste). Turma
era a última da fila, logo após a escola ter derrubado o worker com 500. Se
turma voltar a falhar sozinha, com escola passando, o problema é outro.

### 8.4 Segunda falha da escola — largura declarada dos dados de texto

**Sintoma.** Mesmo após §8.3, a escola continuou falhando com *"Unable to
convert string to the requested encoding (invalid byte sequence)"*. O suporte
observou que outros arquivos SAV importavam normalmente e suspeitou de "algum
string comprometendo o processo".

**Causa raiz.** A correção anterior tratou os **rótulos**; o mesmo defeito de
bytes-vs-caracteres persistia nos **dados**. `construir_meta_sav` declarava
`variable_format = f"A{tamanho}"` com o `tamanho` do dicionário (caracteres),
enquanto `A<n>` conta bytes. Quatro colunas da escola guardavam valores mais
longos em bytes que a largura declarada:

| coluna | declarado | bytes reais |
|---|---|---|
| `NO_ENTIDADE` | A100 | 101 |
| `NU_ENDERECO` | A10 | 11 |
| `DS_COMPLEMENTO` | A20 | 21 |
| `NO_BAIRRO` | A50 | 51 |

Os dados em si não eram truncados (o readstat dimensiona o armazenamento pelo
conteúdo), mas o **formato gravado no arquivo mentia sobre eles**. Varrendo os
555.187 valores de texto distintos da escola, três caem exatamente na fronteira
com um caractere de 2 bytes:

| coluna | formato | valor | fronteira |
|---|---|---|---|
| `NU_ENDERECO` | A10 | `2115 ET 4ª` | `4` + `C2` \| `AA` |
| `NU_ENDERECO` | A10 | `1381 ET 2ª` | `2` + `C2` \| `AA` |
| `DS_COMPLEMENTO` | A20 | `QUADRA AG-1, LOTE 4º` | `4` + `C2` \| `BA` |

Um leitor que fatia a string na largura declarada corta o `ª`/`º` ao meio e
obtém a sequência inválida. As demais tabelas não têm colunas de texto longas o
bastante para isso — por isso só a escola falhava.

**Correção.** `largura_bytes_colunas()` mede o comprimento real em bytes de
cada coluna de texto e `construir_meta_sav` passa a declarar
`A{max(dicionário, bytes reais)}` (§7.2). Na escola, `NU_ENDERECO` virou A11,
`DS_COMPLEMENTO` A22, `NO_BAIRRO` A51 e `NO_ENTIDADE` A101; as colunas com
folga (ex.: `NO_MUNICIPIO`, A150) ficaram inalteradas.

**Hipóteses descartadas no caminho** (registradas para não serem reinvestigadas):

- *Encoding cp1252 lido como latin-1.* O CSV da escola não tem **nenhum** byte
  na faixa 0x80–0x9F, então é latin-1 legítimo e a leitura está correta. As
  "aspas adicionais" levantadas pelo suporte não existem nos dados.
- *Truncamento dos dados pelo formato declarado.* O readstat dimensiona o
  armazenamento pelo conteúdo, não pelo `variable_format` — os valores
  chegam íntegros ao arquivo. O problema é só o formato declarado.

### 8.5 EM ABERTO — HTTP 500 na escola

**Estado atual.** Depois de §8.3 e §8.4, a mensagem de encoding desapareceu: a
escola passou a falhar apenas com `Request failed with status code 500`.

**O que isso significa.** Um 500 puro é exceção não tratada no servidor, sem
diagnóstico. Vale registrar que **a escola já retornava 500 na primeiríssima
tentativa**, antes de qualquer correção — ou seja, o 500 sempre foi um problema
distinto do de encoding, que apenas ficou visível depois que o outro saiu da
frente.

**Auditoria estrutural do arquivo — nada encontrado.** Verificado no
`Tabela_Escola.sav` atual: nomes de variável sem duplicatas, sem exceder 64
bytes e todos no padrão SPSS; nenhuma coluna de texto vazia ou com formato
`A0`; rótulos de valor em variáveis de texto com chave string (correto);
`variable_display_width` entre 2 e 150 (máximo do SPSS é 255); leitura íntegra
com `user_missing` em `True` e `False`; e os 555.187 valores de texto distintos
sem estouro ou quebra de caractere.

**Hipótese em aberto: limite de recursos do servidor.** A escola é, com folga,
a maior tabela em células:

| tabela | linhas × vars | células | MB | importa? |
|---|---|---:|---:|---|
| escola | 214.192 × 367 | 78,6 M | 157,9 | **não (500)** |
| matrícula | 178.766 × 239 | 42,7 M | 54,9 | sim |
| turma | 178.772 × 192 | 34,3 M | 36,9 | sim |

O limite estaria entre 42,7 M e 78,6 M células (ou entre 55 MB e 158 MB).

**Reduções já aplicadas.** `row_compress` levou a escola de 717,5 MB para
157,9 MB (§8.3). O modo 2 (só as 302 colunas presentes no CSV, descartando 65
colunas que o modo 1 preenche com vazio) daria 144,8 MB — economia de apenas
8%, porque colunas vazias comprimem bem. Não foi adotado.

**Kit de bisecção.** `OUTROS/diagnostico_escola/` (fora do versionamento) traz
a mesma tabela em quatro
tamanhos, com **estrutura idêntica** (mesmas 367 variáveis, mesmos rótulos —
verificado); só muda a contagem de linhas:

| arquivo | linhas | MB |
|---|---:|---:|
| `Tabela_Escola_5k.sav` | 5.000 | 3,6 |
| `Tabela_Escola_50k.sav` | 50.000 | 35,9 |
| `Tabela_Escola_100k.sav` | 100.000 | 72,7 |
| `Tabela_Escola_COMPLETA.sav` | 214.192 | 157,9 |

Importar em ordem crescente responde a pergunta que não dá para responder deste
lado: se o de 5k falhar, o problema é **estrutural** (e independe do tamanho);
se falhar a partir de algum tamanho, é **limite de recursos** — e o ponto de
virada é o número a levar ao suporte. São arquivos de diagnóstico: descarte os
registros parciais do Editor depois do teste.

### 8.6 Usabilidade da interface

**Motivação.** O app funcionava, mas escondia do usuário coisas que ele
precisava saber: falhas parciais viravam uma linha de log que rolava e sumia,
erros chegavam como a mensagem crua da exceção, e a barra de progresso dava
65% antes do passo mais lento começar.

**O que mudou.**

- **Insumos opcionais.** Caderno e questionários saíram da lista de
  obrigatórios; cada um fica atrás de um checkbox que mostra/esconde o
  uploader. A validação obrigatória cobre só dicionário e CSVs.
- **Painel de cobertura de metadados**, exibido antes de processar: mostra
  quais campos serão preenchidos e quais ficarão vazios com a seleção atual.
  Antes o usuário só descobria que `var_concept` veio vazio ao abrir o
  resultado.
- **`SystemExit` passou a ser interceptado.** Os módulos do pipeline sinalizam
  entrada inválida com `sys.exit(mensagem)`, que `except Exception` não pega —
  essas falhas escapavam inteiramente do tratamento de erro da interface.
- **`explicar_erro`** traduz falhas conhecidas (zip corrompido, encoding, CSV
  malformado, memória insuficiente) em orientação acionável; o traceback
  completo vai para o log.
- **Falhas parciais viram `st.warning` persistente**, guardado em
  `session_state`.
- **Progresso medido**, com o passo 3 acompanhado tabela a tabela (callback
  `progresso` nos passos 2 e 3) e tempo decorrido.
- **Varredura prévia do zip** (`inspecionar_zip`): lê só o índice central,
  mostra o que foi identificado e restringe o multiselect às tabelas que têm
  CSV dentro do arquivo.
- **Modo de colunas exposto na interface** — o parâmetro `modo` de
  `popular_sav` estava fixo em 1 e não era alcançável pelo usuário.
- Diversos itens menores: limite de upload exibido, selecionar todas/limpar,
  legenda no botão desabilitado, aviso de execução longa, indicador de linhas
  omitidas no log, botão Cancelar.

**Pendência conhecida.** O botão **Cancelar** depende do comportamento do
Streamlit de abortar o script em execução quando o usuário interage com um
widget: interrompe no próximo ponto de verificação (entre tabelas), não
instantaneamente. Como tudo roda em `tempfile.TemporaryDirectory()`, nada fica
gravado. **Não foi testado sob carga real** — um cancelamento verdadeiramente
responsivo exigiria mover o pipeline para uma thread com sinalização
cooperativa.

### 8.7 Marcador de versão nos nomes de arquivo (`_V2`)

**Motivação.** O INEP passou a republicar arquivos com um marcador de versão
**depois** do ano: `Tabela_Curso_Tecnico_2025_V2.csv`. A normalização já
removia o ano, mas só quando ele era o último elemento do nome — com o `_V2`
no fim, o ano deixava de estar ancorado e o arquivo não era reconhecido.

**O que mudou.** `_chave_arquivo` passou a remover ano e marcador de versão
**em laço**, até o nome parar de encolher, o que torna ordem e repetição
irrelevantes (§5). Os marcadores aceitos ficam numa única regex,
`_SUFIXO_FINAL_RE`.

**Alcance.** Como toda identificação de arquivo passa por `_chave_arquivo`, a
correção valeu de graça para os CSVs, para as abas do dicionário, para os
questionários (`Escola 2025 V2.pdf`) e para a varredura de zip do `app.py`.

### 8.8 Qualidade dos metadados gerados

**Motivação.** Auditoria da saída real de 2025 (1.052 variáveis) revelou
contradições internas nos JSONs e metadados semânticos perdidos em silêncio.

**O que mudou.**

| Defeito | Correção |
|---|---|
| `var_intrvl` fixo em `"discrete"` para as 1.052 variáveis, contradizendo as 707 que o mesmo objeto marcava com `mean`/`stdev` | derivado de `sum_stats_options["mean"]` |
| Formato do JSON divergia do `.sav` em **100%** das numéricas (JSON `F{n}.0`, `.sav` `F8.2` do pyreadstat) | `censo_lib.formato_numerico` como fonte única, usada pelos dois |
| `LATITUDE`/`LONGITUDE` declaradas com zero casas decimais | `DECIMAIS_POR_VARIAVEL` → `F20.6` |
| `loc_width` fixo em 8 nas numéricas, contradizendo o `data_format` do próprio objeto | vem do `tamanho` do dicionário |
| `case_count` sempre 0 | regravado no passo 3 |
| Caches invalidavam por mera existência do arquivo | impressão digital das fontes (§6) |
| `Turma 2025.pdf` rendia 0 questões; 223 variáveis sem `var_qstn_qstnlit` | extrator por layout para questionário não numerado |
| `var_universe` guardava anos de coleta | recebe o universo da tabela; anos vão para `var_notes` |
| `var_concept` recebia parágrafos de até 1807 caracteres, duplicando `var_txt` | recebe o **título** do conceito |
| Casamento de questões calculado duas vezes | resolvido uma vez e reaproveitado |
| Sem trilha de auditoria dos casamentos heurísticos | `relatorio_casamento.csv` |

**Resultado medido.**

| Métrica | Antes | Depois |
|---|---|---|
| Incoerências `var_intrvl` × `sum_stats_options` | 707 | 0 |
| Divergência de formato JSON × `.sav` | 100% | 0 |
| Questões extraídas de `Turma 2025.pdf` | 0 | 16 |
| `var_qstn_qstnlit` em turma / curso_tecnico | 0/192, 0/31 | 28/192, 3/31 |
| Maior texto em `var_concept` | 1807 caracteres | 160 |
| Tempo de execução | 43,2s | 37,8s |

**Verificado que não houve dano aos dados.** Declarar formato numérico no
`.sav` era a única alteração com risco real; as 266 latitudes do recorte de
teste saem idênticas ao CSV de origem (diferença absoluta máxima = 0.0). O
formato governa exibição, não armazenamento.

**Decisões de conteúdo tomadas pelo usuário.** `var_universe` passou a receber
o universo por tabela (`UNIVERSO_POR_TABELA`) e `var_concept` o título curto do
conceito. Ambas dependiam de semântica DDI não verificável sem o `model.json`.

**O que continua limitado, e por quê.**

- **`matricula` segue sem conceitos do Caderno** (239 variáveis). Não é defeito
  de casamento: `TABELA_PARA_SECAO` a mapeia para a seção `pessoa_fisica`, mas
  nesta edição os microdados são agregados por escola — as descrições são
  contagens (*"Número de Matrículas da Educação Básica"*) e os conceitos
  disponíveis descrevem atributos de pessoa. Nada casa, corretamente. A
  diferença é que **agora isso é avisado**. Resolver de fato exige revisar
  `TABELA_PARA_SECAO` para a natureza agregada da publicação — decisão de
  conteúdo, não de código.
- **Turma recuperou 28 de 192 variáveis**, não todas. As demais são contagens
  (`QT_TUR_*`) sem campo correspondente no formulário. O extrator recupera o
  que existe no documento; não inventa o resto.
- **`model.json` do Metadata Editor não está no repositório**, embora seja
  citado no cabeçalho de `gerar_json_metadata_editor.py`. Sem ele, a
  conformidade de `var_universe`, `var_concept`, `var_catgry` e `var_sumstat` é
  leitura do padrão DDI, não verificação. Vale trazer uma cópia.

---

## 9. Verificação

O que foi executado para validar as alterações:

| Verificação | Como | Resultado |
|---|---|---|
| Detecção ano-agnóstica | nomes 2025/2026/2027, caixa alta, sem ano | 6/6 tabelas e questionários corretos; sem colisões |
| Interface — insumos opcionais | `AppTest`: boot nos dois modos, checkboxes, validação | Caderno/questionários não bloqueiam; uploaders somem ao desmarcar |
| Interface — painel de cobertura | `AppTest` com opcionais desmarcados | painel reflete o estado; sem exceção |
| Insumos opcionais no pipeline | passo 1 com `pasta_questionarios=None` e `caminho_caderno=None` | JSONs e `censo.html` gerados; campos correspondentes vazios |
| Callbacks de progresso | passos 2 e 3, 2 tabelas | chamados na ordem, com índice e total corretos |
| Modos de coluna 1 e 2 | mesma tabela, os dois modos | 367 vs 302 colunas em escola, como esperado |
| Inspeção de zip | estrutura real do INEP, zip sem opcionais, só `~$`, zip corrompido | dicionário/Caderno/6 questionários/6 tabelas; `~$` ignorado; `None` em zip inválido |
| Sufixo de versão (`_V2`) | 17 variantes (`_2025_V2`, `_V2_2025`, `_rev2`, `_retificada_V3`, …) + regressão dos nomes antigos | todos resolvem para a tabela certa; não reconhecidos seguem `None` |
| Coerência JSON x `.sav` | geração real de 2025 (1.052 vars) + `.sav` regerados no mesmo pipeline | 0 divergências de formato (antes: 100%) |
| `var_intrvl` x `sum_stats_options` | mesma execução | 0 incoerências (antes: 707) |
| Questionário não numerado | `Turma 2025.pdf` pelo extrator de layout | 16 rótulos extraídos; 28+3 variáveis recuperadas (antes: 0) |
| Integridade após declarar formato numérico | 266 latitudes do `.sav` vs. CSV de origem | diferença absoluta máxima = 0.0 |
| Versionamento de cache | PDF alterado, dicionário alterado, formato antigo, arquivo corrompido | invalidado corretamente nos 4 casos |
| `case_count` | `.sav` regerado | JSON = `meta.number_rows` |
| Pipeline com CSVs `_V2` | `Tabela_Curso_Tecnico_2025_V2.csv` e `Tabela_Escola_2025_V2.csv` reais | `.sav` gerados com as 150 linhas do arquivo `_V2` |
| Pipeline completo (arquivos separados) | `AppTest` do Streamlit, CSV renomeado para 2026 | pacote com 1 `.sav` + 1 `.json` + `censo.html` |
| Pipeline completo (ZIP) | `AppTest` com zip reduzido | sem regressão; filtro de tabelas respeitado |
| JS do `censo.html` | execução real em quickjs com DOM mínimo | 4 modos, abas, busca e expandir/recolher sem erro |
| Casos degenerados do HTML | só dicionário; só Caderno | modos vazios escondidos; sem crash |
| Truncamento por bytes | fuzz de 799 prefixos × 2 limites | zero violações de limite ou UTF-8 |
| Rótulos preservados | 6 tabelas com dados reais, releitura | 0 rótulos alterados pelo readstat |
| Leitura dos `.sav` | `user_missing` em `True` e `False` | 6/6 OK (as duas variantes que o Editor tenta) |
| Largura declarada dos dados | 567.426 valores de texto distintos, 6 tabelas | 0 estouros e 0 quebras de caractere |
| Auditoria estrutural da escola | nomes, larguras, rótulos, display widths | nenhuma anomalia (ver §8.5) |

A execução do JavaScript usou um venv isolado no scratchpad (quickjs), sem
tocar no `venv/` do projeto.

---

## 10. Operação

```bash
# interface (uso normal)
streamlit run app.py

# standalone, passo a passo
python gerar_json_metadata_editor.py dicionario.xlsx pasta_saida pasta_questionarios "Caderno.pdf"
python criar_sav_vazio.py pasta_json pasta_saida --tabelas escola turma
python popular_sav.py dados sav --modo 1 --tabelas escola turma
```

Dependências ([requirements.txt](requirements.txt)): `streamlit==1.58.0`,
`pandas==3.0.3`, `pyreadstat==1.3.5`, `openpyxl==3.1.5`, `pdfplumber==0.11.10`.

### Pontos de atenção

- **`pd.set_option("future.infer_string", False)`** no topo de `censo_lib.py`
  não é cosmético: os arrays de string apoiados em pyarrow (padrão do pandas 3)
  já causaram segfault em `libarrow.so` ao gravar com pyreadstat, em
  combinação com DataFrames de muitas colunas montadas por inserção individual.
  Não remova.
- **Limite de upload do Streamlit** é 200 MB por padrão. No modo por arquivos
  separados, os CSVs de escola (157 MB) e matrícula (91 MB) chegam perto. Para
  enviar vários de uma vez, ajuste `server.maxUploadSize` em
  `.streamlit/config.toml`.
- **`Turma 2025.pdf` não é numerado** e por isso passa pelo extrator de layout,
  que rende 16 rótulos de campo (contra 59 questões numeradas da Escola). Turma
  e curso técnico recuperam 28 e 3 variáveis com `var_qstn_qstnlit` — não
  todas, porque a maioria das suas variáveis são contagens `QT_*` sem campo
  correspondente no formulário. Ver §8.8.
- **`relatorio_casamento.csv` deve ser revisado antes de publicar.** Boa parte
  dos metadados semânticos vem de casamento por similaridade; o relatório é o
  que torna isso auditável.
- **Os textos de `UNIVERSO_POR_TABELA`** foram redigidos de forma conservadora
  e merecem revisão de quem conhece o domínio.
- **`QUESTIONARIO_POR_TABELA` é código morto** — ninguém lê essa constante.
  Quem vale é `BASE_QUESTIONARIO_POR_TABELA`. Mantida para não quebrar um
  eventual import externo.
- **Não versionar** `.zip`, `.sav` nem dados grandes — ver
  [.gitignore](.gitignore).
