# ETL do Censo Escolar — Documentação do Programa

Documentação de referência do serviço que transforma os insumos oficiais do
INEP (dicionário, Caderno de Conceitos e questionários) nos metadados
consumidos pelo **World Bank Metadata Editor**: os `.json` de importação, o
`censo.html` navegável e o `relatorio_casamento.csv`.

**O único insumo obrigatório é o dicionário de variáveis.** Os microdados não
são lidos e o serviço não produz mais `.sav` — ver **§8.11**, que documenta a
mudança e o que ela custa. Os scripts que geram `.sav` continuam no
repositório como ferramentas standalone (§3).

**Este é o documento de referência do projeto.** Onde ele divergir de qualquer
outro, este vale: foi escrito a partir do código atual e é revalidado a cada
alteração (§9).

O diagnóstico que motivou as alterações mais recentes está resumido no
histórico: **§8.6** (usabilidade da interface), **§8.7** (marcador de versão
nos nomes de arquivo), **§8.8** (qualidade dos metadados), **§8.11** (serviço
só de metadados) e **§8.12** (códigos especiais do dicionário) — cada uma com o
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
insumos INEP ────┼── Caderno .pdf ──────┤  (opcional)   ──► ETL ──► json/*_import_metadata_editor.json
                 └── questionários .pdf ┘  (opcional)              censo.html
                                                                   relatorio_casamento.csv
```

**Só o dicionário é obrigatório.** O Caderno e os questionários enriquecem os
metadados (`var_concept`, `var_txt`, `var_qstn_qstnlit`); sem eles o pipeline
roda e esses campos ficam vazios — ver §3 (painel de cobertura).

Os **microdados não são insumo**. Enviando o ZIP oficial do INEP, os CSVs de
dentro dele são ignorados: `app.py: extrair_insumos_zip` extrai apenas `.xlsx`
e `.pdf`. Duas consequências diretas:

- **`case_count` sai 0** em todos os JSONs. Só quem lê os dados conhece o
  número de linhas de cada tabela.
- **O ano da edição vem dos nomes dos insumos**, não de `NU_ANO_CENSO`
  (§4.0).

O serviço executa **um passo**:

| Módulo | Produz |
|---|---|
| `gerar_json_metadata_editor.py` | `*_import_metadata_editor.json` + `censo.html` + `relatorio_casamento.csv` |

`criar_sav_vazio.py` e `popular_sav.py` continuam no repositório, mas **fora do
serviço**: são ferramentas standalone para quem tem os microdados em mãos e
quer produzir os `.sav` a partir dos JSONs (§3, §10). A motivação e o custo da
mudança estão em §8.11.

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

Os nomes de CSV na tabela acima são o **padrão** publicado pelo INEP, listados
para referência: o serviço não lê CSVs (§8.11), mas o nome de cada um é o que
`datafile.file_name` declara (com a extensão `.sav`) e é o que os scripts
standalone procuram. Não há casamento literal: o ano e um eventual marcador de
versão (`_V2`, `_retificado`) são ignorados na identificação — ver §5.

`curso_tecnico` compartilha o questionário de Turma — por isso o `censo.html`
deduplica os PDFs antes de montar as abas. Esse questionário é o único **não
numerado** do conjunto, e depende do extrator por layout (§3).

---

## 3. Módulos

### `app.py` — interface Streamlit

Ponto de entrada (`streamlit run app.py`). Coleta os insumos, gera os metadados
em um diretório temporário e devolve um `.zip` para download.

Oferece **dois modos de entrada**:

- **ZIP oficial do INEP** — um único upload. Antes de processar,
  `inspecionar_zip` varre o índice do arquivo (sem extrair) e mostra o que foi
  identificado; os mesmos critérios são usados na extração. `ler_membro_zip`
  então lê **só o dicionário** de dentro do pacote, para descobrir quais
  tabelas ele traz. Na execução, `extrair_insumos_zip` extrai **apenas `.xlsx`
  e `.pdf`** — os CSVs de microdados ficam no arquivo, e a extração do pacote
  de 2025 cai de 84 MB para 26 MB de disco temporário (num pacote completo, de
  vários GB para dezenas de MB).
- **Arquivos separados** — um upload **obrigatório** (dicionário `.xlsx`) e
  dois **opcionais**, cada um atrás de um checkbox que mostra/esconde o
  uploader: Caderno `.pdf` e questionários `.pdf` (múltiplos).

**Sem dicionário a interface para.** Ele define o recorte, o ano e todo o
resto, então o app exibe "Aguardando o dicionário de variáveis (.xlsx)" e
`st.stop()` antes de oferecer qualquer opção — nos dois modos.

**As tabelas vêm das abas do dicionário.** `censo_lib.tabelas_do_dicionario`
lê só os NOMES das abas (`read_only`, sem carregar célula alguma) e devolve as
tabelas reconhecidas na ordem canônica; um `multiselect` (com "Selecionar
todas"/"Limpar seleção") escolhe o recorte. Antes eram os CSVs presentes no
pacote que definiam essa lista — sem eles, quem sabe o que existe é o
dicionário. Um `.xlsx` sem nenhuma aba reconhecível é erro explícito, não uma
lista vazia silenciosa.

Caderno e questionários são apenas fontes de metadados: sem eles o pipeline roda
normalmente, mas `var_concept` e `var_qstn_qstnlit` ficam vazios. O **painel de
cobertura** mostra essa consequência antes da execução, e um `st.warning`
persistente a repete no resultado:

```
Cobertura de metadados com a seleção atual
  ✅ nomes, tipos, rótulos e categorias — dicionário
  ❌ conceitos e definições (var_concept) — Caderno de Conceitos — ficará vazio
  ✅ perguntas literais (var_qstn_qstnlit) — questionários
  case_count sai 0 em todos os JSONs: o ETL não lê os microdados.
```

A última linha é fixa, não um estado a corrigir: sem os dados não há número de
linhas a declarar (§8.11).

No modo por arquivos, cada opcional fica atrás de um checkbox que **mostra ou
esconde o uploader** — desmarcar é a forma de dizer "não tenho este insumo".
Marcar o checkbox e não enviar o arquivo é ambíguo, então bloqueia com uma
mensagem pedindo o envio ou o desmarque. A validação obrigatória cobre **apenas**
o dicionário.

Uma opção de saída controla o pacote: `gerar_html` (censo.html). O **modo de
colunas** deixou de existir na interface — era o parâmetro `modo` de
`popular_sav`, que não é mais chamado (continua disponível no CLI do script).

`incluir_questionarios` é **travado em falso** quando nenhum questionário foi
fornecido: deixar a flag ligada faria o painel de cobertura discordar do
`censo.html` efetivamente gerado.

O pacote final contém `json/*_import_metadata_editor.json`, `censo.html` e
`relatorio_casamento.csv`. Os caches intermediários do Caderno
(`caderno_conceitos_metadados.json`, `censo_html_dados.json`) ficam de fora.

**Tratamento de erros.** Falhas de passo são traduzidas por `explicar_erro`
(mensagem acionável na tela, traceback completo no log). `rodar_passo`
intercepta `Exception` **e** `SystemExit` — os módulos do pipeline sinalizam
entrada inválida com `sys.exit()`, que `except Exception` não pega. Exceções de
controle do Streamlit (`RerunException`/`StopException`) continuam propagando,
que é o que permite o botão **Cancelar** funcionar.

**Falhas parciais.** As lacunas de cobertura (Caderno/questionários ausentes,
ano da edição não determinado) viram `st.warning` persistentes guardados em
`session_state` — sobrevivem ao rerun e continuam visíveis junto do botão de
download. Antes só apareciam como uma linha `[aviso]` dentro da janela de log,
que rolava e sumia: era possível ver "Concluído!" em verde com uma lacuna
silenciosa.

**Progresso.** A barra usa faixas ponderadas (`P_ENTRADAS`/`P_PASSO1`/
`P_EMPACOTE`). Sem a leitura dos CSVs, a execução passou de vários minutos para
segundos ou dezenas de segundos, e a barra deixou de precisar do
acompanhamento tabela a tabela do antigo passo 3. Mostra o tempo decorrido
junto do percentual.

**Outros detalhes da interface:** limite de upload exibido a partir de
`server.maxUploadSize`; rótulos amigáveis das tabelas via `ROTULO_TABELA`;
legenda explicando por que o botão "Processar" está desabilitado; indicador de
linhas omitidas quando o log passa de `LOG_MAX` (50) linhas.

A assinatura que invalida um resultado já gerado cobre **arquivos e opções** —
mudar um checkbox depois de processar descarta o resultado anterior, em vez de
deixar disponível um download que não corresponde mais à seleção.

### `censo_lib.py` — biblioteca compartilhada

Módulo mais pesado do projeto. Reúne:

- **Constantes das tabelas** — `ABA_PARA_ARQUIVO`, `TABELAS`, `NOME_TABELA`,
  `FID_POR_TABELA`, `ROTULO_TABELA`, `UNIVERSO_POR_TABELA`,
  `QUESTIONARIO_POR_TABELA` (esta última é **código morto**: quem vale é
  `ASSINATURA_QUESTIONARIO` — ver §5).
- **Identificação de insumos (§5)** — em três camadas.
  Nome: `tokens_arquivo`, `ASSINATURA_TABELA`, `ASSINATURA_QUESTIONARIO`,
  `identificar_tabela`, `identificar_questionario`, `pontuar_caderno`.
  Conteúdo: `ler_cabecalho_csv`, `identificar_tabela_por_cabecalho`,
  `identificar_tabela_por_colunas`, `_eh_caderno_pelo_texto`.
  Resolução com relatório: `resolver_csvs` (devolve camada, pontuação e
  conflito por arquivo), `mapear_csvs`, `localizar_csv`,
  `localizar_questionario`.
  Pacote inteiro: `classificar_nomes` (só strings — compartilhada pela prévia
  do zip e pela extração real) e `localizar_insumos` (árvore extraída).
  Dicionário: `tabelas_do_dicionario` (aceita caminho, `bytes` ou file-like;
  lê só os nomes das abas) — é o que define o recorte oferecido na interface
  desde que os CSVs deixaram de ser insumo.
- **Formato numérico declarado** — `DECIMAIS_POR_VARIAVEL`, `largura_variavel`,
  `decimais_variavel`, `formato_numerico`. Fonte **única** do formato: usada
  tanto pelo JSON quanto pela gravação do `.sav`, para os dois não divergirem
  (ver §4).
- **Valores especiais do dicionário (§4.1)** — `_MARCADORES_IMPUTACAO`,
  `_MARCADORES_NAO_RESPOSTA`, `classificar_codigo_especial`,
  `separar_codigos_especiais`, `descrever_imputacao` e `parece_sentinela`.
  Separam os códigos que **não são categoria** (88888 de valor extremo, 9 de
  "Não informado") dos que são.
- **Leitura de CSV** — `detectar_encoding` (valida o arquivo **inteiro** em
  `utf-8-sig`, `utf-8`, `cp1252`, `latin-1`), `detectar_delimitador` (`;`, `,`,
  tab ou `|`, contados fora de aspas), `ler_csv`. Tudo lido como string; a
  tipagem vem do dicionário. Ver §5.4.
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
  `var_txt` e `var_qstn_ivuinstr`), `indexar_conceitos`,
  `mapear_conceitos_para_concept` (alimenta `var_concept`) e `rotulo_conceito`
  (título em Title Case, só na saída do JSON — os títulos vêm em CAIXA ALTA do
  Caderno e continuam assim no `censo.html`).
- **Caches versionados** — `fingerprint_fontes`, `ler_cache_versionado`,
  `gravar_cache_versionado` (ver §6).
- **Gravação de SAV** — `truncar`, `largura_bytes_colunas`,
  `construir_meta_sav`, `gravar_sav`.
- **Pós-processamento** — `atualizar_case_count`, chamada por `popular_sav`
  (standalone) para regravar o total de linhas no JSON. O serviço não a
  aciona: sem os dados, `case_count` fica 0.

As partes de CSV e de gravação de SAV continuam mantidas e testadas: são a base
dos scripts standalone (§10) e do caminho de identificação por cabeçalho (§5).

### `gerar_json_metadata_editor.py` — o passo do serviço

Lê o dicionário `.xlsx` e monta um JSON por tabela no schema do Metadata Editor
(DDI-CodeBook 2.5). Também dispara a geração do `censo.html` e grava o
`relatorio_casamento.csv`.

```python
executar(caminho_xlsx, pasta_saida, pasta_questionarios=None, caminho_caderno=None,
         gerar_html=True, incluir_questionarios=True, tabelas_alvo=None)
```

`tabelas_alvo` restringe **apenas** quais tabelas viram JSON. O dicionário é
sempre lido por inteiro — ver §6. É o único passo que o serviço executa.

`ano` é passado pelo app (detectado uma vez, a partir dos nomes dos insumos); se
vier `None`, o próprio módulo tenta deduzi-lo dos nomes que recebeu.

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
                 titulo=..., dicionario=None) -> Path
```

Devolve o `Path` gravado. Devolvia `str`, e o chamador usa `.name` para logar o
resultado: o `AttributeError` caía no `except` que existe ali para falhar
graciosamente e virava **"[aviso] Não foi possível gerar censo.html"** — sobre
um arquivo que tinha acabado de ser gravado corretamente. O `censo.html` sempre
esteve no `.zip`; só o log mentia. Corrigido junto de §8.11, porque com o fim
dos `.sav` o `censo.html` passou a ser um dos dois artefatos principais.

### `criar_sav_vazio.py` — standalone

**Fora do serviço** desde §8.11; continua no repositório e funcional.

`executar(tabelas_alvo, pasta_json, pasta_saida, progresso=None) -> list[str]`
(tabelas com erro). Monta um DataFrame vazio com os dtypes corretos e grava via
`gravar_sav`. Parte dos JSONs já gerados: leia o nome do `.sav` de
`datafile.file_name` (`censo_lib.nome_sav_do_json`).

### `popular_sav.py` — standalone

**Fora do serviço** desde §8.11; continua no repositório e funcional.

`executar(tabelas_alvo, pasta_csv, pasta_sav, modo, progresso=None) -> list[str]`.

- **Modo 1** (padrão da interface): todas as variáveis do dicionário; colunas
  ausentes no CSV ficam vazias (`NaN` para numéricas, `""` para texto).
- **Modo 2**: só as colunas presentes no CSV; extras do CSV vão para o fim com
  tipo inferido.

O modo é escolhido por `--modo {1,2}` na linha de comando. Era um radio na
interface ("Colunas nos arquivos .sav"), removido junto com os `.sav`.

`processar_tabela` devolve o número de linhas gravadas e chama
`censo_lib.atualizar_case_count`, fechando o `case_count` do JSON. **É o único
caminho que preenche esse campo** — quem usa só o serviço fica com 0.

### Callback `progresso`

Opcional, chamado como `progresso(indice, total, tabela)` antes de cada tabela,
nos dois scripts de `.sav`. Existia para a interface mostrar avanço **medido**
em vez de estimado, já que a leitura dos CSVs dominava o tempo de execução.
Com os `.sav` fora do serviço, nenhum chamador o usa hoje; foi mantido porque é
opcional (`None` por padrão), não custa nada e volta a ser útil se os passos
forem reintegrados.

---

## 4. Formatos de saída

### 4.0 Nomenclatura dos artefatos

A saída segue a convenção da publicação do INEP, para que os metadados fiquem
ao lado dos microdados de origem sem ambiguidade:

```
ceb2025_microdados_tabela_gestor_escolar.sav
└┬┘└─┬┘ └────┬───┘ └────────┬──────────┘
 │   │       │              └─ BASE_ARQUIVO_SAIDA[tabela]
 │   │       └─ fixo
 │   └─ ano da edição, detectado
 └─ PREFIXO_EDICAO ("ceb", Censo da Educação Básica)
```

| artefato | nome | gerado pelo serviço |
|---|---|---|
| metadados | `ceb2025_microdados_tabela_gestor_escolar_import_metadata_editor.json` | sim |
| glossário | `ceb2025_censo.html` | sim |
| auditoria | `ceb2025_relatorio_casamento.csv` | sim |
| dados | `ceb2025_microdados_tabela_gestor_escolar.sav` | não — só standalone (§8.11) |

O `.sav` continua na tabela porque **é declarado**: `datafile.file_name` guarda
esse nome em todo JSON, e é por ele que o Metadata Editor amarra o metadado ao
arquivo de dados publicado. O ETL declara o nome sem produzir o arquivo.

A base de cada tabela está em `censo_lib.BASE_ARQUIVO_SAIDA`. Ela segue a
grafia do INEP nos CSVs, que difere da chave interna em um caso:
**`gestor` → `tabela_gestor_escolar`**.

Isso vale para **qualquer insumo**: um pacote no formato antigo
(`Tabela_Escola_2025.csv`, pasta `Anexos/`) também produz saída nesta
convenção. O nome de saída é decisão do ETL, não herança do nome de entrada.

**De onde vem o ano.** `detectar_ano_censo(pasta_csv=None, nomes_extra=...)`
tenta, nesta ordem:

1. o valor de **`NU_ANO_CENSO` nos próprios dados** — a fonte mais confiável,
   porque não depende de nome nenhum (qualquer coluna cujo nome contenha
   `ANO_CENSO` serve). Lê duas linhas do CSV, não o arquivo;
2. o ano no **nome dos CSVs**;
3. o ano em `nomes_extra` — dicionário, Caderno, questionários, nome do pacote.

**O serviço só alcança o passo 3**, porque não recebe `pasta_csv`: os
microdados não são insumo (§8.11). Os passos 1 e 2 permanecem no código e valem
para o uso standalone. Na prática a perda é pequena — tanto a publicação de
2025 (`ceb2025_*`) quanto a anterior (`*_2025.csv`) carimbam o ano no nome de
todos os insumos, inclusive do dicionário e do Caderno.

**O dicionário decide sozinho.** O app chama `detectar_ano_censo` em cascata:
primeiro só com o nome do dicionário; e só se ele não trouxer ano é que
Caderno, questionários e nome do pacote entram. A razão é o desempate: dentro
de uma mesma chamada, `detectar_ano_censo` escolhe o ano **mais frequente**, e
combinar um dicionário de 2026 com o Caderno e os cinco questionários de 2025
(§5.7) daria 6 × 2025 contra 1 × 2026 — saída carimbada com o ano errado.
Enquanto os CSVs eram lidos, `NU_ANO_CENSO` desempatava isso sem ambiguidade;
hoje a hierarquia faz esse papel, e é a escolha certa: a edição do metadado é a
edição do dicionário que o gerou.

Não determinado, a saída sai como `ceb_microdados_tabela_*` — **sem ano
inventado** — e a interface avisa, pedindo que o dicionário seja renomeado com
o ano.

**Fonte única do nome.** O ano é detectado **uma vez**, no início da execução, e
propagado para `executar(..., ano=...)`. O JSON grava o nome do `.sav` em
`datafile.file_name`; os scripts standalone leem esse campo
(`censo_lib.nome_sav_do_json`) em vez de recalcular, então um `.sav` gerado
depois não tem como divergir do metadado — ver §8.10.

### JSON de importação

Um arquivo por tabela: `ceb<ano>_microdados_<tabela>_import_metadata_editor.json`.

```json
{
  "datafile": { "file_id": "F5", "fid": "F5",
                "file_name": "ceb2025_microdados_tabela_gestor_escolar.sav",
                "labl": "Dicionário de Variáveis - Tabela de Gestor",
                "var_count": 65, "case_count": 0 },
  "variables": [ { "...": "35 campos por variável" } ]
}
```

> `case_count` aparece 0 acima e **assim permanece na saída do serviço**, que
> não lê os microdados (§8.11). Só `popular_sav.py`, rodado standalone sobre os
> dados, o regrava com o total real de linhas.

Campos por variável: `uid`, `sid`, `fid`, `vid`, `name`, `labl`, `sort_order`,
`var_intrvl`, `loc_width`, `var_invalrng`, `var_valrng`, `var_sumstat`,
`var_catgry`, `var_catgry_labels`, `var_format`, `var_format_original`,
`file_id`, `interval_type`, `sum_stats_options`, `var_concept`, `var_wgt_id`,
`var_universe`, `var_txt`, `var_security`, `var_notes`, `var_respunit`,
`var_qstn_preqtxt`, `var_qstn_qstnlit`, `var_qstn_postqtxt`, `var_forward`,
`var_backward`, `var_qstn_ivuinstr`, `var_codinstr`, `var_imputation`,
`var_derivation`.

`case_count` nasce 0 — o JSON é escrito sem que nenhuma linha de dado tenha
sido lida — e o serviço o entrega assim. `censo_lib.atualizar_case_count` o
regrava com o total real, mas quem a chama é `popular_sav.py`, fora do serviço
(§8.11). O painel de cobertura da interface declara isso antes de processar.

**Procedência dos campos preenchidos:**

| Campo | Fonte |
|---|---|
| `name`, `labl`, `var_format`, `loc_width`, `var_catgry_labels` | dicionário `.xlsx` |
| `var_universe` | `censo_lib.universo_publicacao(ano_do_dicionário)` |
| `var_notes` | notas do dicionário + anos de coleta + flag de descontinuidade |
| `var_invalrng` | códigos especiais do dicionário (§4.1) |
| `var_imputation` | os mesmos códigos, descritos por natureza (§4.1) |
| `var_txt` | Caderno (com a descrição do dicionário como reserva) |
| `var_qstn_ivuinstr` | Caderno (orientações de preenchimento + destaques "Importante!") |
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
  ficam em `var_notes`. O texto é `"Escola de Educação Básica declarada em
  {ano}"`, **igual nas seis tabelas** — nesta publicação a unidade de observação
  é a mesma nas seis (os microdados são agregados por escola; as variáveis de
  matrícula, docente e turma são contagens por escola). O `{ano}` sai da última
  coluna de "Coleta por ano" do dicionário, não do ano detectado para nomear a
  saída: é a planilha que define de que edição são as variáveis descritas.
  Sem ano legível, o texto cai para `UNIVERSO_SEM_ANO`, sem data.
- `var_concept` guarda o **título** do conceito (rótulo curto, como pede o DDI),
  não a definição — que continua em `var_txt`. Antes o mesmo parágrafo, de até
  1807 caracteres, ia nos dois campos.

### 4.0 Os dois campos de texto livre: quem lê cada um

`var_notes` ("Notas sobre as variáveis") e `var_qstn_ivuinstr` ("Instruções
para o entrevistador") têm **uma fonte cada**, e a divisão não é arbitrária —
é por destinatário:

| Campo | Fonte | Quem lê |
|---|---|---|
| `var_notes` | coluna "Notas importantes" do dicionário `.xlsx` | quem **analisa** os microdados |
| `var_qstn_ivuinstr` | Caderno de Conceitos: orientações de preenchimento **e** destaques "Importante!"/"Você sabia?" | quem **preenche** o Educacenso |

Antes, os destaques do Caderno iam para `var_notes`. Eram o texto errado no
campo errado: falam com o declarante, não com o analista — *"é importante que
as secretarias estaduais e municipais de educação tenham especial atenção no
preenchimento (...) a cada coleta do Censo Escolar"*. Na edição 2025 isso move
40 blocos de texto de `var_notes` para `var_qstn_ivuinstr`; em 2 variáveis o
destaque se junta a uma orientação que já estava lá (orientação primeiro,
destaque depois, separados por quebra de linha). `var_qstn_ivuinstr` sai
preenchido em 101 variáveis, contra 63 antes.

`var_notes` continua recebendo também os anos de coleta (`Coletado em: …`) e a
flag de descontinuidade abaixo — os dois descrevem a variável para quem a
analisa, que é o critério do campo.

### 4.0.1 Variáveis descontinuadas

A matriz "Coleta por ano" do dicionário marca `"s"`/`"n"` por variável e por
ano. **Critério decidido em reunião:** `"n"` na coluna do ano do próprio
dicionário significa variável descontinuada naquele ano, e rende uma linha em
`var_notes`:

```
Variável descontinuada no ano de 2025.
```

O ano vem da última coluna da matriz — a mesma fonte do `{ano}` de
`var_universe`, para que os dois campos não possam discordar. Implementado em
`gerar_json_metadata_editor.nota_descontinuada`; a mesma flag é anexada à nota
do dicionário no `censo.html`, que é a face humana da mesma documentação.

Na edição 2025 são **85 variáveis**: 78 em Escola, 3 em Docente, 2 em Matrícula,
2 em Turma (Gestor e Curso Técnico, nenhuma).

⚠️ **O critério é deliberadamente literal.** Entre as 78 de Escola estão 9
campos de endereço (`DS_ENDERECO`, `NU_ENDERECO`, `DS_COMPLEMENTO`, `NO_BAIRRO`,
`CO_CEP` e afins) que aparecem com `"n"` em **todos** os anos da matriz — nunca
chegaram a ser publicados, então "descontinuada em 2025" descreve mal o caso
deles. A alternativa (exigir ao menos um `"s"` anterior) foi levantada e
**descartada**: vale a fidelidade ao critério acordado. Para essas 9, a nota do
próprio dicionário já explica a retirada por proteção de dados pessoais, e ela
aparece em `var_notes` logo acima da flag.

### 4.1 Valores especiais: imputação e não-resposta

O dicionário lista, na mesma coluna das categorias, códigos que **não são
categorias** — são marcas de que o valor observado não existe ou foi tratado.
No dicionário de 2025 são três:

| código | rótulo no dicionário | vars | tipo |
|---|---|---:|---|
| `88888` | "registro com marcação de valor extremo (…)" | 26 `QT_*` | imputação |
| `9` | "Não informado" | 20 `TP_*` | não-resposta |
| `99999999999999` | "Sem declaração" | 2 de CNPJ | não-resposta |

Tratá-los como categoria tem consequência concreta: `88888` entrando na média
de "quantidade de televisões" é a diferença entre **3,4 e 4.317,0**.

**O rótulo decide, não o número.** No mesmo dicionário, o código `8` de largura
1 é categoria real ("Área onde se localizam povos e comunidades tradicionais")
e o `9` da mesma largura é "Não informado". Nenhuma regra baseada na forma do
número separa os dois — por isso a classificação é feita por marcadores no
texto do rótulo (`censo_lib._MARCADORES_IMPUTACAO` e `_MARCADORES_NAO_RESPOSTA`,
comparados sem acento, sem caixa e com espaço normalizado).

Os marcadores são deliberadamente específicos: `"nao informad"`, não `"nao"` —
senão "Não oferece", "Não exclusivamente" e "Não há rede local interligando
computadores", todas categorias reais, seriam capturadas.

**Dois tipos, mesmo destino:**

| tipo | significado | `var_invalrng` | `var_imputation` |
|---|---|---|---|
| `imputacao` | o produtor **substituiu** o valor ao aplicar uma regra de consistência | sim | sim |
| `nao_resposta` | o valor **nunca foi declarado** (não informado / sem declaração) | sim | sim |

**Os dois entram em `var_imputation`.** É decisão registrada em reunião
(§8.12): todo código especial é resultado do processamento do INEP, e não
apenas o de valor extremo — são todos valores que o produtor **grava no lugar
da observação**. Uma primeira versão restringia `var_imputation` ao tipo
`imputacao`, por leitura estrita do DDI (`imputation` descreve o
*procedimento*); a leitura adotada é a outra.

O que a distinção de tipo preserva é a **redação**: `_FRASE_POR_TIPO` dá a cada
código a descrição correta da sua natureza, de modo que o texto publicado
continue verdadeiro frente ao dicionário.

```
Código 9: marca de ausência de declaração atribuída pelo produtor; no
dicionário de variáveis, “Não informado”. Código 88888: marca de tratamento de
consistência aplicada pelo produtor; no dicionário de variáveis, “registro com
marcação de valor extremo (…)”.
```

O texto é só a lista de códigos: a frase de abertura que remetia a
`var_invalrng` foi retirada, porque o mesmo conjunto de códigos já está
declarado lá e a remissão não acrescentava informação ao metadado.

O tipo também continua visível no `relatorio_casamento.csv`
(`88888=imputacao`, `9=nao_resposta`), que é onde a revisão confere código a
código — e é o que permite voltar atrás em uma linha, se a validação pendente
decidir o contrário.

**O rótulo é preservado.** Os códigos especiais continuam em
`var_catgry_labels` com o texto do dicionário — quem abre o metadado precisa
saber o que `88888` significa. O que muda é que passam a ser declarados
também em `var_invalrng`, que é como o Metadata Editor sabe excluí-los das
estatísticas. É a prática padrão em DDI/SPSS: rótulo de valor e declaração de
*missing* convivem.

**Efeito em `sum_stats_options`.** `determinar_sum_stats_options` passou a
contar apenas categorias **reais**. Isso corrigiu as 2 variáveis de CNPJ, cuja
única "categoria" era o `99999999999999`: pediam uma tabela de frequência de
200 mil CNPJs distintos, e agora ficam só com `missing`/`vald`.

**Auditoria (`parece_sentinela`).** A forma do número não classifica, mas
*audita*: um código que é repetição de 8 ou 9 com dois ou mais dígitos
(`88`, `999`, `8888`, `88888`) e cujo rótulo **não** casou com nenhum marcador
vira `[AVISO]` no log, nomeando variável, código e rótulo. É assim que uma
redação nova do INEP aparece em vez de passar calada como categoria:

```
[AVISO] Escola: 2 código(s) com forma de sentinela seguem valendo como
CATEGORIA REAL porque o rótulo não casou com nenhum marcador conhecido —
confira e, se for o caso, estenda censo_lib._MARCADORES_*:
QT_EQUIP_SOM:9999=“reservado”; QT_EQUIP_TV:88888=“codigo reservado (…)”
```

O piso de dois dígitos existe pelo mesmo motivo do `8`/`9`: com um dígito só, a
forma não informa nada.

**Como estender.** Redação nova do INEP → acrescente o trecho em
`_MARCADORES_IMPUTACAO` ou `_MARCADORES_NAO_RESPOSTA` (uma linha) e fixe o caso
em `testar_valores_especiais.py`.

**Pendência.** A classificação do `88888` como resultado de imputação segue a
posição registrada em reunião, **pendente de validação** com as áreas
responsáveis. O que está no código é a regra; mudar de posição é mexer em
`descrever_imputacao` e nos marcadores, não no resto do pipeline.

### `ceb<ano>_relatorio_casamento.csv`

Gerado junto dos JSONs, uma linha por variável, separador `;`, `utf-8-sig`
(abre direto no Excel pt-BR):

```
tabela;variavel;descricao;conceito;tem_var_txt;questao;score_questao;valores_especiais
```

`valores_especiais` lista o que saiu de categoria e virou valor inválido, no
formato `88888=imputacao` (vazio na maioria das linhas). Está aí porque essa
reclassificação muda como o Metadata Editor lê a variável e precisa ser
conferível na mesma planilha — ver §4.1.

Existe porque boa parte dos metadados semânticos vem de casamento por
similaridade e o log só mostra contagens agregadas. É o artefato para conferir,
variável a variável, o que foi atribuído e com que pontuação — **revise antes de
publicar**. Vai junto no `.zip` de download.

### `ceb<ano>_censo.html`

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

## 5. Identificação resiliente de insumos

### 5.1 O problema

O INEP não mantém convenção entre publicações. Para o **mesmo ano de coleta**
já circularam estas duas formas:

| | publicação "Anexos" | publicação "ceb2025_CSV" |
|---|---|---|
| CSV | `Tabela_Escola_2025.csv` | `ceb2025_microdados_tabela_escola.csv` |
| questionário | `Escola 2025.pdf` | `ceb2025_quest_escola.pdf` |
| dicionário | `Anexos/ANEXO I - Dicionário de Dados/` | `dicionario de dados/` |
| Caderno | `leia-me/Caderno de Conceitos e Orientações…pdf` | `leiame/ceb2025_cadastro_de_conceitos_e_orientacoes_do_censo.pdf` |
| delimitador | `;` | `,` |
| codificação | iso-8859-1 | UTF-8 com BOM |

Mudou tudo: prefixo de edição, **ano no meio do nome**, abreviação nova
(`quest`), nome de pasta, delimitador, codificação — e o Caderno saiu com
**"cadastro" no lugar de "caderno"**, erro de digitação da própria fonte.

Casar por chave inteira (a implementação anterior) reconhecia **zero** arquivos
da segunda forma. O pipeline não é resistente a *uma* mudança prevista: precisa
degradar bem diante de mudanças que ninguém previu.

### 5.2 A solução — três camadas

Da mais barata para a mais definitiva. A primeira que decide, decide.

**Camada 1 — nome como CONJUNTO de tokens.** `tokens_arquivo()` quebra o nome
em palavras, descarta acento, caixa, separadores, **ano em qualquer posição**,
números soltos e as palavras de embalagem de `_TOKENS_RUIDO` (`tabela`,
`microdados`, `censo`, `escolar`, `quest`, `v2`, `retificado`…). Sobra o
conjunto identificador, que é pontuado contra `ASSINATURA_TABELA` /
`ASSINATURA_QUESTIONARIO`:

```
"Tabela_Escola_2025"                  →  {escola}          →  escola
"ceb2025_microdados_tabela_escola"    →  {escola}          →  escola
"Tabela_Escola_2025_retificada_V3"    →  {escola}          →  escola
"Tabela_Gestor_Escolar_2025"          →  {gestor}          →  gestor
"ceb2025_quest_profissional_escolar"  →  {profissional}    →  docente
"Tabela_Curso_Tecnico_2025_V2"        →  {curso, tecnico}  →  curso_tecnico
"Cadastro Escola Nova 2025"           →  {cadastro, escola, nova}  →  (nenhuma)
```

Como é um **conjunto**, ordem e posição não importam — é isso que faz as duas
convenções colapsarem no mesmo resultado.

A pontuação penaliza os **excedentes**: `len(assinatura) / (len(assinatura) +
tokens_sobrando)`. É o que distingue um nome que É a coisa de um nome que
apenas a MENCIONA — `quest_escola` → 1.00, `cadastro_escola_nova` → 0.33
(abaixo de `LIMIAR_NOME = 0.50`, rejeitado). Sem isso, o formulário de cadastro
de escola nova seria confundido com o questionário da Escola.

**Camada 2 — conteúdo.** Quando o nome não decide, o **cabeçalho do CSV** é
comparado com as variáveis que o dicionário declara para cada tabela
(`identificar_tabela_por_cabecalho`). Medido no insumo real:

```
                        escola  matricula  docente  turma  gestor  curso_tec
escola.csv                1.00       0.09     0.09   0.09    0.09       0.09
matricula.csv             0.10       1.00     0.10   0.10    0.10       0.10
gestor_escolar.csv        0.28       0.28     0.28   0.28    1.00       0.28
curso_tecnico.csv         0.51       0.51     0.51   0.51    0.51       1.00
```

1.00 para a certa, ≤0.51 para todas as outras: separação larga. Exige
`LIMIAR_COLUNAS = 0.60` **e** `MARGEM_COLUNAS = 0.15` sobre a segunda colocada,
porque as seis tabelas compartilham o bloco de colunas geográficas. Pontua por
*containment* e não por Jaccard: uma publicação pode omitir colunas que o
dicionário lista sem deixar de ser aquela tabela (foi o caso do curso técnico —
20 colunas contra 31 no dicionário).

Só o cabeçalho é lido: as tabelas de matrícula e docente passam de 100 MB e a
identificação roda em todas.

**Consequência prática:** um pacote em que os CSVs se chamem `arquivo_00.csv`…
`arquivo_05.csv` é processado corretamente — verificado. Isso vale hoje para os
scripts standalone de `.sav`, os únicos que leem CSV (§8.11); o serviço de
metadados não passa por essa camada.

Para os PDFs o papel da camada 2 cabe ao texto da 1ª página
(`_eh_caderno_pelo_texto`), consultado só quando o nome não decide, porque
abrir PDF custa caro.

**Camada 3 — relatório.** `resolver_csvs()` devolve, junto com o mapa
`{tabela: caminho}`, um `detalhes` com `camada` (`"nome"` ou `"conteudo"`),
`pontos` e `conflito`. Quando nome e cabeçalho discordam **vale o cabeçalho** —
é evidência mais forte — e a discordância é impressa como aviso. Uma
identificação duvidosa fica auditável em vez de silenciosa, mesma filosofia do
`relatorio_casamento.csv`.

### 5.3 Localização dos insumos no pacote

`localizar_insumos(raiz)` acha dicionário, Caderno, pasta de CSVs e pasta de
questionários em uma árvore extraída. No serviço, `pasta_csv` volta `None` e é
ignorada: a árvore extraída não contém CSVs (§8.11). A função não mudou —
continua sendo a mesma usada pelos scripts standalone, que enxergam os dados. **Nada procura por nome de pasta** — a
estrutura já mudou de `Anexos/ANEXO I - Dicionário de Dados/` para
`dicionario de dados/`. Procura-se o ARQUIVO em toda a árvore e as pastas são
deduzidas de onde os arquivos reconhecidos caíram (`_pasta_dominante`).

O núcleo é `classificar_nomes(nomes)`, que opera **só sobre strings** — nomes de
entrada de `.zip` ou caminhos relativos. É a mesma função usada pela prévia do
zip na interface (`app.py: inspecionar_zip`) e pela extração real, o que torna
impossível a prévia discordar do resultado.

O Caderno é pontuado por tokens com peso (`_TOKENS_CADERNO`), e **`caderno` não
é obrigatório** — `conceito` carrega o peso, justamente porque a publicação de
2025 saiu como "cadastro_de_conceitos". `_TOKENS_NAO_CADERNO` exclui os outros
PDFs que também citam "conceito"/"orientação" (notas técnicas, pareceres, RIP).

### 5.4 Delimitador e codificação

`detectar_encoding` valida o arquivo **inteiro** com um decodificador
incremental, em vez de só uma amostra: um arquivo latin-1 cujo primeiro acento
apareça depois do trecho amostrado passaria como UTF-8 e estouraria no meio da
leitura do pandas, com centenas de MB já processados. Custa 0,45 s em 165 MB.
A ordem é `utf-8-sig`, `utf-8`, `cp1252`, `latin-1`; a última decodifica
qualquer byte e é a rede de segurança.

`detectar_delimitador` conta `;`, `,`, tab e `|` **fora de aspas**, para que um
rótulo de coluna com vírgula no meio (`"Área, Curso"`) não inverta a contagem.

### 5.5 Como estender

Quase sempre basta uma linha:

| Mudança do INEP | Onde mexer |
|---|---|
| palavra de embalagem nova no nome (`"consolidado"`) | `_TOKENS_RUIDO` |
| palavra identificadora nova (`"matriculas"` → outro termo) | `ASSINATURA_TABELA` |
| questionário renomeado | `ASSINATURA_QUESTIONARIO` |
| Caderno com outro título | `_TOKENS_CADERNO` |
| delimitador novo | `detectar_delimitador` |
| redação nova de código especial (§4.1) | `_MARCADORES_IMPUTACAO` / `_MARCADORES_NAO_RESPOSTA` |

**Nada disso é necessário para os CSVs**: a camada 2 continua identificando-os
pelo cabeçalho sem nenhum ajuste — hoje só nos scripts standalone, que são os
únicos que leem dados.

### 5.6 Regressão

`testar_identificacao.py` fixa o comportamento sobre os nomes reais das duas
publicações mais variações hostis (plural, caixa, acento, marcador de versão em
qualquer posição, colisões por substring). Não depende de insumo em disco:

```bash
python testar_identificacao.py
python testar_valores_especiais.py   # §4.1 — códigos que não são categoria
```

Uma mudança futura de convenção que o sistema não absorva quebra **aqui**, e não
no meio de um processamento de 500 MB.

`testar_valores_especiais.py` fixa a classificação dos códigos especiais pelos
rótulos reais de 2025 mais redações plausíveis, e trava explicitamente os dois
casos que uma regra ingênua erraria: o par `8`/`9` de largura 1, e as
categorias que começam com "Não" sem serem não-resposta ("Não oferece", "Não
há rede local interligando computadores").

### 5.7 Combinar insumos de anos diferentes

Continua valendo, e agora de forma mais ampla: **é possível processar um
dicionário novo com o Caderno e os questionários de um ano anterior** — e
também misturar as duas convenções de nome no mesmo lote.

O ano da saída é o **do dicionário** (§4.0): combinando um dicionário de 2026
com o Caderno e os questionários de 2025, a saída sai como `ceb2026_*`, que é o
correto — o metadado descreve a edição do dicionário, e os insumos antigos
entram só como fonte de texto. Se o dicionário não trouxer ano no nome, aí sim
os demais insumos decidem, e vale conferir o prefixo na saída.

Os valores de `TABELAS` e `QUESTIONARIO_POR_TABELA` (com `_2025` no nome) são
**apenas ilustrativos**: nada casa por eles. Só as chaves de `TABELAS` são
usadas no código.

---

## 6. Recorte por tabela

Regra: **o filtro vale para os artefatos por tabela, não para o documento de
consulta.**

- `.json` → só as tabelas selecionadas no multiselect (alimentado pelas abas do
  dicionário — ver §3).
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

Continua valendo integralmente mesmo sem os `.sav`: as larguras declaradas
(`loc_width`, `var_format`) e os rótulos truncados vão **no JSON**, e é o JSON
que o Metadata Editor importa. §7.2 é a parte que só afeta a gravação do
arquivo de dados, e portanto só os scripts standalone.

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

> **Fora do caminho do serviço desde §8.11.** Esta seção trata da importação do
> `.sav` da escola, que o ETL não produz mais. Os **metadados** da escola
> importam normalmente. O item continua aberto porque vale para quem gera o
> `.sav` pelos scripts standalone, e porque o diagnóstico acumulado aqui não
> deve ser perdido.

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
  uploader. A validação obrigatória cobre só dicionário e CSVs. *(Os CSVs
  saíram da lista em §8.11; hoje só o dicionário é obrigatório.)*
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
  `progresso` nos passos 2 e 3) e tempo decorrido. *(Os passos de `.sav` saíram
  do serviço em §8.11; restou o tempo decorrido.)*
- **Varredura prévia do zip** (`inspecionar_zip`): lê só o índice central,
  mostra o que foi identificado e restringe o multiselect às tabelas que têm
  CSV dentro do arquivo. *(Desde §8.11 o multiselect é alimentado pelas abas do
  dicionário; a varredura prévia continua, e os CSVs aparecem listados como
  ignorados.)*
- **Modo de colunas exposto na interface** — o parâmetro `modo` de
  `popular_sav` estava fixo em 1 e não era alcançável pelo usuário. *(Removido
  da interface em §8.11, junto com os `.sav`; segue no CLI do script.)*
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
| `case_count` sempre 0 | regravado por `popular_sav` *(fora do serviço desde §8.11 — volta a sair 0)* |
| Caches invalidavam por mera existência do arquivo | impressão digital das fontes (§6) |
| `Turma 2025.pdf` rendia 0 questões; 223 variáveis sem `var_qstn_qstnlit` | extrator por layout para questionário não numerado |
| `var_universe` guardava anos de coleta | recebe o universo da publicação, ancorado no ano do dicionário; anos vão para `var_notes` |
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

### 8.9 Segunda convenção de nomes do INEP — identificação em camadas

**Sintoma.** Uma segunda publicação do Censo 2025 (`ceb2025_CSV.zip`) chegou com
`ceb2025_microdados_tabela_escola.csv` no lugar de `Tabela_Escola_2025.csv`.
`mapear_csvs()` devolveu `{}` — **nenhum** dos seis CSVs foi reconhecido, e o
mesmo valeu para os seis questionários e para o Caderno de Conceitos.

**Diagnóstico.** `_chave_arquivo()` removia ano e marcador de versão apenas do
**final** do nome e consultava `APELIDOS_TABELA` por **chave inteira**. Com o
ano no prefixo e `microdados_` no meio, a chave virava
`ceb2025_microdados_tabela_escola`, ausente do dicionário de apelidos. A
detecção do Caderno era pior: exigia literalmente `"caderno"` e `"conceito"` no
nome, e a nova publicação trocou "caderno" por **"cadastro"** — erro de
digitação da fonte, que nenhuma lista de apelidos anteciparia.

Mudaram junto: estrutura de pastas (`Anexos/ANEXO I - …` → `dicionario de
dados/`), delimitador (`;` → `,`) e codificação (iso-8859-1 → UTF-8 com BOM).
Os dois últimos já eram detectados e passaram sem alteração.

**Causa raiz.** O reconhecimento dependia de o INEP manter uma convenção que ele
nunca prometeu manter. Cada correção pontual (o marcador `_V2` da §8.7 foi uma)
cobre a mudança já vista e nada da próxima.

**Correção.** Identificação em três camadas — nome como conjunto de tokens,
cabeçalho do CSV contra o dicionário, e relatório de proveniência. Detalhes na
§5. Pontos principais:

- o nome vira um **conjunto** de tokens significativos, então ano, prefixo de
  edição e palavras de embalagem deixam de importar em qualquer posição;
- a pontuação por excedentes mantém "Cadastro Escola Nova" fora do questionário
  da Escola, que era o motivo original de casar por chave inteira;
- quando o nome não basta, o **cabeçalho decide** — separação de 1.00 contra
  ≤0.51 no insumo real. CSVs chamados `arquivo_00.csv` são identificados
  corretamente;
- `classificar_nomes()` passou a ser a única implementação: a prévia do zip na
  interface e a extração real chamam a mesma função e não podem mais divergir
  (antes eram dois blocos de critérios duplicados em `app.py`);
- `detectar_encoding` valida o arquivo inteiro, não só uma amostra.

**Verificação.** `testar_identificacao.py` cobre as duas convenções e variações
hostis. O pipeline completo foi executado sobre as duas publicações: no insumo
novo, 88/88 colunas do gestor e 49/49 do curso técnico casaram com o dicionário;
no antigo, o resultado não mudou.

**Regressão em aberto.** Nenhuma. O único ponto que ainda exige nome legível é
o **dicionário `.xlsx`** — identificado pelo token `dicionario`, com fallback
para "o único `.xlsx` do pacote". Suas ABAS já são identificadas pela camada 1.

---

### 8.10 Nomenclatura da saída na convenção do INEP

**Motivação.** Os artefatos saíam como `Tabela_Gestor.sav` e
`gestor_import_metadata_editor.json` — três grafias diferentes para a mesma
tabela entre entrada, dados e metadados, e nenhuma delas identificando a
edição. Com duas publicações do mesmo ano circulando (§8.9), um `.sav` solto
não dizia de qual pacote veio.

**Bug encontrado no caminho.** O JSON declarava `"file_name": "gestor.sav"`
enquanto o arquivo gravado era `Tabela_Gestor.sav`. Os dois nomes eram
derivados **independentemente**: `montar_datafile` usava a chave interna
(`gestor`) e `criar_sav_vazio`/`popular_sav` usavam `NOME_TABELA`
(`Tabela_Gestor`). É por `file_name` que o Metadata Editor amarra o JSON ao
arquivo de dados, então o vínculo estava quebrado desde sempre.

**Correção.**

- A saída passou a seguir `ceb<ano>_microdados_<tabela>` (§4.0), inclusive para
  insumos no formato antigo — o nome de saída é decisão do ETL.
- O ano é detectado **uma vez**, preferindo `NU_ANO_CENSO` **nos próprios
  dados** ao nome dos arquivos. Sem ano determinável, sai `ceb_microdados_*`
  com aviso, em vez de um ano chutado.
- `datafile.file_name` virou a **fonte única** do nome do `.sav`: os passos 2 e
  3 leem esse campo (`nome_sav_do_json`) em vez de recalcular. A divergência
  deixou de ser possível por construção, não por coincidência.
- `encontrar_json` ganhou um fallback que varre `*_import_metadata_editor.json`
  e identifica cada um por `identificar_tabela` — assim os passos 2 e 3 acham o
  JSON sem conhecer o ano. Isso exigiu tratar `import`/`metadata`/`editor`/
  `sav`/`json` como tokens de ruído (§5.2), de modo que os artefatos que o
  próprio pipeline produz sejam reidentificáveis.

**Verificação.** `testar_identificacao.py` §7 cobre os nomes das seis tabelas,
os fallbacks de ano e o **round-trip** (todo artefato gerado volta a ser
identificado como sua tabela). O pipeline foi executado sobre as duas
publicações: em ambas o `file_name` do JSON aponta para um `.sav` que existe, e
`case_count` bate com as linhas do arquivo (180.540 no gestor, 32.136 no curso
técnico).

**Compatibilidade.** `encontrar_json` continua aceitando os nomes antigos, então
uma pasta de saída de uma execução anterior segue processável. `NOME_TABELA`
permanece no módulo, usado só por esse caminho de compatibilidade.

### 8.11 O serviço passou a ser só de metadados

**A mudança.** Os microdados deixaram de ser insumo e os `.sav` deixaram de ser
saída. O único insumo obrigatório passou a ser o **dicionário de variáveis**;
Caderno e questionários continuam opcionais, como já eram.

**Por quê.** O produto que o Metadata Editor consome é o `.json` de importação —
os `.sav` eram um segundo artefato, gerado no mesmo pipeline por conveniência.
Exigir as tabelas de dados para produzir metadados acoplava o serviço ao insumo
mais caro do pacote (centenas de MB por CSV, minutos de leitura, o limite de
upload de 200 MB do Streamlit) sem que nada nos metadados dependesse do
conteúdo delas — exceto `case_count`.

**O que saiu do serviço:**

| Antes | Agora |
|---|---|
| dicionário **e** CSVs obrigatórios | só o dicionário |
| tabelas derivadas dos CSVs presentes | tabelas derivadas das **abas do dicionário** |
| 3 passos (JSON → `.sav` vazio → `.sav` populado) | 1 passo (JSON + `censo.html` + relatório) |
| ZIP extraído por inteiro | só `.xlsx` e `.pdf` extraídos |
| pacote com `sav/`, `json/`, HTML, relatório | pacote com `json/`, HTML, relatório |
| radio "Colunas nos arquivos .sav" | removido (segue no CLI de `popular_sav`) |

**O que isso custa.** Duas perdas reais, ambas visíveis na interface:

1. **`case_count` sai 0** em todos os JSONs. Quem precisa do número real roda
   `popular_sav.py` standalone, que regrava o campo
   (`censo_lib.atualizar_case_count`). O painel de cobertura declara isso antes
   de processar, para não parecer um defeito do resultado.
2. **O ano perdeu a fonte mais confiável.** `NU_ANO_CENSO` lido dos dados não
   depende de nome nenhum; hoje o ano vem do nome do dicionário, com os demais
   insumos como fallback (§4.0). A hierarquia foi introduzida junto com esta
   mudança, porque o desempate por maioria quebraria o caso de §5.7.

**O que NÃO saiu.** `criar_sav_vazio.py`, `popular_sav.py` e todo o maquinário
de CSV e de gravação de SAV em `censo_lib.py` continuam no repositório,
funcionais e documentados (§3, §10). Eles partem dos JSONs gerados pelo
serviço: `datafile.file_name` segue declarando o nome do `.sav`, que é
justamente como o Metadata Editor amarra o metadado ao arquivo de dados. Nada
foi apagado — o caminho de dados foi **desacoplado**, não removido.

**Ganho medido.** Sobre o pacote de exemplo (`ceb2025_CSV.zip`, 84 MB):
extração de 84 MB para **26,2 MB** (13 arquivos, 0,1 s) e execução completa de
minutos para **40–47 s** com todos os PDFs, ou **menos de 1 s** com o
dicionário sozinho. Num pacote completo do INEP a diferença é de vários GB.

**Correção acoplada.** `gerar_censo_html` devolvia `str` e o chamador usa
`.name`: o `AttributeError` caía no `except` de falha graciosa e virava
"[aviso] Não foi possível gerar censo.html" sobre um arquivo gravado com
sucesso. Passou a devolver `Path`. O bug era anterior a esta mudança, mas o
`censo.html` deixou de ser um artefato secundário ao lado dos `.sav` — agora é
metade da saída, e um aviso falso sobre ele importa.

### 8.12 Códigos especiais deixaram de ser categoria

**Origem.** Posição registrada em reunião: tratar o código de valor extremo
como **resultado de imputação** (regra de consistência do INEP), e não apenas
como sentinela padrão. Pendente de validação com as áreas responsáveis — ver a
nota ao fim de §4.1.

**Alcance.** A decisão foi depois estendida aos **demais códigos especiais**: o
`9` de "Não informado" e o `99999999999999` de "Sem declaração" também entram
em `var_imputation`. O critério é que todos são valores que o produtor grava no
lugar da observação — a diferença entre "tratei o valor extremo" e "não me
declararam" fica na redação do texto, não em quais campos são preenchidos.

**O defeito.** O dicionário lista os códigos especiais na mesma coluna das
categorias, e o pipeline os tratava como categoria comum. Consequências no
metadado publicado:

| Sintoma | Efeito |
|---|---|
| `var_invalrng` sempre `{"values": []}` | nada declarava 88888/9/99999999999999 como valor a excluir |
| `var_imputation` sempre `""` | o tratamento aplicado pelo produtor não era registrado em lugar nenhum |
| 2 variáveis de CNPJ marcadas com `freq` | tabela de frequência de ~200 mil CNPJs distintos, porque o único "código" era o de "Sem declaração" |

Havia consciência parcial do problema: `PREFIXOS_CONTINUOS = {"QT"}` existia
**exatamente** para impedir que o 88888 tornasse as contagens categóricas. Era
uma correção pelo nome da variável, que resolvia as `QT_` e deixava passar tudo
o mais — os CNPJ, por exemplo.

**A correção.** Classificação por **rótulo**, em dois tipos, com destinos
distintos (§4.1). O que o INEP escreve ao lado do código é o que diz se ele é
categoria; a forma do número serve só para auditar o que escapou.

**Por que não pela forma do número.** Foi a primeira hipótese e ela não
sobrevive ao dado: no mesmo dicionário, `8` (largura 1) é
"Área onde se localizam povos e comunidades tradicionais" — categoria real — e
`9` (mesma largura) é "Não informado". Uma regra morfológica classifica os dois
igual e corrompe as 20 variáveis `TP_` que usam o `9`, ou perde todas elas.

**Efeito medido** (tabela de escola, 370 variáveis, dicionário 2025):

| Campo | Antes | Depois |
|---|---|---|
| `var_invalrng` preenchido | 0 | **48** (26 de consistência + 22 de não-resposta) |
| `var_imputation` preenchido | 0 | **48** |
| `sum_stats_options` com `freq` indevido | 2 (CNPJ) | **0** |
| `var_intrvl`, `var_catgry_labels`, demais campos | — | **inalterados** |

O diff é cirúrgico: nenhum outro campo de nenhuma outra variável mudou.

**Generalização.** A regra não conhece "88888". Conhece redações — inclusive as
que não aparecem em 2025 (`"8888"`, `"valor imputado"`, `"Ignorado"`, `"Sem
resposta"`). Um dicionário de outro ano ou de outra pesquisa do INEP que use
outro número com redação equivalente é tratado sem alteração de código; um que
use redação nova levanta `[AVISO]` nomeando variável, código e rótulo.

**Regressão.** `testar_valores_especiais.py`, 90+ casos, incluindo os dois
armadilhados: o par `8`/`9` e as categorias que começam com "Não" sem serem
não-resposta. Escreveu-se o teste antes de fechar a implementação, e ele achou
dois defeitos reais:

- rótulos com espaço interno duplo ("Não  informado", forma que sai de célula
  de Excel e de linhas concatenadas em `parse_categoria`) não casavam;
  `classificar_codigo_especial` passou a normalizar o espaço;
- ao estender `var_imputation` aos dois tipos, a abertura do texto ficou sem
  concordância ("O código abaixo **não é** … **são** atribuídos"). A abertura
  acabou retirada por inteiro (§4.1), e o teste passou a travar o que sobrou:
  o texto começa no primeiro código e não remete mais a `var_invalrng`.

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

Acrescentadas em §8.11 (serviço só de metadados):

| Verificação | Como | Resultado |
|---|---|---|
| `tabelas_do_dicionario` | dicionário real de 2025, nas 3 formas (caminho, `bytes`, file-like) | as 6 tabelas, na ordem canônica, nos 3 casos |
| `tabelas_do_dicionario` com lixo | `bytes` que não são `.xlsx` | lista vazia, sem exceção |
| Pipeline sem nenhum CSV | passo 1 direto, dicionário + Caderno + 5 questionários | 2 JSONs + `censo.html` + relatório; casamento idêntico ao de antes |
| Extração seletiva do zip | `ceb2025_CSV.zip` (84 MB) real | 26,2 MB / 13 arquivos em 0,1 s; `localizar_insumos` acha tudo menos `pasta_csv` (`None`, esperado) |
| Leitura do dicionário de dentro do zip | `ler_membro_zip` + `tabelas_do_dicionario` | 6 tabelas, sem extrair o pacote |
| Interface — boot | `AppTest`, os dois modos | sem exceção; para em "Aguardando o dicionário" nos dois |
| Pipeline completo (arquivos separados) | `AppTest` com uploads simulados, 2 tabelas | `2 .json + censo.html` em 40 s; zip sem `sav/` |
| Pipeline completo (ZIP) | `AppTest` com o zip real, 1 tabela | `1 .json + censo.html` em 47 s; CSVs do pacote ignorados |
| Caso mínimo (só dicionário) | `AppTest`, ambos os opcionais desmarcados | 1 JSON + HTML em 0 s; `var_concept`/`var_qstn_qstnlit` vazios; 2 avisos persistentes; `case_count` 0 |
| Ano em cascata | dicionário 2026 + Caderno e 5 questionários 2025 | `2026` (por maioria simples sairia `2025`) |
| Ano — fallback e ausência | dicionário sem ano; nenhum insumo com ano | cai nos demais insumos; `None` com aviso |
| Retorno de `gerar_censo_html` | execução real | `Path`; log passou de "[aviso] Não foi possível gerar" para `OK: ceb2025_censo.html` |
| Standalone a partir dos JSONs do serviço | `criar_sav_vazio.py` + `popular_sav.py` sobre a saída real do app | `.sav` de 51,5 MB com 180.540 linhas; `case_count` regravado no JSON do serviço |
| Regressão de identificação | `testar_identificacao.py` | todos os casos passaram (inalterado) |

Acrescentadas em §8.12 (códigos especiais):

| Verificação | Como | Resultado |
|---|---|---|
| Classificação sobre o dicionário real | 1.180 variáveis de 2025, 6 tabelas | 48 códigos classificados (26 imputação, 22 não-resposta); **0** escapes |
| Falso positivo crítico | código `8` = "Área onde se localizam povos e comunidades tradicionais" | segue categoria real; `var_invalrng` vazio |
| Categorias que começam com "Não" | "Não oferece", "Não exclusivamente", "Não há rede local…", "Não possui" | nenhuma classificada como não-resposta |
| Diff do JSON antes × depois | escola, 370 variáveis, campo a campo | só `var_invalrng` (48), `var_imputation` (26) e `sum_stats_options` (2 CNPJ); nada mais |
| `freq` indevido nos CNPJ | `NU_CNPJ_ESCOLA_PRIVADA`, `NU_CNPJ_MANTENEDORA` | `freq` removido; restam `missing`/`vald` |
| `var_imputation` cobre os dois tipos | variável com 88888 **e** 9 | ambos citados, cada um com a sua natureza |
| Concordância do texto gerado | 1 código × vários códigos | singular e plural corretos; travado no teste |
| Aviso de redação nova | dicionário falsificado: 88888 com rótulo desconhecido + 9999 "reservado" | `[AVISO]` nomeando as 2 variáveis, códigos e rótulos |
| Generalização | `"8888"`, "valor imputado", "Ignorado", "Sem resposta", caixa/acento/espaço | classificados corretamente |
| Regressão dedicada | `testar_valores_especiais.py` | todos os casos passaram |
| Pipeline completo | `AppTest`, escola | JSON + `censo.html`; 48 `var_invalrng`, 48 `var_imputation` |
| Natureza preservada no relatório | coluna `valores_especiais` | 26 `=imputacao`, 22 `=nao_resposta`, 322 vazias |

A execução do JavaScript usou um venv isolado no scratchpad (quickjs), sem
tocar no `venv/` do projeto. Os testes de interface usaram
`streamlit.testing.v1.AppTest` com os uploaders simulados a partir de
`exemplo_input/`.

---

## 10. Operação

```bash
# interface (uso normal) — só metadados
streamlit run app.py

# o mesmo, standalone
python gerar_json_metadata_editor.py dicionario.xlsx pasta_saida pasta_questionarios "Caderno.pdf"

# .sav, FORA do serviço (§8.11) — parte dos JSONs acima
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
- **Limite de upload do Streamlit** é 200 MB por padrão. Deixou de ser um
  problema no modo por arquivos, onde agora só entram o `.xlsx` e PDFs. Ainda
  vale para o modo ZIP: um pacote completo do INEP passa de 200 MB, e nesse
  caso ou se ajusta `server.maxUploadSize` em `.streamlit/config.toml` ou se
  usa o modo por arquivos separados, que é o caminho leve.
- **`case_count` sai 0** em todos os JSONs do serviço. É esperado, não defeito
  (§8.11): quem precisa do número real roda `popular_sav.py` standalone.
- **`Turma 2025.pdf` não é numerado** e por isso passa pelo extrator de layout,
  que rende 16 rótulos de campo (contra 59 questões numeradas da Escola). Turma
  e curso técnico recuperam 28 e 3 variáveis com `var_qstn_qstnlit` — não
  todas, porque a maioria das suas variáveis são contagens `QT_*` sem campo
  correspondente no formulário. Ver §8.8.
- **`relatorio_casamento.csv` deve ser revisado antes de publicar.** Boa parte
  dos metadados semânticos vem de casamento por similaridade; o relatório é o
  que torna isso auditável. A coluna `valores_especiais` mostra quais códigos
  saíram de categoria e viraram valor inválido (§4.1).
- **Códigos especiais são classificados pelo RÓTULO** (§4.1), nunca pela forma
  do número: `8` e `9` têm a mesma forma e papéis opostos no dicionário de
  2025. Redação nova do INEP levanta `[AVISO]` no log em vez de passar como
  categoria.
- **A leitura do `88888` como imputação está pendente de validação** com as
  áreas responsáveis (§8.12). É uma decisão de conteúdo, isolada em
  `censo_lib.descrever_imputacao` e nos marcadores.
- **Os textos de `UNIVERSO_POR_TABELA`** foram redigidos de forma conservadora
  e merecem revisão de quem conhece o domínio.
- **`QUESTIONARIO_POR_TABELA` é código morto** — ninguém lê essa constante.
  Quem vale é `BASE_QUESTIONARIO_POR_TABELA`. Mantida para não quebrar um
  eventual import externo.
- **Não versionar** `.zip`, `.sav` nem dados grandes — ver
  [.gitignore](.gitignore).
