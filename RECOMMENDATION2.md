# Recomendações — geração de metadados

Análise crítica do passo 1 do pipeline (`gerar_json_metadata_editor.py` +
as funções de casamento em [censo_lib.py](censo_lib.py)), com foco na
**qualidade dos metadados produzidos**, não na interface.

**Status: levantado e APLICADO em 03/08/2026.** Ver o registro de
implementação ao final. Os trechos de código e números citados ao longo do
documento descrevem o estado **anterior** à correção — servem como registro do
problema original.

Documento irmão: [RECOMMENDATION.md](RECOMMENDATION.md) — usabilidade da
interface Streamlit (já aplicado).

---

## Como estas conclusões foram obtidas

Execução real do gerador sobre os insumos de 2025 (dicionário + Caderno +
questionários completos), seguida de análise programática da saída:

- **1.052 variáveis** em 6 tabelas, 43,2s de execução;
- 72 conceitos e 6 quadros extraídos do Caderno;
- 123 perguntas extraídas de 4 questionários;
- comparação dos JSONs gerados contra os `.sav` correspondentes.

Os números citados abaixo vêm dessa execução.

---

## O que está bem resolvido

Registrado para não se perder em refatorações futuras:

- **O casamento muitos-para-um de conceitos está, em geral, CORRETO.** As 46
  variáveis `IN_*` que compartilham *"Devem ser informados os ambientes que
  existem na escola"* são itens de marcação de uma mesma questão — agrupá-las
  sob o mesmo conceito é o comportamento certo. O mesmo vale para as 27
  `QT_TUR_BAS_DISC_*` sob *"áreas do conhecimento"* e para as 16
  `QT_DOC_BAS_ESPEC_*` sob *"formação continuada"*.
- **As travas de qualidade de `_score_match` funcionam.** As regras (descrição
  com 1–2 palavras exige casamento total; 3+ exige ao menos 2; questão não pode
  ter mais de 8× o tamanho da descrição) rejeitam pares obviamente errados —
  pares improváveis testados manualmente pontuaram 0,000.
- **`construir_meta_sav` trata largura em BYTES vs CARACTERES corretamente** —
  ver o docstring em [censo_lib.py](censo_lib.py). É um detalhe sutil e está
  certo.
- **Degradação graciosa sem Caderno/questionários** já funciona: o pipeline
  roda e apenas deixa os campos correspondentes vazios.

---

## Achados críticos

### 1. O questionário de Turma extrai ZERO questões, silenciosamente

```
Escola 2025.pdf                ->  59 questões
Aluno 2025.pdf                 ->  22 questões
Profissional Escolar 2025.pdf  ->  23 questões
Gestor Escolar 2025.pdf        ->  19 questões
Turma 2025.pdf                 ->   0 questões   <-- 
Cadastro Escola Nova 2025.pdf  ->  17 questões   (nunca usado)
```

Não é falha de filtro. Instrumentando a extração no PDF de Turma:

- linhas que casam `_QUESTAO_RE`: **0**
- descartadas por `_texto_garbled`: 0
- descartadas por `_MULTI_QUESTAO_RE`: 0

O PDF de Turma simplesmente **não é numerado**. Suas linhas são rótulos secos
(`'Código da escola'`, `'Nome da turma'`, `'Tipo de mediação didático-pedagógica'`),
enquanto `_QUESTAO_RE` exige `^\s*(\d+[a-z]?)\s*[-–]\s+`.

**Impacto:** como `curso_tecnico` compartilha esse PDF, **223 variáveis**
(turma 192 + curso_tecnico 31) ficam com `var_qstn_qstnlit` vazio. O log
informa apenas um neutro `0 questões PDF` — indistinguível de "questionário não
enviado".

**Extra:** `Cadastro Escola Nova 2025.pdf` produz 17 questões que nunca são
usadas — nenhuma tabela mapeia para ele em `BASE_QUESTIONARIO_POR_TABELA`.

**Recomendação:** avisar alto quando um PDF de questionário render 0 questões
(é sempre sintoma de problema, nunca resultado esperado) e escrever um extrator
alternativo para questionários não numerados, baseado em layout.

---

### 2. O formato declarado no JSON contradiz o `.sav` — em 100% das numéricas

Comparação do JSON de `turma` contra o `.sav` gerado do mesmo pipeline:
**190 de 190 variáveis divergem.**

