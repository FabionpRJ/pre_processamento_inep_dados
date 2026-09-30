# Histórico de alterações

Registro das mudanças do ETL, com o diagnóstico e os números medidos de cada
uma. A especificação vigente está em [especificacao.md](especificacao.md);
este documento explica **como se chegou a ela**.

> **Nomes de código nas seções 8.1–8.12 e 9.** Elas descrevem o código anterior
> à refatoração de 2026-09 (§8.13), organizado em `censo_lib.py`,
> `gerar_json_metadata_editor.py`, `gerar_caderno_html.py` e nos scripts de
> `.sav`. As funções citadas existem hoje, com o mesmo comportamento, nos
> módulos de `censo_etl/` — a correspondência está na tabela de §8.13.
> Referências como "§4.0" ou "§7" apontam para a antiga `DOCUMENTACAO.md`;
> o conteúdo delas está em especificacao.md, identificacao.md e operacao.md.
>
> As notas de análise que originaram §8.6–§8.12 (`RECOMMENDATION.md` e
> `RECOMMENDATION2.md`) ficam em `OUTROS/`, fora do versionamento.

## 8.1 Modo de entrada por arquivos separados

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

## 8.2 Dicionário no `censo.html`

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

## 8.3 Falha de importação no Metadata Editor

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

## 8.4 Segunda falha da escola — largura declarada dos dados de texto

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

## 8.5 EM ABERTO — HTTP 500 na escola

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

## 8.6 Usabilidade da interface

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

## 8.7 Marcador de versão nos nomes de arquivo (`_V2`)

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

## 8.8 Qualidade dos metadados gerados

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

## 8.9 Segunda convenção de nomes do INEP — identificação em camadas

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

## 8.10 Nomenclatura da saída na convenção do INEP

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

## 8.11 O serviço passou a ser só de metadados

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

## 8.12 Códigos especiais deixaram de ser categoria

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

## 8.13 Refatoração do zero (2026-09)

**Motivação.** O código funcionava, mas estava concentrado em um módulo de
2.477 linhas (`censo_lib.py`) e numa função de ~270 linhas
(`gerar_json_metadata_editor.executar`); comunicava por `print()` capturado
com `redirect_stdout`, sinalizava erro com `sys.exit()` dentro de biblioteca,
passava `dict` soltos entre as etapas e acumulava comentários que contradiziam
o código.

**O que mudou.** Reescrita em um pacote, `censo_etl/`, com um módulo por
responsabilidade e sem alterar nenhum byte dos artefatos:

| Antes | Agora |
|---|---|
| 9 dicionários paralelos descrevendo as tabelas (`ABA_PARA_ARQUIVO`, `FID_POR_TABELA`, `TABELAS`, `NOME_TABELA`, `BASE_ARQUIVO_SAIDA`, `ROTULO_TABELA`, `ASSINATURA_*`, `TABELA_PARA_SECAO`, `QUESTIONARIO_POR_TABELA`) | um registro `Tabela` por tabela em `tabelas.py` |
| identificação por nome (`tokens_arquivo`, `_melhor_assinatura`, `pontuar_caderno`) | `nomes.py` |
| `classificar_nomes`, `localizar_insumos`, `localizar_questionario`, varredura/extração do zip (em `app.py`) | `insumos.py` (devolvem dataclasses) |
| `detectar_encoding`, `detectar_delimitador`, `resolver_csvs`, `identificar_tabela_por_cabecalho` | `leitura_csv.py` |
| `detectar_ano_censo`, `nome_saida*`, cascata do ano (em `app.py`) | `edicao.py` (`detectar_ano_em_cascata`) |
| `ler_dicionario`, `ler_aba`, `parse_categoria`, `tabelas_do_dicionario` | `dicionario.py`, com `Variavel` e `TabelaDicionario` |
| códigos especiais | `valores_especiais.py` |
| `formato_numerico`, `largura_variavel`, `DECIMAIS_POR_VARIAVEL` | `formato.py` |
| `extrair_questionario_html`/`_layout` | `pdf/questionarios.py` |
| `extrair_conceitos_pdf` | `pdf/caderno_secoes.py` (`extrair_secoes`) |
| `extrair_conceitos_html` | `pdf/caderno_conceitos.py` (`extrair_conceitos`) |
| `extrair_quadros_pdf` | `pdf/caderno_quadros.py` |
| `_score_match`, `_score_match_conceito`, `mapear_conceitos_por_variavel`, `mapear_conceitos_para_concept` | `casamento.py` (`pontuar_questao`, `pontuar_conceito`, `mapear_secoes_por_variavel`, `mapear_conceitos_por_variavel`) |
| `fingerprint_fontes`, `ler/gravar_cache_versionado` | `cache.py` |
| `montar_variavel`, `montar_datafile`, `determinar_sum_stats_options` | `metadata_editor.py` (`opcoes_estatisticas`) |
| `gravar_relatorio_casamento` | `relatorio.py` |
| `gerar_caderno_html.py`, `montar_dicionario_html`, `templates/` | `censo_html.py`, `censo_etl/templates/` |
| `gerar_json_metadata_editor.executar` | `pipeline.gerar_metadados` → `ResultadoExecucao` |
| `truncar`, `construir_meta_sav`, `gravar_sav`, `carregar_metadados`, `encontrar_json`, `atualizar_case_count` | `sav/gravacao.py`, `sav/metadados_json.py` |
| `criar_sav_vazio.py`, `popular_sav.py` | `sav/criar_vazio.py`, `sav/popular.py`; os scripts da raiz viram atalhos |
| `explicar_erro`, assinatura, empacotamento (em `app.py`) | `servico.py` |
| três `main()` com `argparse` | `cli.py` (`python -m censo_etl ...`) |
| `testar_*.py` com `checar()` caseiro | `pytest` em `tests/` |

