# Recomendações de UX — `app.py`

Documento de referência com os pontos de melhoria de usabilidade levantados para a
interface Streamlit ([app.py](app.py)).

**Status: aplicado em 03/08/2026**, com uma exceção registrada na seção 3
(cancelamento). As referências `app.py:linha` abaixo apontam para o código
*anterior* à alteração — servem como registro do problema original.

---

## 1. Feedback de erros e falhas parciais

- **Erros pouco acionáveis.** Em `app.py:299-304`, qualquer exceção no Passo 1
  vira só `st.error(f"Erro ao gerar JSONs: {exc}")` — a mensagem crua da
  exceção (ex: `KeyError: 'Tabela_de_Escola'`), sem traceback e sem tradução
  para algo que o usuário consiga agir. Recomendação: capturar os modos de
  falha conhecidos (aba ausente na planilha, encoding de CSV, PDF ilegível) e
  traduzir para mensagens específicas; manter o traceback completo só no log
  interno.
- **Falhas parciais enterradas no log.** `erros_vazio` (`app.py:322-323`) e
  `erros_pop` (`app.py:339-340`) hoje só aparecem como linha `[aviso]` dentro
  da janela de log de 50 linhas — o usuário pode ver "Concluído!" em verde
  mesmo com uma tabela que falhou silenciosamente. Recomendação: promover para
  `st.warning()` persistente, visível mesmo depois que o log rolar.
- **Modo ZIP não valida Caderno/questionários antes de rodar.** A detecção
  automática (`app.py:240-267`) só bloqueia se faltar dicionário ou pasta de
  CSVs; Caderno e questionários ausentes só geram uma linha de log, sem aviso
  prévio ao usuário antes de comprometer o tempo de execução completo.

## 2. Barra de progresso

- Os percentuais em `app.py:213, 288, 309, 326, 343` (10/45/65/92) são
  estimativas fixas, não proporcionais ao tempo real de cada passo. Para
  tabelas grandes (`matricula`, `docente`), o Passo 3 (popular `.sav`) tende a
  ser o mais lento, mas a barra já mostra 65% antes dele começar — parece
  travar. Recomendação: sub-progresso dentro do Passo 3 baseado na contagem de
  `tabelas_selecionadas` processadas.

## 3. Controle de execução

- **Sem cancelamento.** O pipeline roda de forma síncrona dentro do callback
  do botão, sem opção de abortar. Para ZIPs oficiais grandes, um clique errado
  ou seleção errada de tabelas obriga a esperar o processo todo.
- **Botão "Processar" desabilitado sem explicação visível.** Depois de um
  resultado gerado, o botão em `app.py:209-210` fica cinza sem indicação do
  motivo até o usuário rolar a página e achar "Processar novo arquivo".
  Recomendação: legenda curta perto do botão desabilitado.

## 4. Validações e feedback prévio

- Sem aviso sobre limite de tamanho de upload (padrão Streamlit: 200MB) —
  ZIPs oficiais do INEP podem estourar isso sem nenhuma mensagem explicativa
  no app.
- `multiselect` de tabelas (`app.py:91-96`) não tem atalho "selecionar
  todas/nenhuma" além do default já vir com todas marcadas.
- Modo ZIP não mostra um resumo do que foi encontrado dentro do zip antes de
  rodar (ao contrário do modo "Arquivos separados", que já tem
  `st.success`/`st.warning` em `app.py:143-153`).

## 5. Itens menores

- Log trunca nas últimas 50 linhas (`app.py:218`) sem indicar que linhas
  anteriores foram descartadas.
- Sem tempo decorrido/estimado — só percentual.
- Interface 100% em português — confirmar se é intencional e permanente.

**Prioridade sugerida se só der para atacar 3 coisas:** falhas parciais
visíveis, progresso proporcional ao Passo 3, e legenda no botão desabilitado.

---

# Recomendação de interface — insumos opcionais (Caderno / Questionários)

Pedido: no modo "Arquivos separados", dicionário e tabelas (CSVs) continuam
obrigatórios; Caderno de Conceitos e Questionários passam a ser opcionais,
controlados por checkbox, com a opção de gerar os artefatos com todos os
metadados disponíveis ou só com o que foi fornecido.

## Layout proposto

```
Insumos obrigatórios
────────────────────
1. Dicionário de variáveis (.xlsx)          [uploader]
2. Tabelas de dados (.csv)                  [uploader, multiple]

Metadados opcionais
────────────────────
☑ Incluir Caderno de Conceitos (preenche var_concept)
    └─ 3. Caderno de Conceitos e Orientações (.pdf)   [uploader — só aparece se marcado]

☑ Incluir Questionários (preenche var_qstn_qstnlit)
    └─ 4. Questionários (.pdf)                        [uploader, multiple — só aparece se marcado]

ℹ️ Cobertura de metadados com a seleção atual:
   ✅ nomes, tipos, rótulos, categorias (sempre, via dicionário)
   ✅ conceitos (Caderno incluído)
   ❌ perguntas literais (Questionários não incluídos)
```

## Decisões de design

1. **Checkbox controla a visibilidade do uploader, não só a validação.**
   Desmarcar "Incluir Caderno de Conceitos" esconde o uploader em vez de
   deixá-lo desabilitado/vazio na tela — mais claro sobre o que foi excluído.
2. **Sem toggle separado de "completo vs. parcial".** Um radio adicional tipo
   "Gerar com metadados completos / só com o disponível" duplicaria o que os
   checkboxes já dizem e poderia contradizê-los. Os checkboxes já são o
   controle de completo/parcial.