```
variável        JSON declara   loc_width   .sav real
NU_ANO_CENSO    F4.0           8           F8.2
CO_ENTIDADE     F8.0           8           F8.2
QT_TUR_BAS      F8.0           8           F8.2
LATITUDE        F20.0          8           F8.2
```

**Causa:** `construir_meta_sav` só define `formatos` para `Char`/`Data`
(`if tipo in ("Char", "Data") and var.get("tamanho")`), então o pyreadstat
aplica o padrão `F8.2` a todas as numéricas. Já `montar_var_format`
(`gerar_json_metadata_editor.py`) sempre emite `F{tamanho}.0`. As duas fontes
nunca se falaram.

Dois problemas adicionais no mesmo campo:

- **`LATITUDE`/`LONGITUDE` declaradas com ZERO casas decimais** (`F20.0`).
  Coordenadas geográficas são decimais por definição — o formato mente sobre o
  dado.
- **`loc_width` está fixo em 8** para as 1.024 variáveis numéricas, ignorando
  o `tamanho` do dicionário. Ou seja, contradiz o `data_format` *dentro do
  mesmo objeto*.

**Atenuante importante:** isso afeta apenas os metadados. Os **dados** do
`.sav` estão íntegros — os decimais de latitude/longitude são preservados,
porque nenhuma numérica recebe formato explícito na gravação.

**Recomendação:** definir também os formatos numéricos em `construir_meta_sav`,
para que JSON e `.sav` concordem por construção; derivar `loc_width` de
`tamanho`; e manter um conjunto de variáveis com casas decimais
(`LATITUDE`, `LONGITUDE`) para emitir `F{w}.{d}` com `d > 0`.

---

### 3. `var_intrvl` é `"discrete"` para todas as 1.052 variáveis

Enquanto isso, `sum_stats_options` marca **707 dessas variáveis** com
`mean`/`stdev` — isto é, declara-as contínuas. **O mesmo objeto JSON afirma as
duas coisas.**

```
Distribuição de var_intrvl no projeto inteiro: {'discrete': 1052}
Variáveis com mean/stdev mas var_intrvl='discrete': 707
```

`determinar_sum_stats_options` já sabe distinguir contínuas de categóricas
(prefixo `QT_`, `LATITUDE`/`LONGITUDE`, tipo `Data`, presença de categorias).
Os campos `var_intrvl` e `interval_type` simplesmente nunca receberam essa
informação — estão fixos em `"discrete"` no dicionário literal de
`montar_variavel`.

**Recomendação:** `var_intrvl = "contin"` quando `sum_stats_options["mean"]`
for verdadeiro, senão `"discrete"`. Reaproveita lógica que já existe; é a
correção de menor esforço e maior efeito deste documento.

---

### 4. `case_count` é sempre 0

```
curso_tecnico  var_count=  31  case_count=0
docente        var_count= 158  case_count=0
escola         var_count= 367  case_count=0
gestor         var_count=  65  case_count=0
matricula      var_count= 239  case_count=0
turma          var_count= 192  case_count=0
```

O JSON é escrito no **passo 1**, e as linhas só entram nos `.sav` no **passo
3**. `montar_datafile` fixa `"case_count": 0` e nada nunca volta para
preencher. Todo arquivo chega ao Metadata Editor declarando zero casos.

**Recomendação:** após o passo 3, reabrir cada JSON e gravar o número real de
linhas do `.sav` correspondente.

---

### 5. Os caches invalidam por existência, não por conteúdo

`caderno_conceitos_metadados.json` e `censo_html_dados.json` são reaproveitados
sempre que o arquivo existe:

```python
if caminho_cache.exists():
    print("  ... (scraping do PDF ignorado)")
    return json.load(fh)
```

Nenhum dos dois guarda impressão digital da origem — nem do PDF do Caderno, nem
do dicionário. E `mapear_conceitos_por_variavel` depende **dos dois**: trocar
só o dicionário também deveria invalidar o cache.

**Por que ainda não causou dano:** a interface Streamlit roda cada execução em
`tempfile.TemporaryDirectory()`, então o cache nasce e morre a cada run. O risco
está no uso standalone via CLI com uma pasta de saída fixa — ali, alimentar o
Caderno de 2026 **reaproveita silenciosamente os conceitos de 2025**.

**Recomendação:** gravar no cache um fingerprint (hash do PDF + hash/mtime do
dicionário + lista de tabelas) e descartar quando não bater.

---

## Achados moderados

### 6. `matricula` — 239 variáveis — fica sem nenhum metadado do Caderno

