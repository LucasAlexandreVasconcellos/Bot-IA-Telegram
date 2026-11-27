# Jarvis KPI Bot (`Bot-IA-Telegram`)

Assistente executivo conversacional no Telegram para consulta em linguagem natural, auditoria de qualidade de dados e visualização gráfica de indicadores corporativos.

---

## 1. Arquitetura Integrada

```text
Usuário Telegram
   │  (Auth opcional por User ID + Rate-Limit + Comandos /start, /help, /reset, /meu_id)
   ▼
jarvis_bot/telegram_bot.py
   │
   ▼
jarvis_bot/agent.py  ──► Memória curta deslizante por chat_id (TTL + /reset)
   │  1. Roteamento estruturado Pydantic (RoteamentoConsulta)
   │  2. Consulta via Cliente MCP (STDIO / In-Process)
   ▼
jarvis_bot/mcp_server.py (FastMCP)
   │
   ├──► jarvis_bot/sql_guard.py   (SQLGlot: SELECT único, allowlist de tabelas, LIMIT automático)
   ├──► jarvis_bot/db.py          (PostgreSQL Read-Only ou SQLite mode=ro + fallback seguro de metadados)
   └──► jarvis_bot/quality.py     (Higienização por coluna, mojibake, moeda PT-BR, períodos e logs)
   │
   ▼
jarvis_bot/agent.py
   │  3. Síntese executiva Pydantic (RespostaAgente + Guardrails PEND-01 / PEND-02 / Anti-Injection)
   │  4. Renderização prévia de gráfico (barra, linha, pizza)
   ▼
sandbox_ambiente/executor_sandbox.py
   │  (Subprocesso Python -E com env limpo sem segredos, allowlist AST e auto-limpeza do PNG)
   ▼
Entrega no Telegram (Texto paginado <= 4.000 chars + Gráfico PNG)
```

---

## 2. Estrutura do Repositório

```text
Bot-IA-Telegram/
├── .env.example                       # Modelo seguro de variáveis de ambiente
├── .gitignore                         # Proteção contra versionamento de .env, *.db e charts/
├── docker-compose.yml                 # PostgreSQL 16 com criação automática de role READ ONLY
├── docker/init_readonly.sh            # Script de provisionamento do usuário jarvis_readonly
├── pyproject.toml / requirements.txt  # Dependências declaradas e empacotamento Python
├── jarvis_bot/                        # Pacote modular principal
│   ├── config.py                      # Configurações tipadas e logging estruturado
│   ├── quality.py                     # Validação e sanitização defensiva orientada por coluna
│   ├── sql_guard.py                   # Parser SQLGlot, allowlist e proteção contra SQLi/catálogos
│   ├── db.py                          # Repositório híbrido PostgreSQL RO / SQLite RO
│   ├── seed.py                        # Carga unificada (modos clean e dirty)
│   ├── mcp_server.py                  # Servidor FastMCP oficial
│   ├── mcp_client.py                  # Cliente MCP integrado ao Agente
│   ├── schemas.py                     # Contratos Pydantic 2.0 estritos
│   ├── charts.py                      # Renderizador isolado de gráficos com limpeza automática
│   ├── agent.py                       # Orquestração IA, guardrails e memória por chat_id
│   └── telegram_bot.py                # Interface Telegram, controle de acesso e rate-limit
├── sandbox_ambiente/                  # Sandbox Python blindada (AST allowlist + env limpo)
├── evals/                             # Suíte comparativa de LLM Evals (DeepEval, Ragas, Promptfoo)
├── tests/                             # Testes unitários e de integração ponta a ponta
├── ferramentas/                       # Script automatizado de Pré-Verificação Offline (CT-001..037)
├── scripts/                           # Scripts utilitários e demonstrações (ex.: demo_mcp.py)
└── docs/                              # Caderno de Testes, Relatório de Evals e PDFs de arquitetura
```

> **Compatibilidade Retroativa:** Os arquivos da raiz (`kpi_bot.py`, `servidor_mcp_banco.py`, `qualidade_dados.py`, `criar_sandbox.py`, `popular_postgres.py`) foram preservados como *entrypoints* limpos apontando para `jarvis_bot/`.

---

## 3. Instalação e Configuração Rápida

### 3.1 Ambiente Python
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3.2 Variáveis de Ambiente (`.env`)
Copie `.env.example` para `.env` e preencha suas chaves:
```powershell
Copy-Item .env.example .env
```
Principais variáveis:
- `TELEGRAM_TOKEN`: Token do bot obtido no `@BotFather`.
- `OPENAI_API_KEY`: Chave da API OpenAI.
- `DATABASE_URL`: Vazio para usar SQLite local somente leitura (`sandbox_jarvis.db`), ou `postgresql://jarvis_readonly:senha@localhost:5432/corporativo_db` para PostgreSQL.
- `USE_MCP`: `true` (padrão) executa consultas passando pelo Servidor MCP via `stdio`.
- `TELEGRAM_ALLOWED_USER_IDS`: IDs numéricos autorizados separados por vírgula (ex.: `12345678,87654321`).

### 3.3 Popular o Banco de Dados

**Opção A — SQLite local (desenvolvimento e testes offline):**
```powershell
python criar_sandbox.py
```

**Opção B — PostgreSQL 16 via Docker (homologação / produção):**
```powershell
docker compose up -d
python popular_postgres.py
```
Após popular com `DATABASE_ADMIN_URL`, configure `DATABASE_URL` no `.env` usando o usuário `jarvis_readonly` para garantir permissão estrita de `SELECT` também no nível do SGBD.

---

## 4. Como Executar

### Iniciar o Bot do Telegram
```powershell
python kpi_bot.py
```

### Executar o Servidor MCP Isoladamente (STDIO)
```powershell
python servidor_mcp_banco.py
# Demonstração cliente-servidor MCP:
python scripts/demo_mcp.py
```

---

## 5. Testes, Pré-Verificação Offline e LLM Evals

### Suíte Completa de Testes Automatizados (`pytest` / `unittest`)
```powershell
pytest -v
# ou apenas com stdlib unittest:
python -m unittest discover -s tests -v
python -m unittest test_qualidade_dados.py -v
```

### Pré-Verificação Offline do Caderno de Testes (`CT-001` a `CT-037`)
```powershell
python ferramentas/pre_verificacao_offline.py
```

### Benchmark Comparativo de LLM Evals (DeepEval, Ragas e Promptfoo)
```powershell
python -m evals.comparar_ferramentas
```
*(Para instalar os pacotes pesados opcionais `deepeval` e `ragas` além do modo híbrido incluso: `pip install -e ".[evals]"`).*

---

## 6. Nota de Segurança sobre Histórico Git

Caso chaves antigas tenham sido registradas em commits históricos anteriores à refatoração:
1. **Revogue imediatamente** o `TELEGRAM_TOKEN` antigo no `@BotFather` e a `OPENAI_API_KEY` antiga no painel da OpenAI.
2. Para expurgar definitivamente o arquivo `.env` de commits antigos do repositório remoto (reescrevendo SHAs em coordenação com a equipe):
```powershell
pip install git-filter-repo
git filter-repo --path .env --invert-paths
git push origin --force --all
```
