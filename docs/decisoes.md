# Decisões de domínio

Regras que parecem arbitrárias para quem só lê o código, mas foram decididas
em reunião ou medidas no insumo real. Não mude sem revisitar a decisão.

## D1. Códigos especiais são classificados pelo rótulo

**Contexto.** O dicionário lista 88888 ("valor extremo"), 9 ("Não informado")
e 99999999999999 ("Sem declaração") junto das categorias. Tratá-los como
categoria põe 88888 na média de "quantidade de televisões" (3,4 vira 4.317,0) e
pede frequência de 200 mil CNPJs.

**Decisão.** A classificação é pelo texto do rótulo, contra listas de
marcadores. A forma do número só audita: no mesmo dicionário, `8` é categoria
real ("Área onde se localizam povos e comunidades tradicionais") e `9` é "Não
informado".

**Consequência.** Redação nova do INEP gera aviso em vez de passar calada; o
ajuste é uma linha em `valores_especiais.MARCADORES_*` e um caso em
`tests/test_valores_especiais.py`.

## D2. Todo código especial vai para `var_invalrng` e `var_imputation`

**Decisão (reunião).** Tratar o valor especial como resultado do processamento
do INEP — todos são gravados pelo produtor no lugar da observação —, e não só o
de valor extremo. A distinção entre tratamento de consistência e ausência de
declaração fica na redação do texto e no relatório.

**Status.** A leitura do 88888 como imputação está **pendente de validação**
com as áreas responsáveis. Voltar atrás é mexer em
`valores_especiais.descrever_imputacao` (e, se for o caso, no destino por tipo
em `metadata_editor.montar_variavel`).

## D3. `var_notes` para quem analisa, `var_qstn_ivuinstr` para quem preenche

**Decisão (reunião).** `var_notes` recebe as notas do dicionário, os anos de
coleta e a descontinuidade. `var_qstn_ivuinstr` recebe as orientações de
preenchimento **e** os destaques "Importante!"/"Você sabia?" do Caderno, que
falam com o declarante do Educacenso.

**Consequência.** Em 2025, 40 blocos saíram de `var_notes`; `var_qstn_ivuinstr`
passou de 63 para 101 variáveis preenchidas.

## D4. Descontinuidade literal

**Decisão (reunião).** `"n"` na coluna do ano do dicionário na matriz "Coleta
por ano" = "Variável descontinuada no ano de {ano}." em `var_notes`.

**Consequência conhecida.** Vale também para as 9 variáveis de endereço da
Escola com `"n"` em todos os anos (nunca publicadas). A alternativa (exigir um
`"s"` anterior) foi **descartada**; a nota do dicionário, logo acima, já
explica a retirada por proteção de dados. Em 2025 são 85 variáveis (78 Escola,
3 Docente, 2 Matrícula, 2 Turma).

## D5. `var_universe` é a população e segue o ano do dicionário

**Decisão.** "Escola de Educação Básica declarada em {ano}", igual nas seis
tabelas: nesta publicação os microdados são agregados por escola. O ano é a
última coluna de "Coleta por ano" — o mesmo de D4 —, não o ano detectado pelo
nome dos arquivos. Os anos de coleta ficam em `var_notes`.

**Status.** O texto foi redigido de forma conservadora e merece revisão de quem
conhece o domínio.

## D6. `var_concept` guarda o título do conceito

**Decisão.** O título curto, em Title Case (o DDI trata `concept` como rótulo
de vocabulário); a definição fica em `var_txt`. Antes o mesmo parágrafo, de até
1.807 caracteres, ia nos dois campos.

## D7. O ano da saída é o ano do dicionário

**Decisão.** A edição do metadado é a edição do dicionário que o gerou. Os
demais insumos só decidem quando o dicionário não traz ano. Sem ano em nenhum,
a saída sai `ceb_…` com aviso — nunca um ano inventado.

## D8. O serviço só produz metadados

**Decisão.** Os microdados deixaram de ser insumo e os `.sav` de ser saída: o
produto é o JSON, e exigir centenas de MB de CSV acoplava o serviço ao insumo
mais caro sem que os metadados dependessem dele. Só o dicionário é
obrigatório.

**Custo aceito.** `case_count` sai 0 (só `popular-sav` o preenche) e o ano
perdeu a fonte mais confiável (`NU_ANO_CENSO`). As ferramentas de `.sav`
continuam disponíveis, fora do serviço.

## D9. Matrícula sem conceitos do Caderno é correto

**Contexto.** A tabela de matrícula casa com a seção "pessoa física" do
Caderno, mas nesta edição suas variáveis são contagens por escola ("Número de
Matrículas…"), sem conceito correspondente.

**Decisão.** Não forçar casamento; manter o aviso. Resolver de fato exige rever
o mapeamento tabela → seção para a natureza agregada da publicação — decisão de
conteúdo.

## D10. Sem peso amostral

O Censo é enumeração completa: `sum_stats_options` nunca marca `wgt`,
`mean_wgt` nem `stdev_wgt`.