A segunda maior tabela termina com **0 conceitos** e **4/239 questões
casadas**, sem nenhum aviso.

```
tabelas no cache do Caderno: {'escola': 210, 'docente': 17, 'turma': 28, 'gestor': 16}
seções disponíveis no Caderno: escola=47, turma=11, pessoa_fisica=81 conceitos
```

`TABELA_PARA_SECAO` mapeia `matricula` → `pessoa_fisica`, que tem 81 conceitos
disponíveis. Mas nesta edição os microdados são **agregados por escola**: as
descrições são *"Número de Matrículas da Educação Básica"*, enquanto os
conceitos de `pessoa_fisica` descrevem atributos de pessoa (*"Nome completo"*,
*"Data de nascimento"*, *"Filiação"*). Nada casa — corretamente.

O problema não é o casamento, é que **o mapeamento pressupõe microdados
individualizados** e ninguém é avisado quando uma tabela inteira sai vazia.

Verificado que **não** há erro de atribuição de aba: dicionário e CSV batem em
100% das colunas do CSV em todas as tabelas conferidas.

**Recomendação:** emitir aviso explícito quando uma tabela termina com 0
conceitos ou 0 questões, e revisar `TABELA_PARA_SECAO` para a natureza agregada
desta edição.

---

### 7. `var_universe` guarda anos de coleta, não o universo

583 variáveis trazem `"Coletado em: 2007–2025"`; outras 170,
`"Coletado em: 2019–2025"`.

