# Backend — production-metrics-dashboard

Read-only FastAPI service aggregating plant production metrics. Runs
against a local CSV source today; SQL Server and Ignition sources slot
in later behind the same Protocol.

## Prerequisites

- Python 3.12
- Windows (primary target) or any POSIX for local dev

## Install

From `backend/`, with the venv created and activated:

```powershell
# Windows PowerShell
.\venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

`requirements-dev.txt` pulls in both runtime and dev/test tooling
(`pytest`, `pytest-asyncio`, `ruff`).

## Run

```powershell
uvicorn app.main:app --reload
```

- API:     <http://127.0.0.1:8000>
- Swagger: <http://127.0.0.1:8000/docs>
- ReDoc:   <http://127.0.0.1:8000/redoc>
- Health:  <http://127.0.0.1:8000/api/health>
- Latest:  <http://127.0.0.1:8000/api/production-report/latest>

## Test

```powershell
pytest
```

## Lint + format

```powershell
ruff check .
ruff format .
```

## Configuration

Set via environment variables (prefixed `PMD_`) or a `.env` file in
`backend/`. See `.env.example` for the full list.

| Variable                           | Default                                                     | Purpose                                            |
| ---------------------------------- | ----------------------------------------------------------- | -------------------------------------------------- |
| `PMD_ENVIRONMENT`                  | `local`                                                     | Deployment label surfaced in `/api/health`.        |
| `PMD_LOG_LEVEL`                    | `INFO`                                                      | structlog filter (DEBUG/INFO/WARNING/ERROR).       |
| `PMD_PRODUCTION_REPORT_CSV_PATH`   | `<repo>/context/sample-data/production-report/sample.csv`   | CSV file the production-report source reads.      |

## Layout

```
app/
  main.py                     # app factory + lifespan
  core/
    config.py                 # pydantic-settings
    correlation.py            # X-Correlation-ID middleware + ContextVar
    logging.py                # structlog JSON config
    snapshot.py               # SnapshotStore Protocol + InMemory impl
  api/
    dependencies.py           # DI providers
    routes/
      health.py               # GET /api/health
      production_report.py    # GET /api/production-report/latest
  integrations/
    production_report/
      base.py                 # ProductionReportSource Protocol
      csv_source.py           # CSV impl (current)
  services/
    production_report.py      # latest-per-workcenter business logic
  schemas/
    health.py
    production_report.py
tests/
  api/
  integrations/
```