Outras mudanças de forma:

- **`logging` no lugar de `print`.** Avisos saem com a etiqueta `[aviso]`; o
  pipeline também os devolve em `ResultadoExecucao.avisos`.
- **Exceção de domínio** (`EntradaInvalida`) no lugar de `sys.exit` na
  biblioteca; só o CLI converte em código de saída.
- **O pipeline não detecta mais o ano sozinho.** Quem chama (interface ou CLI)
  aplica a cascata e passa `ano`. Antes, `executar(ano=None)` voltava a
  detectar por maioria entre dicionário, Caderno e *nome da pasta* de
  questionários — o que podia divergir do ano usado pela interface para
  procurar o `censo.html` na hora de empacotar. Agora a interface empacota os
  caminhos que o pipeline devolve.
- **Memorização da normalização de texto** nos casamentos: a execução
  completa caiu de 39 s para 28 s, com saída idêntica.
- `use_container_width` (depreciado no Streamlit 1.58) trocado por
  `width="stretch"`.

**Removido:**

- `QUESTIONARIO_POR_TABELA`, valores de `TABELAS`, `NOME_TABELA`: código morto
  ou só de compatibilidade.
- `encontrar_json` não procura mais os nomes da primeira convenção
  (`escola_metadados.json`, com a chave `variaveis`) nem a pasta
  `saida_censo_escolar/` do diretório corrente. Os `*_import_metadata_editor.json`
  de qualquer convenção continuam sendo achados, pelo nome da tabela.
- `localizar_caderno_padrao`, que exigia "caderno" no nome, contradizendo a
  identificação normal (o Caderno de 2025 se chama "cadastro de conceitos").
  O CLI usa a identificação normal.
- Parâmetro `titulo` de `gerar_censo_html`, que era ignorado.

**Generalização trivial.** A extração de conceitos pulava literalmente a linha
"CADERNO DE CONCEITOS E ORIENTAÇÕES DO CENSO ESCOLAR 2025"; agora pula o
cabeçalho de qualquer ano. Sem efeito na edição 2025.

**Verificação.** Saída de referência capturada do código anterior em 8
cenários (completo, só dicionário, sem Caderno, sem questionários, recorte de 2
tabelas, sem HTML, HTML sem questionários, cache reaproveitado): **nenhuma
diferença** nos JSONs (objeto e bytes), relatórios (bytes), `censo.html`
(bytes) e caches; todos os avisos presentes. `.sav` de gestor e curso técnico
(vazio, modo 1, modo 2): metadados, dados e `case_count` idênticos. Interface:
8 cenários de `AppTest` com as mesmas mensagens, botões, opções e conteúdo do
pacote baixado. O teste de paridade está em `tests/test_paridade.py`.

---

## 9. Verificações anteriores à refatoração

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