3. **Painel "cobertura de metadados" ao vivo.** É a peça que resolve o pedido
   original: hoje, se falta o Caderno, o usuário só descobre que `var_concept`
   veio vazio depois de abrir o resultado. O painel expõe isso antes do clique
   em "Processar".
4. **Reconciliar com os checkboxes `gerar_html` / `incluir_questionarios`**
   (`app.py:158-170`). Eles hoje são independentes de o questionário/Caderno
   terem sido de fato enviados. `incluir_questionarios` deve ficar forçado
   como falso (não só visualmente desabilitado) quando nenhum PDF de
   questionário foi enviado, para o painel de cobertura e o `censo.html`
   gerado nunca discordarem.
5. **Validação (`app.py:188-204`) simplificada.** `faltando` passa a checar
   só dicionário + CSVs. Ausência de Caderno/questionários deixa de ser erro —
   vira estado válido.
6. **Mesmo tratamento no modo ZIP, com toque mais leve.** O modo ZIP já
   tolera Caderno/questionários ausentes (`app.py:246-267`); falta só mostrar
   o mesmo painel de cobertura depois de escanear o zip, em vez de só reportar
   no log ao final da execução.

---

# Registro de implementação (03/08/2026)

## O que foi aplicado

| Item | Onde |
|---|---|
| Tradução de erros conhecidos (`explicar_erro`) | `app.py` |
| Captura de `SystemExit` — os módulos sinalizam entrada inválida com `sys.exit()`, que não era pego por `except Exception` | `app.py` (`rodar_passo`) |
| Traceback completo no log + mensagem curta na tela | `app.py` (`rodar_passo`) |
| Falhas parciais (`erros_vazio`/`erros_pop`) como `st.warning` persistente | `app.py` |
| Aviso persistente de cobertura reduzida (Caderno/questionários ausentes) | `app.py` |
| Progresso real tabela a tabela no passo 3 | `popular_sav.executar(progresso=…)` |
| Progresso tabela a tabela no passo 2 | `criar_sav_vazio.executar(progresso=…)` |
| Repesagem das faixas da barra (passo 3 = maior fatia) | `app.py` (`P_ENTRADAS/P_PASSO1/P_PASSO2/P_PASSO3`) |
| Tempo decorrido na barra e no resumo final | `app.py` (`avancar`) |
| Legenda explicando o botão "Processar" desabilitado | `app.py` |
| Aviso de execução longa para matrícula/docente | `app.py` |
| Limite de upload exibido (`server.maxUploadSize`) | `app.py` |
| Botões "Selecionar todas" / "Limpar seleção" | `app.py` |
| Rótulos amigáveis no multiselect (`format_func` com `ROTULO_TABELA`) | `app.py` |
| Varredura prévia do zip + painel "Conteúdo identificado no zip" | `app.py` (`inspecionar_zip`) |
| Opções de tabela restritas às que existem no zip | `app.py` |
| Indicador de linhas omitidas na janela de log | `app.py` (`log`) |
| Caderno e questionários opcionais, via checkbox que oculta o uploader | `app.py` |
| Painel de cobertura de metadados | `app.py` (`painel_cobertura`) |
| `incluir_questionarios` travado quando não há questionário | `app.py` |
| Validação: só dicionário + CSVs bloqueiam | `app.py` |
| Assinatura de invalidação passa a incluir as opções, não só os arquivos | `app.py` (`assinatura`) |

## Extra, fora do documento original

Exposto na interface o parâmetro `modo` de `popular_sav`, que estava fixo em `1`:

- **Todas as variáveis do dicionário** (modo 1) — o `.sav` traz a estrutura
  completa e as colunas ausentes no CSV ficam vazias.
- **Apenas as colunas presentes no CSV** (modo 2) — o `.sav` traz só o que
  existe no CSV; colunas extras entram sem metadados.

É a leitura literal de "gerar com todos os metadados ou só os disponíveis" e o
parâmetro já existia no módulo — só não estava acessível pela interface.

## Pendência conhecida — cancelamento

O botão **Cancelar** foi adicionado ao lado da barra de progresso, mas depende
do comportamento do Streamlit de abortar o script em execução quando o usuário
interage com um widget. Na prática ele interrompe no próximo ponto de
verificação (entre tabelas, onde a barra é atualizada), e não instantaneamente.
Como o processamento roda inteiro em `tempfile.TemporaryDirectory()`, nada fica
gravado ao abortar. **Não foi testado sob carga real** — um cancelamento
verdadeiramente responsivo exigiria mover o pipeline para uma thread separada
com sinalização cooperativa, o que muda a arquitetura do `app.py`.

## Como foi verificado

- `streamlit.testing.v1.AppTest`: boot dos dois modos sem exceção; checkboxes
  opcionais presentes; Caderno/questionários não bloqueiam a validação;
  uploaders opcionais somem ao desmarcar; painel de cobertura reflete o estado.
- E2E com os microdados reais de 2025 (CSVs truncados em 200 linhas):
  passo 1 com `pasta_questionarios=None` e `caminho_caderno=None`; callbacks de
  progresso dos passos 2 e 3; modos de coluna 1 e 2 gerando `.sav` distintos
  (escola: 367 vs 302 colunas).
- `inspecionar_zip` contra a estrutura real do INEP: encontra dicionário
  (ignorando os temporários `~$` que existem na pasta), Caderno, 6
  questionários e as 6 tabelas; detecta ausência dos opcionais; devolve `None`
  em zip corrompido; rebobina o ponteiro para a extração seguinte funcionar.
