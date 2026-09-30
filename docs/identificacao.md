# Identificação resiliente de insumos

Como o ETL reconhece dicionário, Caderno, questionários, abas e CSVs sem
depender da convenção de nomes do INEP, e o que mexer quando ela mudar.

## O problema

O INEP não mantém convenção entre publicações. Para o **mesmo ano de coleta**
já circularam:

| | publicação "Anexos" | publicação "ceb2025_CSV" |
|---|---|---|
| CSV | `Tabela_Escola_2025.csv` | `ceb2025_microdados_tabela_escola.csv` |
| questionário | `Escola 2025.pdf` | `ceb2025_quest_escola.pdf` |
| dicionário | `Anexos/ANEXO I - Dicionário de Dados/` | `dicionario de dados/` |
| Caderno | `leia-me/Caderno de Conceitos e Orientações…pdf` | `leiame/ceb2025_cadastro_de_conceitos_e_orientacoes_do_censo.pdf` |
| delimitador | `;` | `,` |
| codificação | iso-8859-1 | UTF-8 com BOM |

Mudou tudo: prefixo de edição, ano no meio do nome, abreviação nova (`quest`),
pastas, delimitador, codificação — e o Caderno saiu com **"cadastro" no lugar
de "caderno"**, erro de digitação da própria fonte. Casar por nome inteiro
reconhecia zero arquivos da segunda forma.

## Três camadas

Da mais barata para a mais definitiva; a primeira que decide, decide.

### 1. Nome como conjunto de tokens — `censo_etl/nomes.py`

`tokens_arquivo` quebra o nome em palavras e descarta acento, caixa,
separadores, **ano em qualquer posição** (`ceb2025` vira `ceb` + `2025`),
números soltos e as palavras de `TOKENS_RUIDO` (`tabela`, `microdados`,
`censo`, `quest`, `v2`, `retificado`…); plurais comuns são reduzidos. O
conjunto que sobra é pontuado contra a assinatura de cada tabela
(`Tabela.assinatura` e `Tabela.assinatura_questionario` em `tabelas.py`):

```
"Tabela_Escola_2025"                  →  {escola}                  →  escola
"ceb2025_microdados_tabela_escola"    →  {escola}                  →  escola
"Tabela_Escola_2025_retificada_V3"    →  {escola}                  →  escola
"Tabela_Gestor_Escolar_2025"          →  {gestor}                  →  gestor
"ceb2025_quest_profissional_escolar"  →  {profissional}            →  docente
"Tabela_Curso_Tecnico_2025_V2"        →  {curso, tecnico}          →  curso_tecnico
"Cadastro Escola Nova 2025"           →  {cadastro, escola, nova}  →  (nenhuma)
```

A pontuação penaliza os excedentes, `len(assinatura) / (len(assinatura) +
excedentes)`, com `LIMIAR_NOME = 0.50`. É o que distingue o nome que é a coisa
do nome que só a menciona: `quest_escola` → 1,00; `cadastro_escola_nova` → 0,33.
Empate vai para a assinatura mais específica; persistindo, para a tabela que
vem antes na ordem canônica.

As abas do dicionário passam pela mesma função. Os nomes que o próprio
pipeline gera também (`import`, `metadata`, `editor`, `sav`, `json` são ruído),
o que permite às ferramentas de `.sav` achar o JSON de uma tabela sem saber o
ano.

**Caderno.** `pontuar_caderno` soma pesos de `TOKENS_CADERNO` (`conceito` 0,6;
`orientacao` 0,2; `caderno` 0,15; `cadastro` 0,05) com `LIMIAR_CADERNO = 0.55`;
qualquer token de `TOKENS_NAO_CADERNO` (nota técnica, parecer, termo, RIP,
leia-me…) zera. "caderno" não é obrigatório.

**Dicionário.** Planilha com o token `dicionario` (+0,2 por `variavel`),
ignorando os temporários do Excel (`~$…`); se nenhuma se disser dicionário,
aceita a única planilha do pacote.

