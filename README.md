# DataForge

[![CI](https://github.com/JVCSampaio/dataforge/actions/workflows/ci.yml/badge.svg)](https://github.com/JVCSampaio/dataforge/actions/workflows/ci.yml) · [Portfólio](https://github.com/JVCSampaio)

**Data platform** end-to-end: ingesta dados **reais** de fontes heterogêneas (API GitHub + CSV público), aplica **controle de qualidade**, persiste em **PostgreSQL** com modelagem relacional, expõe **analytics via SQL não trivial** e serve tudo por uma **API REST (FastAPI)** — tudo dentro de **Docker** com **CI** no GitHub Actions.

O fluxo integra ingestão, qualidade, armazenamento e consumo analítico. As decisões técnicas e instruções de execução estão documentadas abaixo.

## Funcionalidades e implementação

| Capacidade | Implementação |
|---|---|
| **Ingestão incremental** | `sync_state` + `since` na API de eventos |
| **Idempotência** | upserts + chaves únicas (`full_name`, `sha`, `(country, year)`) |
| **Data quality** | `quality.py`: nulls, duplicatas, schema, valores impossíveis |
| **Modelagem relacional** | `users`, `repositories`, `languages`, `events`, `commits`, `country_economy` |
| **SQL não trivial** | CTEs, `ROW_NUMBER()`, `LAG()`, `date_trunc`, JOINs |
| **API de analytics** | FastAPI: `/metrics/*`, `/quality`, `/health` |
| **Reprodutibilidade** | Dockerfile, `docker-compose.yml`, CI |

## Arquitetura

```
        ┌─────────────┐      ┌─────────────┐
        │  GitHub API │      │  CSV público│
        └──────┬──────┘      └──────┬──────┘
               │   (incremental)    │
               ▼                    ▼
        ┌──────────────────────────────────┐
        │  Ingestion (Python)              │
        │  - events since last sync        │
        │  - upsert users/repos/languages  │
        │  - upsert country_economy        │
        └───────────────┬──────────────────┘
                        ▼
        ┌──────────────────────────────────┐
        │  Data Quality                    │
        │  nulls / dups / schema / range   │
        └───────────────┬──────────────────┘
                        ▼
        ┌──────────────────────────────────┐
        │  PostgreSQL                      │
        │  users, repositories, languages, │
        │  events, commits, country_economy│
        │  sync_state                      │
        └───────────────┬──────────────────┘
                        ▼
        ┌──────────────────────────────────┐
        │  Analytics (SQL)                 │
        │  CTE / window fn / aggregation   │
        └───────────────┬──────────────────┘
                        ▼
        ┌──────────────────────────────────┐
        │  FastAPI  →  /metrics, /quality  │
        └──────────────────────────────────┘
```

## Fontes de dados

- **GitHub REST API** (público, sem token): perfis de `guillaumegomez`, `jakevdp`, `vintaugh`, `adamchainz` (contribuidores ativos de projetos open-source); seus repositórios, linguagens, eventos recentes e commits.
- **CSV público** (Gapminder): `country`, `year`, `life_expectancy`, `population`, `gdp_per_cap` — ~3.300 linhas.

## Como rodar

### Docker (recomendado)

```bash
docker compose up --build
```

Sobe o Postgres, cria as tabelas, roda a ingestão e sobe a API em `http://localhost:8000`.

### Manual (sem Docker)

```bash
# 1. banco (docker ou local)
docker run -d -p 5432:5432 -e POSTGRES_USER=dataforge \
  -e POSTGRES_PASSWORD=dataforge -e POSTGRES_DB=dataforge postgres:16-alpine

# 2. dependências
python -m venv .venv && .venv\Scripts\activate        # Windows
pip install -r requirements.txt
set PYTHONPATH=src                                       # Windows (ou export PYTHONPATH=src)

# 3. criar tabelas
python -m dataforge db-init

# 4. ingerir (incremental — rode quantas vezes quiser)
python -m dataforge ingest --source all

# 5. qualidade e métricas
python -m dataforge quality
python -m dataforge metrics

# 6. API
python -m dataforge serve
```

## API (exemplos)

| Endpoint | O que retorna |
|---|---|
| `GET /health` | `{"status":"ok"}` |
| `GET /metrics/top-repos?limit=10` | Top repos por estrelas |
| `GET /metrics/language-share` | Contagem + estrelas por linguagem |
| `GET /metrics/event-activity?user=pandas-dev` | Eventos por mês |
| `GET /metrics/repo-ranking` | Ranking por owner com `ROW_NUMBER` + `LAG` |
| `GET /metrics/gdp-life?year=2007` | PIB per capita × expectativa de vida |
| `GET /metrics/life-trend?country=Brazil` | Série temporal de expectativa de vida |
| `GET /metrics/event-types` | Distribuição de tipos de evento |
| `GET /quality` | Relatório de qualidade das 4 tabelas |

Documentação interativa: `http://localhost:8000/docs`.

## Testes e CI

```bash
python -m pytest -v          # 12 testes (ingestão, qualidade, analytics, API)
python -m ruff check src tests
```

O workflow `.github/workflows/ci.yml` sobe um Postgres efêmero, roda a ingestão, os testes e o linter em cada push.

## Decisões técnicas (o "por quê")

- **Pandas, não Spark.** O volume aqui é de milhares de linhas — pandas é a ferramenta certa. Spark seria over-engineering; um entrevistador pergunta "por que Spark?" e a resposta honesta é "não precisava".
- **`httpx` direto, não PyGithub.** Menos dependências, controle total sobre paginação e `since`.
- **Upsert em vez de `INSERT`.** Garante idempotência sem lógica de "já existe?" espalhada.
- **`sync_state` por fonte.** Cada fonte guarda onde parou; a próxima execução só busca o delta.
- **SQL no banco, não em Python.** Analytics com CTE/window function mostra que o banco é o motor de análise, não um dump.

## Estrutura

```
dataforge/
├── src/dataforge/
│   ├── config.py          # Settings (env)
│   ├── github_client.py   # cliente REST mínimo
│   ├── ingest.py          # ingestão incremental + upsert
│   ├── quality.py         # checks de qualidade
│   ├── analytics.py       # SQL não trivial
│   ├── api.py             # FastAPI
│   ├── cli.py             # db-init / ingest / quality / metrics / serve
│   └── db/
│       ├── models.py      # schema SQLAlchemy
│       ├── session.py
│       └── migrate.py
├── migrations/001_init.sql
├── tests/                 # pytest (ingest, quality, analytics, api)
├── .github/workflows/ci.yml
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── Makefile
└── README.md
```

## Limitações e roadmap

**Limitações (honestas):**
- Sem autenticação na API (read-only, uso local).
- Sem retenção/limpeza de eventos antigos (cresce com o tempo).
- Qualidade é reportada, não bloqueante (em produção, gate o pipeline).

**Roadmap (próxima iteração, proposital):**
- **Airflow** para orquestrar o ciclo ingest→quality→transform.
- **dbt** para modelar as camadas `staging → marts`.
- **DuckDB** para analytics ad-hoc sem subir o Postgres.
- **PySpark** — *somente* se o volume passar de ~10M de linhas; hoje não é o caso.

## Licença

MIT — veja [LICENSE](LICENSE).
