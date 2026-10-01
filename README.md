# ETL do Censo Escolar

Transforma os insumos oficiais do INEP nos metadados consumidos pelo
**World Bank Metadata Editor**.

```
dicionário .xlsx  (obrigatório) ─┐
Caderno de Conceitos .pdf (opc.) ├─► ETL ─► json/ceb2025_microdados_tabela_<t>_import_metadata_editor.json
questionários .pdf (opcionais)  ─┘          ceb2025_censo.html          (glossário navegável)
                                            ceb2025_relatorio_casamento.csv  (auditoria)
```

- **Só o dicionário de variáveis é obrigatório.** Caderno e questionários
  preenchem `var_concept`, `var_txt` e `var_qstn_qstnlit`; sem eles, esses
  campos ficam vazios.
- **Os microdados não são lidos.** Do ZIP oficial só saem o dicionário e os
  PDFs; por isso `case_count` sai 0.
- A saída segue a convenção do INEP (`ceb2025_…`), qualquer que seja o formato
  do insumo. O ano vem do nome do dicionário (ou, na falta, dos demais insumos);
  sem ano, sai `ceb_…` com aviso.
- **Revise o relatório de casamento antes de publicar**: boa parte dos
  metadados semânticos vem de casamento por similaridade.

## Instalação

Python 3.13.

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt          # requirements-dev.txt para testes
```

## Instalação no servidor

Roteiro para servidor Linux com systemd. Os caminhos (`/opt/censo-etl`), o
usuário (`censo`) e a porta (`8501`) são sugestões; ajuste ao padrão da casa.

### 1. Pré-requisitos

- **Arquitetura: x86_64 (Intel/AMD) ou ARM64 (aarch64).** Não é preciso ARM;
  todas as dependências fixadas em `requirements.txt` têm pacotes binários
  prontos para as duas arquiteturas, e nada é compilado na instalação. Outras
  arquiteturas (32 bits, ppc64le, s390x) não foram verificadas.
- **Linux com glibc 2.28 ou mais nova** (`ldd --version`): RHEL/Rocky/Alma 8+,
  Debian 10+, Ubuntu 20.04+. Distribuições com musl (Alpine) não têm esses
  pacotes binários e exigiriam compilação.
- **Python 3.13** com `venv` (`python3.13 --version`). Se a distribuição não
  trouxer o 3.13, instale-o pelo gerenciador de pacotes, pelo `uv` ou compilado.
- `git` e acesso de leitura ao repositório.
- Disco: nada é gravado de forma permanente; cada processamento usa uma pasta
  temporária do sistema (`/tmp`), apagada ao final. Reserve espaço em `/tmp`
  para o tamanho dos uploads.

### 2. Usuário e código

```bash
sudo useradd --system --create-home --home-dir /opt/censo-etl --shell /usr/sbin/nologin censo
sudo -u censo git clone https://github.com/FabionpRJ/pre_processamento_inep_dados.git /opt/censo-etl/app
cd /opt/censo-etl/app
sudo -u censo git checkout main        # ou a tag/branch homologada
```

### 3. Ambiente Python

```bash
sudo -u censo python3.13 -m venv /opt/censo-etl/venv
sudo -u censo /opt/censo-etl/venv/bin/pip install --upgrade pip
sudo -u censo /opt/censo-etl/venv/bin/pip install -r /opt/censo-etl/app/requirements.txt
```

Atrás de proxy corporativo, exporte `HTTPS_PROXY` antes do `pip` (ou use
`pip --proxy`).

Teste rápido, ainda sem serviço:

```bash
sudo -u censo /opt/censo-etl/venv/bin/python -m censo_etl --help
```

### 4. Configuração do Streamlit

Crie `/opt/censo-etl/app/.streamlit/config.toml`:

```toml
[server]
headless = true
address = "127.0.0.1"     # só o proxy reverso acessa; use "0.0.0.0" se não houver proxy
port = 8501
maxUploadSize = 1024      # MB; o padrão (200) não comporta o ZIP completo do INEP

