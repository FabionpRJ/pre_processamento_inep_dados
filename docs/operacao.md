# Operação

Como rodar, testar e o que vigiar.

## Comandos

```bash
# interface (uso normal) — só metadados
streamlit run app.py

# o mesmo pela linha de comando
python -m censo_etl gerar dicionario.xlsx pasta_saida pasta_questionarios caderno.pdf
python -m censo_etl gerar dicionario.xlsx saida --tabelas escola turma --ano 2025

# .sav, fora do serviço — partem dos JSONs acima
python -m censo_etl criar-sav-vazio pasta_json [pasta_saida] --tabelas escola turma
python -m censo_etl popular-sav pasta_csv pasta_json --modo 1 --tabelas escola turma
```

Os scripts `gerar_json_metadata_editor.py`, `criar_sav_vazio.py` e
`popular_sav.py` da raiz continuam funcionando, com os mesmos argumentos: são
atalhos para os subcomandos acima.

## Testes

```bash
pip install -r requirements-dev.txt
pytest                      # unitários e interface, ~1 s
pytest -m lento             # paridade com a saída de referência, ~3 min
ruff check .
```

`pytest -m lento` precisa dos insumos em `exemplo_input/` e da saída de
referência em `OUTROS/referencia/saida/`, ambos fora do Git; sem eles, é
pulado. Para comparar duas pastas de saída à mão:
`python tests/comparacao.py <referência> <nova>`.

## Bytes vs. caracteres no SPSS (crítico)

**Toda largura do formato SPSS é medida em bytes; todo `tamanho` do dicionário
do INEP, em caracteres.** Com acentos os dois divergem, e isso já derrubou duas
importações ([historico.md](historico.md) §8.3 e §8.4). Vale também para o
serviço: `loc_width`, `var_format` e os rótulos vão no JSON que o Metadata
Editor importa.

**Rótulos** (`sav/gravacao.py`): variável até 256 bytes, valor até 120 bytes.
Acima disso o readstat trunca por conta própria no byte exato, partindo
caractere multibyte (o `…` tem 3 bytes) e deixando UTF-8 inválido no arquivo.
`truncar` corta por bytes, com reserva para as reticências, para o readstat
nunca precisar truncar. Um rótulo de 254 caracteres com acentos ocupa 258
bytes.

**Dados de texto**: o formato `A<n>` também conta bytes. "2115 ET 4ª" tem 10
caracteres e 11 bytes; declarar `A10` faz um leitor que fatia pela largura
cortar o `ª` ao meio. `construir_meta_sav` declara `A{max(tamanho do
dicionário, bytes reais)}`.

Coluna de texto é detectada por `not is_numeric_dtype(...)`, não por
`dtype == object`: conforme a versão do pandas o texto vem como `object` ou
como `str`.

## Pontos de atenção

- **`pd.set_option("future.infer_string", False)`** em `censo_etl/sav/__init__.py`
  não é cosmético: as strings apoiadas em pyarrow (padrão do pandas 3) já
  causaram segfault em `libarrow.so` ao gravar com pyreadstat. Não remova.
- **Limite de upload do Streamlit** (200 MB por padrão). No modo por arquivos
  só entram o `.xlsx` e PDFs. Um pacote completo do INEP passa disso no modo
  ZIP: ajuste `server.maxUploadSize` em `.streamlit/config.toml` ou use o modo
  por arquivos.
- **`case_count` sai 0** nos JSONs do serviço. É esperado
  ([decisoes.md](decisoes.md) D8); `popular-sav` o preenche.
- **Revise o `relatorio_casamento.csv` antes de publicar.** Boa parte dos
  metadados semânticos vem de similaridade; a coluna `valores_especiais` mostra
  o que saiu de categoria.
- **Questionário de Turma não é numerado** e passa pela extração por layout
  (16 rótulos, contra 59 questões da Escola). Turma e curso técnico recuperam
  28 e 3 variáveis com `var_qstn_qstnlit`; as demais são contagens `QT_*` sem
  campo no formulário.
- **Códigos especiais pelo rótulo** e **88888 como imputação pendente de
  validação**: ver [decisoes.md](decisoes.md) D1 e D2.
- **Botão Cancelar** depende do Streamlit abortar o script quando há interação:
  para no próximo ponto de verificação, não instantaneamente. Não foi testado
  sob carga real.
- **Em aberto — HTTP 500 na importação do `.sav` da escola** (só afeta quem
  gera `.sav` pelas ferramentas standalone). Diagnóstico e kit de bisecção em
  [historico.md](historico.md) §8.5.
- **`model.json` do Metadata Editor não está no repositório.** Sem ele, a
  conformidade de `var_universe`, `var_concept`, `var_catgry` e `var_sumstat` é
  leitura do padrão DDI, não verificação.
- **Não versionar** `.zip`, `.sav`, insumos do INEP nem saídas — ver
  `.gitignore`. Os insumos de exemplo ficam em `exemplo_input/` e o material de
  trabalho em `OUTROS/`, ambos ignorados.