No DDI, *universe* descreve a população à qual a variável se refere ("escolas
em atividade", "alunos matriculados"). Anos de coleta são outra coisa — cabem
em `var_notes` ou num campo de período.

> ⚠️ **A confirmar contra o `model.json` do Metadata Editor**, que não está
> neste repositório. Se o schema do editor usar `var_universe` de forma mais
> frouxa, este item cai.

---

### 8. `var_concept` recebe parágrafos inteiros de definição

```
n=227 variáveis com conceito
tamanho do texto: min=62  mediana=197  max=1807 caracteres
acima de 500 caracteres: 52 variáveis
vocab='' e vocabURI='' em todas
```

O maior caso (1.807 caracteres, em `QT_PROF_SERVICOS_GERAIS`) é a definição
completa com lista de cargos. No DDI, `concept` é um **rótulo curto** ligado a
um vocabulário controlado (daí `vocab`/`vocabURI`, aqui sempre vazios). A
definição longa pertence a `var_txt` — que já recebe texto do Caderno por outro
caminho, de modo que o mesmo conteúdo acaba em dois campos.

**Recomendação:** colocar em `concept` o **título** do conceito do Caderno
(curto) e deixar a definição só em `var_txt`.

> ⚠️ Mesma ressalva do item 7: confirmar contra o `model.json`.

---

### 9. `encontrar_questao` roda duas vezes para cada variável

Em `gerar_json_metadata_editor.executar`:

```python
n_com_match = sum(
    1 for v in info["variaveis"]
    if encontrar_questao(v["descricao"], questoes)      # 1ª passada
)
...
caminho = gerar_json_importacao(..., questoes, ...)     # 2ª passada, idêntica
```

A primeira passada existe **só para imprimir um número no log**. Para `escola`
são 367 variáveis × 59 questões pontuadas duas vezes.

**Recomendação:** calcular o casamento uma vez, guardar, e usar o mesmo
resultado para o log e para o JSON.

---

### 10. Não há trilha de auditoria dos casamentos heurísticos

Cerca de metade dos metadados semânticos (`var_txt`, `var_concept`,
`var_qstn_qstnlit`, `var_qstn_ivuinstr`) vem de casamento por similaridade. A
única saída hoje é uma contagem agregada por tabela.

Não existe artefato que permita a um especialista de domínio conferir **qual
variável recebeu qual conceito, com que pontuação e de qual fonte** — que é
exatamente a revisão que este tipo de produto exige antes de publicar.

**Recomendação:** gerar um `relatorio_casamento.csv` com
`tabela, variavel, descricao, conceito_casado, score, questao_casada, score,
fonte`. É barato de produzir e transforma uma caixa-preta em algo revisável.

---

## Itens menores / latentes

- **`parse_categoria` converte códigos com `int()`.** Hoje inofensivo — conferi
  o dicionário de 2025 e **não há nenhum código com zero à esquerda**. Mas um
  código `"01"` viraria `1` e deixaria de casar com o dado do CSV. Códigos não
  numéricos são silenciosamente reclassificados como "nota" em vez de
  categoria, porque `CODE_RE` só aceita `-?\d+`.
- **`localizar_linha_cabecalho` levanta `ValueError`** quando uma aba não tem a
  linha `"N"`, e a exceção sobe sem tratamento por `ler_aba` → `ler_dicionario`
  → `executar`. Com o `explicar_erro` já aplicado na interface, ao menos chega
  traduzida ao usuário.
- **`var_catgry` e `var_sumstat` saem sempre `[]`** (só `var_catgry_labels` é
  preenchido). Provavelmente correto — o editor calcula essas estatísticas —
  mas vale confirmar no `model.json`.

---

## Prioridade sugerida

| # | Correção | Esforço | Efeito |
|---|---|---|---|
| 3 | `var_intrvl = "contin"` quando `sum_stats_options["mean"]` | Trivial | Corrige 707 variáveis |
| 9 | Calcular o casamento de questões uma única vez | Trivial | Menos trabalho, mesmo resultado |
| 2 | Alinhar formato numérico entre JSON e `.sav`; `loc_width` do `tamanho`; decimais para lat/long | Baixo | Corrige 100% das numéricas |
| 6 | Avisar quando uma tabela sai com 0 conceitos/0 questões | Baixo | Torna visível o item 1 e o 6 |
| 4 | Preencher `case_count` depois do passo 3 | Baixo | 6 arquivos corretos |
| 5 | Fingerprint nos caches | Baixo | Evita metadado de edição errada |
| 10 | `relatorio_casamento.csv` | Baixo | Torna o heurístico auditável |
| 1 | Extrator alternativo para questionário não numerado (Turma) | Médio | Recupera 223 variáveis |
| 7, 8 | Rever semântica de `var_universe` / `var_concept` | — | **Depende do `model.json`** |

**Sugestão de primeiro lote:** itens **3, 9 e 2** — são contidos, não dependem
de decisão externa e corrigem defeitos verificáveis em todas as tabelas.

---

## Pendência de informação

O `model.json` do World Bank Metadata Editor **não está neste repositório**,
embora seja citado no cabeçalho de `gerar_json_metadata_editor.py`. Os itens 7,
8 e a checagem de `var_catgry`/`var_sumstat` dependem dele. Vale trazer uma
cópia para o projeto — sem ela, a conformidade dos campos é suposição baseada
no padrão DDI, não verificação.

---

# Registro de implementação (03/08/2026)

Todos os 10 itens foram aplicados. Os itens 7 e 8 seguiram decisão do usuário
(ver abaixo), já que dependiam de semântica não verificável sem o `model.json`.

## Resultado medido — antes x depois

| Métrica | Antes | Depois |
|---|---|---|
| Incoerências `var_intrvl` x `sum_stats_options` | 707 | **0** |
| Divergência de formato JSON x `.sav` (escola) | 367/367 | **0/367** |
| Divergência de formato JSON x `.sav` (turma) | 190/190 | **0/192** |
| `LATITUDE`/`LONGITUDE` | `F20.0`, loc_width 8 | `F20.6`, loc_width 20 |
| `loc_width` das numéricas | fixo em 8 | 11 valores distintos, do dicionário |
| Questões extraídas de `Turma 2025.pdf` | 0 | **16** |
| `var_qstn_qstnlit` em turma | 0/192 | **28/192** |
| `var_qstn_qstnlit` em curso_tecnico | 0/31 | **3/31** |
| `case_count` | sempre 0 | nº real de linhas |
| Maior texto em `var_concept` | 1807 caracteres | 160 caracteres |
| Tempo de execução | 43,2s | 37,8s (PDF lido 1x em vez de 3x) |

## O que foi alterado

### `censo_lib.py`

| Item | Alteração |
|---|---|
| 2 | `DECIMAIS_POR_VARIAVEL`, `largura_variavel`, `decimais_variavel`, `formato_numerico` — fonte única do formato numérico |
| 2 | `construir_meta_sav` passa a declarar formato também para numéricas (antes só `Char`/`Data`) |
| 7 | `UNIVERSO_POR_TABELA` — universo estatístico de cada tabela |
| 1 | `extrair_questionario_layout` — extrator para questionário não numerado |
| 1 | `extrair_questionario_html` recorre ao extrator por layout e **avisa** quando nada é extraído |
| 10 | `encontrar_questao_com_score` — expõe a pontuação; `encontrar_questao` vira wrapper |
| 5 | `fingerprint_fontes`, `ler_cache_versionado`, `gravar_cache_versionado` |
| 5 | `obter_metadados_caderno` usa o cache versionado |
| 4 | `atualizar_case_count` |
| 8 | `rotulo_conceito` — Title Case só na saída do JSON |

### `gerar_json_metadata_editor.py`

| Item | Alteração |
|---|---|
| 2 | `montar_var_format` usa `formato_numerico`; `loc_width` vem de `largura_variavel` para todos os tipos |
| 3 | `var_intrvl`/`interval_type` derivam de `sum_stats_options["mean"]` |
| 7 | `var_universe` recebe o universo da tabela; anos de coleta migram para `var_notes` |
| 8 | `var_concept` recebe o **título** do conceito, não a definição |
| 9 | Casamento de questões calculado uma vez e reaproveitado no log, no JSON e no relatório |
| 5 | Cache do `censo_html_dados.json` versionado |
| 6 | Avisos explícitos quando uma tabela sai com 0 questões, 0 casamentos ou 0 conceitos |
| 10 | `gravar_relatorio_casamento` → `relatorio_casamento.csv` |
| — | `perguntas_do_pdf` memoriza a leitura de cada PDF (era lido 3x) |

### `popular_sav.py`

- `processar_tabela` devolve o nº de linhas e chama `atualizar_case_count` (item 4).

### `app.py`

- `relatorio_casamento.csv` entra no `.zip` de download.

## Decisões tomadas pelo usuário

- **Item 7** — anos de coleta movidos para `var_notes`; `var_universe` recebe o
  universo por tabela (`UNIVERSO_POR_TABELA` em `censo_lib.py`).
  ⚠️ **O texto do universo foi redigido de forma conservadora e precisa da sua
  revisão** — foi escrito para valer tanto para a publicação agregada por
  escola quanto para uma eventual individualizada.
- **Item 8** — `var_concept` passa a receber o título curto do conceito; a
  definição completa continua em `var_txt`.

## Efeitos colaterais avaliados

- **Declarar formato numérico no `.sav` NÃO altera os dados.** Verificado
  contra o CSV de origem: as 266 latitudes do recorte de teste saem idênticas
  (maior diferença absoluta = 0.0). O formato governa exibição, não
  armazenamento.
- **Caches antigos são recusados, não lidos errado.** Um
  `caderno_conceitos_metadados.json` sem `_fingerprint` é tratado como
  desatualizado e refeito — comportamento seguro, já que pode ter vindo de
  outro Caderno.
- **`censo.html` não mudou de aparência.** O Title Case do item 8 é aplicado só
  na saída do JSON; os títulos de conceito seguem em caixa alta no HTML, como
  no PDF original.

## O que continua limitado (e por quê)

- **`matricula` segue sem conceitos do Caderno** (239 variáveis). Não é defeito
  de casamento: as descrições são contagens agregadas
  (*"Número de Matrículas da Educação Básica"*) e os conceitos disponíveis
  descrevem atributos de pessoa. A diferença é que **agora isso é avisado em
  voz alta** em vez de passar como um "0" discreto. Resolver de fato exige
  revisar `TABELA_PARA_SECAO` para a natureza agregada desta edição — decisão
  de conteúdo, não de código.
- **Turma recuperou 28 de 192 variáveis**, não todas. As demais são contagens
  (`QT_TUR_*`) que não correspondem a campo nenhum do formulário. O extrator
  por layout recupera o que existe no documento; não inventa o resto.

## Como foi verificado

Execução completa sobre os insumos reais de 2025 (1.052 variáveis, 6 tabelas),
seguida de conferência programática:

- **Itens 1, 2, 3, 7, 8, 10** — comparação dos JSONs gerados contra os `.sav`
  regerados pelo mesmo pipeline; todas as asserções passaram.
- **Item 4** — `case_count` conferido contra `meta.number_rows` do `.sav`.
- **Item 5** — cache reaproveitado com entradas iguais; invalidado quando muda
  o PDF, quando muda o dicionário, quando está em formato antigo e quando está
  corrompido (sem estourar exceção).
- **Integridade de dados** — latitudes do `.sav` comparadas valor a valor com o
  CSV de origem.
- **Regressão** — as 5 suítes anteriores (nomes `_V2`, inspeção de zip,
  `AppTest` da interface, E2E de opcionais/callbacks, E2E `_V2`) seguem
  passando.