[browser]
gatherUsageStats = false
```

### 5. Serviço systemd

Crie `/etc/systemd/system/censo-etl.service`:

```ini
[Unit]
Description=Censo Escolar - gerador de metadados (Streamlit)
After=network.target

[Service]
User=censo
Group=censo
WorkingDirectory=/opt/censo-etl/app
ExecStart=/opt/censo-etl/venv/bin/streamlit run app.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now censo-etl
sudo systemctl status censo-etl
curl -s http://127.0.0.1:8501/_stcore/health    # deve responder "ok"
```

Logs: `journalctl -u censo-etl -f`.

### 6. Proxy reverso (nginx)

O Streamlit usa WebSocket; o proxy precisa repassar o `Upgrade` e aceitar
uploads do mesmo tamanho de `maxUploadSize`. Exemplo de `server` do nginx:

```nginx
server {
    listen 443 ssl;
    server_name censo-etl.empresa.local;
    # ssl_certificate / ssl_certificate_key conforme o padrão da casa

    client_max_body_size 1024m;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 3600s;    # processamentos com o Caderno levam minutos
        proxy_send_timeout 3600s;
    }
}
```

Para publicar sob um subcaminho (ex.: `https://intranet/censo-etl/`), use
`location /censo-etl/` e acrescente `baseUrlPath = "censo-etl"` em `[server]`
no `config.toml`.

**O app não tem autenticação.** Restrinja o acesso pela rede interna, pelo
proxy (`auth_basic`, SSO) ou pelo firewall.

### 7. Atualização

```bash
cd /opt/censo-etl/app
sudo -u censo git pull
sudo -u censo /opt/censo-etl/venv/bin/pip install -r requirements.txt
sudo systemctl restart censo-etl
```

Ao trocar a versão do Python, recrie o `venv` (passo 3).

## Uso

```bash
streamlit run app.py
```

A interface aceita o ZIP oficial do INEP ou os arquivos separados (útil para
combinar um dicionário novo com o Caderno e os questionários de um ano
anterior), mostra antes de processar quais campos serão preenchidos e devolve
um `.zip` com os metadados.

Pela linha de comando:

```bash
python -m censo_etl gerar dicionario.xlsx pasta_saida pasta_questionarios caderno.pdf
python -m censo_etl criar-sav-vazio pasta_json            # .sav vazios (fora do serviço)
python -m censo_etl popular-sav pasta_csv pasta_json      # .sav com dados; regrava case_count
```

## Testes

```bash
pytest            # ~1 s
pytest -m lento   # paridade com a saída de referência (precisa de exemplo_input/)
```

## Estrutura

```
app.py                     interface Streamlit
censo_etl/
  pipeline.py              orquestração: gerar_metadados(...) -> ResultadoExecucao
  tabelas.py               as seis tabelas do Censo
  nomes.py, insumos.py     identificação de arquivos e abas; pacote zip
  edicao.py                ano da edição e nomes de saída
  dicionario.py            leitura do dicionário .xlsx
  valores_especiais.py     códigos que não são categoria (88888, 9, …)
  pdf/                     questionários e Caderno de Conceitos
  casamento.py             similaridade entre variáveis e textos dos PDFs
  metadata_editor.py       JSON de importação
  relatorio.py, censo_html.py, cache.py, formato.py
  servico.py               lógica da interface independente do Streamlit
  sav/                     ferramentas standalone de .sav
  cli.py                   python -m censo_etl
tests/                     pytest
docs/                      documentação
```

## Documentação

- [docs/especificacao.md](docs/especificacao.md) — entradas, saídas e a regra
  de cada campo.
- [docs/identificacao.md](docs/identificacao.md) — como os insumos são
  reconhecidos e o que mexer quando o INEP mudar a convenção.
- [docs/decisoes.md](docs/decisoes.md) — decisões de domínio (inclusive as
  pendentes de validação).
- [docs/operacao.md](docs/operacao.md) — comandos, testes, bytes vs.
  caracteres no SPSS e pontos de atenção.
- [docs/historico.md](docs/historico.md) — cada mudança, com diagnóstico e
  números medidos.
