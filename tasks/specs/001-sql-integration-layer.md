# SPEC-001 — SQL integration for production-report source

**Status:** Proposed — 2026-04-23
**Parent decision:** `tasks/decisions/001-stack-and-source-boundary.md`
**Confirmed prerequisites:** ODBC Driver 17 installed on dev box; DB
connection already exercised from another project on the same host.

## Context

The CSV-backed `ProductionReportSource` (active producer since Phase 1)
is validated end-to-end. We are now adding a SQL implementation so the
API reads from the real `IA_ENTERPRISE.[UNS].[SITE_PRODUCTION_RUN_REPORTS]`
table. Routes, services, response schemas, and the frontend do not
change — per the ADR, swapping sources is a DI change, not a code
change.

**Known table schema** (from Trey's screenshot):

| Column | Type | Nullable |
|---|---|---|
| `ID` | `int` (PK) | no |
| `PRODDATE` | `datetime` | no |
| `PROD_ID` | `nvarchar(50)` | no |
| `SITE_ID` | `int` | no |
| `DEPARTMENT_ID` | `int` | no |
| `PAYLOAD` | `nvarchar(max)` | no |
| `DTM` | `datetime` | **yes** |

**Row-count expectation today:** < 100 rows. Small enough that a naive
"select all rows, filter in Python" approach matches what the CSV
source does. Date-window push-down to SQL is deferred until row growth
makes Python-side filtering uneconomical.

## Decisions

### D1. Dependencies
- Add `aioodbc~=0.5` (wraps `pyodbc`; async pool) and `pyodbc~=5.2` to
  `backend/requirements.txt`. No new dev dep.
- ODBC Driver 17 is a *host* dependency, not a Python package. Document
  in `RUNBOOK.md` that the driver must be installed.

### D2. Settings
Add two fields to `backend/app/core/config.py`:

```python
db_conn_string: SecretStr | None = Field(
    default=None,
    description="ODBC connection string for SQL Server backend.",
    validation_alias=AliasChoices("PMD_DB_CONN_STRING", "DB_CONN_STRING"),
)
production_report_backend: Literal["csv", "sql"] = Field(
    default="csv",
    description="Which concrete ProductionReportSource to instantiate.",
)
```

- `AliasChoices` means Trey's existing un-prefixed `DB_CONN_STRING` in
  `.env` works as-is; the `PMD_` prefix is accepted too for
  consistency.
- `SecretStr` keeps the string from appearing in logs or repr output.
- Default backend is `csv` so today's running app is unchanged until
  the setting is explicitly flipped.

### D3. Type-contract adjustments

Current:
```python
@dataclass(frozen=True)
class ProductionReportRow:
    id: int
    prod_date: datetime
    prod_id: str
    site_id: str           # CSV has "101" -- SQL has 101 (int)
    department_id: str     # CSV has "127" -- SQL has 127 (int)
    payload: dict[str, Any]
    dtm: datetime          # SQL DTM is nullable
```

Changes:
- Keep `site_id: str` and `department_id: str`. The SQL source casts
  `int -> str` on read. Preserves the JSON contract surfaced by the
  API and the frontend's string comparisons.
- Loosen `dtm: datetime | None`. Update `app/services/production_report.py`
  sort keys to use `(r.prod_date, r.dtm or datetime.min)` so null
  sorts oldest.
- CSV source continues to parse DTM as required for the sample file;
  if a future CSV has null, parsing will need a guard, but the
  committed sample always populates it.

### D4. SQL source shape

`backend/app/integrations/production_report/sql_source.py`:

```python
class SqlProductionReportSource:
    name = "sql:production_report"

    def __init__(self, pool: aioodbc.Pool, table: str = "[UNS].[SITE_PRODUCTION_RUN_REPORTS]"):
        self._pool = pool
        self._table = table

    async def ping(self) -> SourceStatus: ...
    async def fetch_rows(self) -> list[ProductionReportRow]: ...
    async def list_site_ids(self) -> list[str]: ...
```

- `ping()` runs `SELECT 1` with a short timeout; returns ok=True on 1,
  ok=False with the driver error on exception.
- `fetch_rows()` runs the `select_all.sql` query, casts types, returns
  a list of `ProductionReportRow`. Payload JSON is `json.loads`'d from
  the `nvarchar(max)` column.
- `list_site_ids()` can be pushed down to `SELECT DISTINCT SITE_ID` but
  given the <100-row size, deriving from `fetch_rows` is fine and
  matches CSV behavior.

The `aioodbc` work happens inside `async with self._pool.acquire()`
blocks; no blocking calls.

### D5. Queries on disk

Per the project convention (`CLAUDE.md` "SQL lives in files"):

```
backend/app/integrations/production_report/queries/
  ├─ ping.sql                # SELECT 1
  └─ select_all.sql          # SELECT * from [UNS].[SITE_PRODUCTION_RUN_REPORTS]
```

- Loaded at module import via a small `load_query(name)` helper.
- `?` parameterization used when parameters arrive later (the initial
  queries have none — `SELECT *` with no WHERE).
- Column list is enumerated explicitly in `select_all.sql` (not `*`)
  so a schema addition upstream doesn't silently break parsing.

### D6. Connection pool lifecycle

- Pool created during FastAPI lifespan startup **only when**
  `settings.production_report_backend == "sql"` **and** a conn string
  is present.
- Pool size: `minsize=1, maxsize=4`. Small: dashboard polling is low
  concurrency.
- Stored on `app.state.sql_pool` so DI providers can read it from the
  request's FastAPI context.
- On pool-creation failure: log the error as `app.startup.sql_pool_failed`
  with the driver exception, leave `app.state.sql_pool = None`, and
  continue. The SQL source's `ping()` returns ok=False; the
  `/api/health` endpoint surfaces that; the /latest and /history
  endpoints return HTTP 503 with a per-source detail. Dashboard's red
  error bar shows the failure without blanking.
- Pool closed during lifespan shutdown.

### D7. DI provider update

`backend/app/api/dependencies.py`:

```python
@lru_cache
def get_production_report_source() -> ProductionReportSource:
    settings = get_settings()
    if settings.production_report_backend == "sql":
        pool = _get_app_state_pool()  # raises if not initialized
        return SqlProductionReportSource(pool=pool)
    return CsvProductionReportSource(settings.production_report_csv_path)
```

- CSV remains the default and the permanent test fixture.
- `lru_cache` still in play; we call `cache_clear()` on settings
  changes (same pattern as today).

### D8. Tests

Three categories:

1. **Unit tests for `SqlProductionReportSource`** using an in-memory
   fake cursor — no real DB. Verifies type-casting (int -> str),
   null-DTM handling, PAYLOAD parsing.
2. **Integration tests, gated** by env var
   `PMD_ENABLE_SQL_INTEGRATION_TESTS=1`. Skipped in CI unless
   explicitly opted in. When enabled, they open a real connection
   using the same `.env` and run a handful of read-only queries.
3. **Existing CSV tests continue to pass unchanged.** Total after
   this spec: 22 existing + ~5 SQL unit tests + (gated) ~3 integration
   tests = 27 routine / 30 with integration opt-in.

### D9. Observability

- Log pool creation with `source=sql:production_report` and the server
  hostname (parsed from the conn string, password redacted).
- Every SQL query logs `duration_ms`, `rows_returned`, and the
  correlation ID (already on context). No query SQL in logs — the
  query name only (e.g. `query=select_all`).
- `/api/health` surfaces the SQL source's `ping()` result the same way
  it does the CSV source's.

### D10. Non-goals for this spec

- Write support (app stays read-only).
- Windows Integrated Auth / gMSA container story (SQL auth with a
  service-account password is what the current conn string uses;
  Integrated Auth comes later if requirements change).
- Push-down date-window filter on `/history` (deferred until row
  count makes Python-side filtering uneconomical).
- Schema versioning / migrations (no DDL; read-only).
- A 3rd source type (Ignition, REST). Those are separate specs.

## Implementation plan

Ordered. Each step is a landable unit; you can stop mid-plan and
defer the rest without breaking anything.

1. **Deps + settings** (no behavior change yet)
   - Update `requirements.txt` / `requirements-dev.txt`
   - `pip install -r requirements-dev.txt` on Windows
   - Add `db_conn_string` and `production_report_backend` to `Settings`
   - `ruff check` + `pytest` still green (nothing uses the new fields)
2. **Protocol adjustments**
   - `ProductionReportRow.dtm: datetime | None`
   - Update `services/production_report.py` sort keys
   - Update tests for new nullable shape (mostly N/A — no CSV row
     has null dtm, but the dataclass change is typed)
3. **SQL source + queries**
   - `app/integrations/production_report/queries/{ping,select_all}.sql`
   - `app/integrations/production_report/sql_source.py`
   - `app/integrations/sql/pool.py` — thin helpers for
     `create_pool(dsn)` / load-query utility
   - Unit tests against a fake cursor
4. **Lifespan wiring**
   - `main.py`: create pool on startup if backend=sql; close on shutdown
   - DI provider branches on `production_report_backend`
5. **Flip the switch** (your call, per D2)
   - Uncomment `DB_CONN_STRING` in `backend/.env` with rotated value
   - Set `PMD_PRODUCTION_REPORT_BACKEND=sql` in `backend/.env`
   - Restart uvicorn; verify `/api/health` shows `sql:production_report`
     as OK; verify `/api/production-report/latest` returns real rows
   - Gated integration tests: set `PMD_ENABLE_SQL_INTEGRATION_TESTS=1`
     and run `pytest`

## Testing strategy

- **Unit** (`tests/integrations/test_sql_source.py`): fake cursor
  returning canned rows; asserts type-casting (`int SITE_ID -> str`),
  null-DTM handling, JSON PAYLOAD parsing.
- **Integration** (same file, gated): requires a real DB. Skips by
  default. When enabled, asserts `SELECT 1` works and
  `fetch_rows()` returns at least 1 row with the expected column
  shape. No assertions on specific values — the DB is live data.
- **Existing**: `conftest.py`'s `client` fixture continues to use the
  CSV source via `app.dependency_overrides`. No SQL setup needed for
  the 22 existing tests.

## Rollout

1. Ship steps 1–4 with backend still defaulting to CSV. All existing
   tests pass. SQL code paths exist but aren't hit by default.
2. On a dev-only window, Trey flips `PMD_PRODUCTION_REPORT_BACKEND=sql`
   locally. We verify `/api/health`, `/api/production-report/latest`,
   and `/api/production-report/history?days=31` against real data.
3. Compare SQL output side-by-side with CSV for a known period (the
   CSV was originally an export of this table, so values should
   match or be explainable by drift).
4. If the dev test is clean, SQL becomes the documented default in
   `RUNBOOK.md` and the CSV source gets demoted to "test fixture only"
   in that doc.

## Open items

- **Timezone on `PRODDATE` / `DTM`**: SQL Server `datetime` has no TZ
  info. Current assumption: they're plant-local (Central Time). We
  already compute the "today" cutoff in UTC in
  `services.get_history`, which will be slightly wrong at the day
  boundary (up to ~6h off depending on DST). Track the discrepancy;
  revisit once the dashboard is in plant users' hands. The fix (if
  needed) is to compute the cutoff in the plant TZ — one line change.
- **Encryption vs self-signed cert**: conn string currently ends with
  `Encrypt=yes;TrustServerCertificate=yes`. Fine for dev; revisit the
  TrustServerCertificate relaxation before production deploy.
- **Pool sizing**: `minsize=1, maxsize=4` is a guess. Revisit when the
  dashboard has >10 concurrent viewers.

## References

- `tasks/decisions/001-stack-and-source-boundary.md` — the parent ADR
- `ARCHITECTURE.md` §5 (Source Protocol) and §9 (second-implementation recipe)
- `context/sample-data/production-report/payload-schema.md`