### 2. Conteúdo

- **PDF**: se o nome não decidir o Caderno, o texto da 1ª página decide
  (`insumos.eh_caderno_pelo_texto`). Só nesse caso, porque abrir PDF é caro.
- **CSV** (só nas ferramentas de `.sav`): o cabeçalho é comparado com as
  variáveis que cada JSON declara (`leitura_csv.identificar_tabela_por_cabecalho`).
  Medido no insumo real:

  ```
                          escola  matricula  docente  turma  gestor  curso_tec
  escola.csv                1.00       0.09     0.09   0.09    0.09       0.09
  matricula.csv             0.10       1.00     0.10   0.10    0.10       0.10
  gestor_escolar.csv        0.28       0.28     0.28   0.28    1.00       0.28
  curso_tecnico.csv         0.51       0.51     0.51   0.51    0.51       1.00
  ```

  Exige `LIMIAR_COLUNAS = 0.60` e `MARGEM_COLUNAS = 0.15` sobre a segunda
  colocada (as seis tabelas compartilham as colunas geográficas). Pontua por
  *containment*: uma publicação pode omitir colunas que o dicionário lista
  (curso técnico: 20 de 31). Lê só o cabeçalho. CSVs chamados `arquivo_00.csv`
  são identificados corretamente.

### 3. Relatório

`leitura_csv.resolver_csvs` devolve, além do mapa tabela → CSV, por arquivo: a
camada que decidiu, a pontuação e se houve **conflito**. Nome e cabeçalho em
desacordo: vale o cabeçalho, e o conflito vira aviso.

## Localização no pacote — `censo_etl/insumos.py`

**Nada procura por nome de pasta.** `classificar_nomes` trabalha só sobre
strings (entradas do zip ou caminhos relativos) — é a mesma função da prévia do
zip na interface e da extração real. `localizar_insumos` aplica-a a uma árvore
extraída e deduz cada pasta de onde os arquivos reconhecidos caíram
(`pasta_dominante`: a que tem mais arquivos; empate, a mais rasa).
`localizar_questionario` escolhe, numa pasta, o PDF de maior pontuação para a
tabela.

## Formato dos CSVs — `censo_etl/leitura_csv.py`

- `detectar_encoding` valida o arquivo **inteiro** em `utf-8-sig`, `utf-8`,
  `cp1252` e cai para `latin-1` (que aceita qualquer byte). Amostrar não basta:
  um latin-1 cujo primeiro acento venha depois da amostra estouraria no meio da
  leitura. Custa ~0,45 s em 165 MB.
- `detectar_delimitador` conta `;`, `,`, tab e `|` **fora de aspas** no
  cabeçalho (um rótulo `"Área, Curso"` não pode inverter a contagem).

## Como estender

| Mudança do INEP | Onde mexer |
|---|---|
| palavra de embalagem nova no nome (`"consolidado"`) | `nomes.TOKENS_RUIDO` |
| palavra identificadora nova de tabela | `Tabela.assinatura` em `tabelas.py` |
| questionário renomeado | `Tabela.assinatura_questionario` |
| Caderno com outro título | `nomes.TOKENS_CADERNO` |
| delimitador novo | `leitura_csv.DELIMITADORES` |
| redação nova de código especial | `valores_especiais.MARCADORES_*` |

Fixe o caso novo em `tests/test_identificacao.py` (ou
`tests/test_valores_especiais.py`). Uma mudança de convenção que o sistema não
absorva deve quebrar ali, e não no meio de um processamento de 500 MB.

## Combinar insumos de anos diferentes

É possível processar um dicionário novo com o Caderno e os questionários de um
ano anterior, e misturar as duas convenções de nome. O ano da saída é o **do
dicionário**: dicionário 2026 + Caderno e questionários 2025 sai `ceb2026_*`.
Só se o dicionário não trouxer ano os demais insumos decidem — confira o
prefixo na saída.
