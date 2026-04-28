# Backend Architecture

A reference for engineers who need to understand — or explain — how the
FastAPI service under `backend/app/` actually works. It starts with a
high-level request flow and then walks every layer of the codebase in
the order a request traverses them.

The root-level `ARCHITECTURE.md` covers the whole project (frontend,
deployment, data sources). **This document is backend-only** and
focuses on the FastAPI code.

---

> **Phase 13 update (2026-04-28):** the document was authored when CSV
> and SQL were both production sources selectable by
> `PMD_PRODUCTION_REPORT_BACKEND`. Phase 13 made
> `SqlProductionReportSource` the only production implementation. CSV
> survives as a test-only fixture under `tests/_fixtures/csv_source.py`
> so the existing ~30 API tests can run without SQL Server. The
> `production_report_backend` and `production_report_csv_path`
> Settings fields are gone, the `get_production_report_source` DI
> provider no longer branches, and `department_name` on
> `ProductionReportRow` / `ProductionReportEntry` is non-null
> (the SQL source synthesizes a `Dept <id>` fallback on the rare
> Departments LEFT JOIN miss). Sections below that reference the
> conditional branching, the missing Settings fields, or the CSV
> source file under `app/integrations/...` describe historical
> state -- the Protocol pattern itself still holds.

---

## 1. High-level workflow

The backend is a read-only FastAPI service. It exposes a handful of
HTTP endpoints, pulls its production-report data from a SQL Server
instance and its interval-metric data from Flow's REST API, shapes
both with Pydantic, and returns JSON. The frontend polls those
endpoints every 30–300 seconds.

```
                   ┌──────────────────────────────┐
                   │  Browser / Dashboard (poll)  │
                   └──────────────┬───────────────┘
                                  │ HTTP GET /api/...
                                  ▼
          ┌──────────────────────────────────────────────┐
          │  ASGI server (uvicorn)                       │
          │  → CorrelationIdMiddleware  (adds X-Corr-ID) │
          │  → FastAPI router                            │
          └──────────────┬───────────────────────────────┘
                         │ matched route
                         ▼
          ┌──────────────────────────────────────────────┐
          │  Route handler  (backend/app/api/routes/*)   │
          │  — validates query params                    │
          │  — resolves dependencies via Depends(...)    │
          │  — calls exactly one service function        │
          │  — returns a Pydantic response model         │
          └──────────────┬───────────────────────────────┘
                         │ service call
                         ▼
          ┌──────────────────────────────────────────────┐
          │  Service  (backend/app/services/*)           │
          │  — business logic (filtering, rollups)       │
          │  — source-agnostic (takes the Protocol)      │
          └──────────────┬───────────────────────────────┘
                         │ source call
                         ▼
          ┌──────────────────────────────────────────────┐
          │  Source implementation  (integrations/*)     │
          │  — CsvProductionReportSource (local file)    │
          │      or                                      │
          │  — SqlProductionReportSource (aioodbc pool)  │
          └──────────────┬───────────────────────────────┘
                         ▼
             CSV file  ─or─  SQL Server (Azure Managed)
```

Three ideas hold the whole thing together.

**One abstraction boundary.** Routes and services never know whether
their data came from a file or a database. They depend on the
`ProductionReportSource` Protocol (`integrations/production_report/base.py`).
Two concrete classes implement it today; swapping between them is a
configuration change, not a code change.

**Dependency injection, not globals.** The source is resolved per
request by a FastAPI `Depends(...)` provider in `api/dependencies.py`.
That provider reads `Settings.production_report_backend` and either
hands back a `CsvProductionReportSource` or a `SqlProductionReportSource`
wired to the app's pool. Tests swap it out via `app.dependency_overrides`
— no monkeypatching, no module globals.

**Async all the way down.** Every handler, service, and source method
is `async def`. The CSV source wraps its blocking file I/O in
`asyncio.to_thread`; the SQL source uses `aioodbc` natively. That keeps
the event loop free so other requests aren't starved while a slow
source is in flight.

---

## 2. Module map

```
backend/app/
├── main.py                 # Application factory, lifespan, static mount
├── core/
│   ├── config.py           # Settings via pydantic-settings
│   ├── correlation.py      # X-Correlation-ID middleware + ContextVar
│   ├── logging.py          # structlog → JSON; stamps correlation IDs
│   └── snapshot.py         # Snapshot-cache Protocol (seam; not active yet)
├── api/
│   ├── dependencies.py     # Depends(...) providers — pick CSV vs SQL
│   └── routes/
│       ├── health.py       # GET /api/health
│       ├── sites.py        # GET /api/sites
│       └── production_report.py  # GET /latest, GET /range, GET /latest-date
├── schemas/                # Pydantic response models
│   ├── health.py
│   ├── sites.py
│   └── production_report.py
├── services/               # Source-agnostic business logic
│   ├── sites.py
│   └── production_report.py
└── integrations/
    ├── production_report/
    │   ├── base.py         # Protocol + ProductionReportRow + SourceStatus
    │   ├── csv_source.py   # CsvProductionReportSource
    │   ├── sql_source.py   # SqlProductionReportSource
    │   └── queries/        # *.sql files loaded at construction time
    │       ├── ping.sql
    │       └── select_all.sql
    └── sql/
        ├── pool.py         # aioodbc.create_pool wrapper
        └── queries.py      # load_query() helper
```

Every folder has one job. Routes are thin; services do the thinking;
integrations talk to the world; schemas describe the wire contract;
core holds cross-cutting concerns.

---

## 3. Application startup

`uvicorn app.main:app` imports `main.py`, which calls `create_app()`
at module load. That function is the single place where the FastAPI
instance is built.

```python
# backend/app/main.py  (excerpt)
def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.api_title,
        version=settings.api_version,
        lifespan=lifespan,
        openapi_tags=[...],
    )
    app.add_middleware(CorrelationIdMiddleware)
    app.include_router(health.router,   prefix="/api/health",            tags=["Health"])
    app.include_router(sites.router,    prefix="/api/sites",             tags=["Sites"])
    app.include_router(production_report.router,
                                        prefix="/api/production-report", tags=["Production Report"])
    # ... static mount for the frontend under "/" ...
    return app
```

Three things happen on startup, in order.

**Settings are resolved.** `get_settings()` is `@lru_cache`'d, so a
single `Settings` instance is built once per process. It reads
`backend/.env`, then any `PMD_*` environment variables, and validates
the result against the `Settings` Pydantic model.

**Middleware and routers are registered.** `CorrelationIdMiddleware`
is installed first so it wraps every subsequent request. Routers are
mounted under `/api/<domain>` prefixes.

**The lifespan context opens.** FastAPI calls the `lifespan`
async-context-manager once at startup and once at shutdown:

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)

    app.state.sql_pool = None
    if settings.production_report_backend == "sql":
        if settings.db_conn_string is None:
            log.error("sql_pool.not_created", reason="backend=sql but no DSN")
        else:
            try:
                app.state.sql_pool = await create_pool(
                    settings.db_conn_string.get_secret_value()
                )
                log.info("sql_pool.created")
            except Exception as exc:
                log.error("sql_pool.create_failed", error_type=type(exc).__name__, error_message=str(exc))

    try:
        yield                      # ── app runs here ──
    finally:
        pool = getattr(app.state, "sql_pool", None)
        if pool is not None:
            pool.close()
            await pool.wait_closed()
        log.info("app.shutdown")
```

Two design choices worth calling out:

**Graceful degradation on pool-create failure.** If `create_pool(...)`
raises (bad DSN, network down, ODBC driver missing), the exception is
logged and `app.state.sql_pool` stays `None`. The process stays up.
`/api/health` then reports the source as `ok=false`, and the
production-report endpoints return **503 Service Unavailable** from
the DI provider rather than bubbling a 500. The dashboard can surface
a per-tile error state instead of blanking the whole page.

**Pool stored on `app.state`, not a module global.** That keeps the
pool tied to the app lifecycle, keeps tests from leaking pools between
runs, and is the standard FastAPI idiom for per-app resources.

After `yield`, the pool is closed and drained. Shutdown logs
`sql_pool.closed` (or `sql_pool.close_failed` if `.close()` itself
throws).

---

## 4. The request lifecycle

Take a single call — `GET /api/production-report/latest?site_id=101` —
and follow it through the stack.

### 4.1  ASGI entry and middleware

Uvicorn accepts the TCP connection and parses the HTTP request into an
ASGI `scope` + `receive` + `send` trio. The FastAPI app sees it first
through `CorrelationIdMiddleware`:

```python
# backend/app/core/correlation.py  (excerpt)
async def dispatch(self, request, call_next):
    cid = request.headers.get(self._header) or str(uuid4())
    token = correlation_id_var.set(cid)       # stash in ContextVar
    try:
        response = await call_next(request)   # run the route
        response.headers[self._header] = cid  # echo back
        return response
    finally:
        correlation_id_var.reset(token)
```

If the client passes `X-Correlation-ID`, we reuse it; otherwise we
mint a UUID4. Either way the ID is written into a `contextvars.ContextVar`
that `structlog` reads when it formats log lines. Every log event
emitted during this request — from route handlers, services, and the
SQL source — will carry the same `correlation_id` field.

The `finally` clause resets the `ContextVar` so the ID doesn't bleed
into the next task on the same event loop.

### 4.2  Routing

FastAPI's router matches `/api/production-report/latest` against the
registered routes. It finds the handler registered in
`api/routes/production_report.py`:

```python
@router.get("/latest", response_model=ProductionReportLatestResponse, ...)
async def latest(
    production_report: ProductionReportSourceDep,
    site_id: Annotated[str | None, Query(...)] = None,
) -> ProductionReportLatestResponse:
    rows = await get_latest_per_workcenter(production_report, site_id=site_id)
    return ProductionReportLatestResponse(
        count=len(rows),
        generated_at=datetime.now(UTC),
        entries=[_to_entry(r) for r in rows],
    )
```

Two things happen before the function body runs.

**Query params are coerced and validated.** `site_id: Annotated[str | None, Query(...)]`
tells FastAPI to parse `?site_id=...` as an optional string. On the
`/history` endpoint, `days: Annotated[int, Query(ge=1, le=365)]` adds
range validation — out-of-range values get a **422 Unprocessable Entity**
with a Pydantic error body, *never reaching* the handler body.

**Dependencies are resolved.** `ProductionReportSourceDep` expands to
`Annotated[ProductionReportSource, Depends(get_production_report_source)]`.
FastAPI calls that provider and passes the return value in as the
`production_report` argument. That's the subject of the next section.

### 4.3  Dependency resolution

`api/dependencies.py` is the switchboard that picks which concrete
source the request gets:

```python
def get_production_report_source(request: Request) -> ProductionReportSource:
    settings = get_settings()
    if settings.production_report_backend == "sql":
        pool = getattr(request.app.state, "sql_pool", None)
        if pool is None:
            raise HTTPException(
                status_code=503,
                detail=("SQL source unavailable: pool not initialized. "
                        "Check startup log for sql_pool.create_failed or "
                        "sql_pool.not_created."),
            )
        return SqlProductionReportSource(pool=pool)
    return CsvProductionReportSource(settings.production_report_csv_path)
```

Three things to notice:

**It takes the FastAPI `Request` as a parameter.** That's how it reaches
`request.app.state.sql_pool` — the pool the lifespan created at startup.
FastAPI recognises the `Request` type annotation and injects it
automatically.

**No `@lru_cache`.** The earlier iteration cached this provider but
that broke the SQL branch: a cached empty-key function would keep
handing back a stale `SqlProductionReportSource` bound to a long-dead
pool. Since both concrete sources are cheap to construct (they just
hold references), dropping the cache costs nothing measurable.

**503 instead of 500 when SQL is configured but broken.** This is what
"graceful degradation" actually looks like at the API boundary. The
error is explicit — the client can show a helpful message instead of
a generic failure.

**Test override path.** `backend/tests/conftest.py` registers
`app.dependency_overrides[get_production_report_source] = lambda: CsvProductionReportSource(sample_csv_path)`.
Every test runs against the committed sample TSV file regardless of
what `PMD_PRODUCTION_REPORT_BACKEND` is set to. Overrides are cleared
in the fixture teardown so tests don't leak state.

### 4.4  Service layer

The handler calls exactly one function:

```python
rows = await get_latest_per_workcenter(production_report, site_id=site_id)
```

`services/production_report.py` contains the business logic that's
agnostic to the data source:

```python
async def get_latest_per_workcenter(
    source: ProductionReportSource,
    site_id: str | None = None,
) -> list[ProductionReportRow]:
    rows = await source.fetch_rows()
    if site_id is not None:
        rows = [r for r in rows if r.site_id == site_id]

    latest: dict[tuple[str, str], ProductionReportRow] = {}
    for row in rows:
        key = (row.site_id, row.department_id)
        current = latest.get(key)
        if current is None or _sort_key(row) > _sort_key(current):
            latest[key] = row

    return sorted(latest.values(), key=_sort_key, reverse=True)
```

The service never imports a concrete source class. It takes a
`ProductionReportSource` (the Protocol) and calls `fetch_rows()` on
it. Whatever backend the DI provider chose, the service does the same
thing.

`_sort_key(row)` returns `(prod_date, dtm or datetime.min)`. The
`datetime.min` sentinel means rows with a null DTM sort as oldest —
which matters because the SQL column is nullable and legacy rows may
not carry a DTM.

### 4.5  Source layer

`source.fetch_rows()` resolves to one of two implementations.

**CSV path** (`integrations/production_report/csv_source.py`):

```python
async def fetch_rows(self) -> list[ProductionReportRow]:
    return await asyncio.to_thread(self._fetch_rows_sync)

def _fetch_rows_sync(self) -> list[ProductionReportRow]:
    rows: list[ProductionReportRow] = []
    with self._path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for raw in reader:
            rows.append(self._parse_row(raw))
    return rows
```

The file I/O is blocking, so we run it on a worker thread via
`asyncio.to_thread`. The event loop keeps servicing other requests
while the thread reads the file. `_parse_row` handles the tab
delimiter (the file is `.csv`-extensioned but tab-separated), the
`M/D/YY H:MM` date format, and the doubled-quote-escaped JSON in the
`PAYLOAD` column. Empty `DTM` cells parse to `None`.

**SQL path** (`integrations/production_report/sql_source.py`):

```python
async def fetch_rows(self) -> list[ProductionReportRow]:
    async with (
        self._pool.acquire() as conn,
        conn.cursor() as cur,
    ):
        await cur.execute(self._select_all_sql)
        raw_rows = await cur.fetchall()
    return [self._row_to_dataclass(r) for r in raw_rows]
```

This is natively async — aioodbc's `acquire()`, `cursor()`, `execute()`,
and `fetchall()` all return awaitables. The combined `async with`
acquires a connection from the pool, opens a cursor against it, runs
the query loaded at construction time, and releases both when the
block exits (even on exception).

`_row_to_dataclass` does the type normalisation that keeps the two
sources interchangeable:

| SQL column       | SQL type       | `ProductionReportRow` field | Note                                   |
|------------------|----------------|-----------------------------|----------------------------------------|
| `ID`             | int            | `id: int`                   | straight cast                          |
| `PRODDATE`       | datetime       | `prod_date: datetime`       | driver returns `datetime` directly     |
| `PROD_ID`        | varchar        | `prod_id: str`              | —                                      |
| `SITE_ID`        | int            | `site_id: str`              | **cast to str** — matches JSON/frontend |
| `DEPARTMENT_ID`  | int            | `department_id: str`        | **cast to str** — same reason          |
| `PAYLOAD`        | nvarchar(max)  | `payload: dict[str, Any]`   | `json.loads` (empty → `{}`)            |
| `DTM`            | datetime NULL  | `dtm: datetime \| None`     | NULL passes through as `None`          |

Those int→str casts are the key to the boundary holding. The CSV path
reads strings out of a text file; the SQL path gets ints from the
driver. Normalising to `str` at the source layer means the service,
schemas, and frontend don't care.

### 4.6  Response shaping

The service returns `list[ProductionReportRow]` — our internal frozen
dataclass. The route handler converts each row to a
`ProductionReportEntry` (the Pydantic model that matches the wire
contract) and wraps them in the response envelope:

```python
return ProductionReportLatestResponse(
    count=len(rows),
    generated_at=datetime.now(UTC),
    entries=[_to_entry(r) for r in rows],
)
```

FastAPI serialises the Pydantic model to JSON and writes it back
through the ASGI send channel. The correlation middleware stamps the
response header on the way out. Uvicorn writes the HTTP response.
Round trip complete.

---

## 5. The source abstraction

This is the one piece of the codebase that's worth understanding in
detail, because it's the reason the CSV→SQL swap was a zero-code
change at the consumer layer.

### 5.1  The Protocol

```python
# integrations/production_report/base.py
@runtime_checkable
class ProductionReportSource(Protocol):
    name: str
    async def ping(self) -> SourceStatus: ...
    async def fetch_rows(self) -> list[ProductionReportRow]: ...
    async def list_site_ids(self) -> list[str]: ...
```

Four contract points:

1. A `name` attribute used in health-check output (`csv:production_report`
   vs `sql:production_report`).
2. A `ping()` returning `SourceStatus` — never raises, always returns a
   status. Health checks depend on this.
3. A `fetch_rows()` returning every row the source knows about, already
   parsed into our frozen dataclass.
4. A `list_site_ids()` returning distinct site IDs. The default
   implementation can derive this from `fetch_rows()`; the SQL source
   could override it with `SELECT DISTINCT` if the table ever gets big.

The Protocol is `@runtime_checkable` so `isinstance(x, ProductionReportSource)`
works — useful in tests and for FastAPI's type introspection.

### 5.2  The two implementations

| Aspect             | `CsvProductionReportSource`      | `SqlProductionReportSource`             |
|--------------------|----------------------------------|------------------------------------------|
| Backing store      | Tab-delimited file on disk       | `IA_ENTERPRISE.[UNS].[SITE_PRODUCTION_RUN_REPORTS]` |
| Driver             | stdlib `csv`, `json`             | `aioodbc` + ODBC Driver 17 for SQL Server |
| Concurrency model  | `asyncio.to_thread(sync_fn)`     | Native async, pool-backed (1–4 conns)    |
| Auth               | POSIX file perms                 | SQL auth (UID/PWD in DSN)                |
| Health check       | File exists + header readable    | `SELECT 1` returns `1`                   |
| Constructor input  | `Path` to the file               | `aioodbc.Pool` instance                  |
| Selected when      | `production_report_backend=csv`  | `production_report_backend=sql`          |

They look nothing alike internally. They look identical from the
outside.

### 5.3  Query file loading

The SQL source follows the project rule that non-trivial SQL lives in
`.sql` files, not in Python strings. Queries are loaded **at
construction time**:

```python
class SqlProductionReportSource:
    def __init__(self, pool: aioodbc.Pool) -> None:
        self._pool = pool
        self._ping_sql = load_query(_QUERIES_DIR, "ping")
        self._select_all_sql = load_query(_QUERIES_DIR, "select_all")
```

If a `.sql` file is missing, construction fails at app startup
instead of at request time. That's deliberate — miswiring should be
loud and early.

`load_query` itself is a four-line helper in `integrations/sql/queries.py`
that just returns the file contents as a string. Parameterisation is
still the caller's responsibility: `?` placeholders passed through the
driver, never f-strings or concatenation. The two current queries
don't take parameters, but when `fetch_rows` grows a `WHERE site_id = ?`
variant, it'll use `cur.execute(sql, (site_id,))`.

### 5.4  The pool

`integrations/sql/pool.py` is a one-function wrapper around
`aioodbc.create_pool`:

```python
async def create_pool(dsn, *, minsize=1, maxsize=4) -> aioodbc.Pool:
    import aioodbc  # lazy import
    return await aioodbc.create_pool(dsn=dsn, minsize=minsize, maxsize=maxsize)
```

The import is lazy so that an environment without `aioodbc` installed
(or without the ODBC driver on the host) doesn't fail to import the
whole app — the CSV backend still works, and `/api/health` can still
respond. The failure is deferred to the point where someone actually
tries to use SQL.

Sizing: a minimum of 1 and maximum of 4 connections is generous for a
single-worker uvicorn serving a polling dashboard. If the deployment
shape changes (multi-worker, more viewers, background refresh),
revisit.

---

## 6. Endpoints

### 6.1  `GET /api/health`

Returns overall API status plus one `SourceHealth` per data source.
Today there's exactly one source, but the handler is written so that
adding a second (external REST API, Ignition historian) is a matter
of adding to the `sources` list — the overall-status derivation is
already generic:

```python
def _derive_overall(sources) -> str:
    if not sources:                         return "ok"
    ok = sum(1 for s in sources if s.ok)
    if ok == len(sources):                  return "ok"
    if ok == 0:                             return "down"
    return "degraded"
```

When there are multiple sources, the handler should fan out:
`await asyncio.gather(*(s.ping() for s in sources))`. The current
single-source implementation awaits serially.

Response shape: `HealthResponse { status, version, environment, checked_at, sources: [SourceHealth] }`.

### 6.2  `GET /api/sites`

Returns the list of sites present in the production-report source,
each with a display name.

The service layer calls `source.list_site_ids()` and joins the results
against `Settings.site_names`. Unknown IDs fall through to a generic
`"Site <id>"` label rather than raising — the selector stays usable
even if `site_names` is stale.

Response shape: `SitesResponse { count, sites: [SiteInfo { id, name }] }`.

### 6.3  `GET /api/production-report/latest?site_id=<optional>`

Returns the most recent row per `(site_id, department_id)`. If
`site_id` is provided, only that site's rows are considered.

Ordering semantics:
- Primary sort key: `prod_date` descending.
- Tiebreaker: `dtm` (upstream write time) descending, with `None`
  sorting as oldest via the `datetime.min` sentinel.

Response shape: `ProductionReportLatestResponse { count, generated_at, entries: [ProductionReportEntry] }`.

### 6.4  `GET /api/production-report/range?site_id=<optional>&from_date=YYYY-MM-DD&to_date=YYYY-MM-DD`

Returns every row within ``[from_date, to_date]`` inclusive. Bounds
are compared against ``prod_date.date()`` so time-of-day doesn't
affect inclusion. `from_date = to_date` is the single-day variant
used by the dashboard's day-picker mode.

Validation:

- `from_date` and `to_date` both required; Pydantic parses ISO-8601
  dates and rejects anything else with 422.
- `from_date > to_date` → 422 with a descriptive detail.
- Window width > 400 days → 422. Guards against accidental
  full-table scans; the dashboard's month mode never exceeds 31
  days, so the ceiling is generous but bounded.
- Anything that gets past the route-layer checks and into
  `get_range()` is also validated there (defensive -- the service
  is callable from non-HTTP contexts).

Response shape: `ProductionReportRangeResponse { count, from_date,
to_date, site_id, generated_at, entries, conveyor_totals }`. The
envelope is identical to the old `ProductionReportHistoryResponse`
except `days` is replaced by the two explicit date bounds.

Unlike `/latest`, multiple entries per `(site_id, department_id)`
are expected when the window spans multiple reports. The frontend
groups client-side and dispatches per-workcenter: one report =>
KPI cards + asset table; two or more reports => history table.

### 6.5  `GET /api/production-report/latest-date?site_id=<required>`

Returns the newest `prod_date.date()` for the given site, or
`latest_date: null` when the site has no reports at all. Used by
the dashboard on bootstrap to seed the day picker with a date that
actually has data -- sidesteps the "Today is often empty" problem
that drove the Phase 7 redesign.

`site_id` is **required** here (unlike the filters on `/latest` and
`/range`, where it's optional). A missing `site_id` returns 422.
The endpoint doesn't cross sites -- "which day does the dashboard
land on" is a per-site question.

Response shape: `LatestDateResponse { site_id, latest_date: date | null }`.

Implementation is the default "derive from `fetch_rows()`": the
source loads all rows and the service takes `max(prod_date.date()
for r where r.site_id == site_id)`. Fine today; if the SQL source
ever scales beyond a reasonable page-load latency, override the
Protocol with a dedicated `SELECT MAX(PRODDATE) WHERE SITE_ID = ?`
query.

### §6.6 Phase 8 enrichment fields (shift / weather / notes)

Every `ProductionReportEntry` in `/range` and `/latest` carries six
additional optional fields populated by the enriched `select_all.sql`
query:

| Field | Type | Source |
|---|---|---|
| `shift` | `str \| None` | `SITE_PRODUCTION_RUN_HISTORY.SHIFT` |
| `weather_conditions` | `str \| None` | `SITE_PRODUCTION_RUN_HISTORY.WEATHER_CONDITIONS` (STUFF'd list) |
| `avg_temp` | `float \| None` | `SITE_PRODUCTION_RUN_HISTORY.AVG_TEMP` |
| `avg_humidity` | `float \| None` | `SITE_PRODUCTION_RUN_HISTORY.AVG_HUMIDITY` |
| `max_wind_speed` | `float \| None` | `SITE_PRODUCTION_RUN_HISTORY.MAX_WIND_SPEED` |
| `notes` | `str \| None` | `SITE_PRODUCTION_RUN_COMMENTS.NOTES` |

All fields are optional because:
- The CSV source has no weather or notes data; every CSV row reports
  `None` for the six fields.
- SQL LEFT JOIN misses produce NULL (e.g. a report without a history
  row yet). The dataclass surfaces those as `None`.

`weather_conditions` is a comma-separated STUFF of distinct
conditions during the shift. Frontend severity-ranks them to pick an
icon (see `tasks/decisions/003-enrichment-joins.md` D4 / D5) while
preserving the full list for the Details modal.

Neither the service layer nor `compute_conveyor_totals` touches
these fields -- they're pure passthrough from the source layer to the
wire envelope.

See `tasks/decisions/003-enrichment-joins.md` for the SP-vs-own-query
decision and the full rationale.

### Shared envelope field: `conveyor_totals` (Phase 5)

Both `/latest` and `/range` responses carry a
`conveyor_totals: dict[str, ConveyorTotals]` field keyed by
`"<site_id>:<department_id>"`. Each value is a belt-scaled tonnage
aggregate computed by `services/production_report.compute_conveyor_totals`:
a per-conveyor sum (one entry per `/^C\d+$/` key found in the
payload's `Metrics`), plus a grand total, a conveyor count, and
the number of source reports that contributed. Workcenters whose
payloads contain no `CX` keys are omitted from the dict entirely.
This field powers the conveyor-totals bar chart under each
workcenter panel on the dashboard. Each `ConveyorTotals` also
carries `product_mode: dict[str, str | None]` -- the most
*frequent* `Produced_Item_Description` per conveyor across the
window (placeholders excluded, ties broken toward the newest
report) -- which the dashboard renders as the second line of each
bar's x-axis label.

The aggregate is always over "whatever rows the service passed
in," so for `/range` it follows the selected window automatically:
a single-day pick sums across that day's reports, a month pick
sums across that month's reports. No window logic lives in the
aggregator; that's a deliberate separation between filter (service
layer) and roll-up (service layer, pure function). See
`PAYLOAD-CONTRACT.md` for why the chart uses strict `CX` matching
rather than the shape-based asset discovery used for the table
rows.

### Removed in Phase 7: `GET /api/production-report/history?days=N`

The rolling-window endpoint from Phase 2.1 was removed when the
dashboard switched to absolute windows. Callers wanting "last N
days" build `from = today - (N-1)`, `to = today` and call `/range`
-- same data, explicit semantics. A regression test in
`tests/api/test_production_report.py` asserts 404 on the removed
path so it doesn't silently come back.

See `tasks/decisions/002-absolute-time-filter.md` for the full
rationale.

---

## 7. Configuration

`core/config.py` defines `Settings` on `pydantic_settings.BaseSettings`.
Every field has a default and a description. Loading order, by
pydantic-settings convention:

1. Defaults in the class definition.
2. Values from `backend/.env` (loaded automatically because
   `model_config.env_file = ".env"`).
3. Environment variables prefixed `PMD_` (override the above).

### 7.1  Secrets

`db_conn_string` is typed `SecretStr | None`. `SecretStr` keeps the
value out of default `repr()` and log output — `Settings(...).db_conn_string`
prints as `SecretStr('**********')`. The raw value is fetched at point
of use via `.get_secret_value()` (see `main.py` lifespan).

`validation_alias=AliasChoices("PMD_DB_CONN_STRING", "DB_CONN_STRING")`
accepts either prefix so existing deployment tooling that sets
`DB_CONN_STRING` works without modification.

### 7.2  Backend switch

```python
production_report_backend: Literal["csv", "sql"] = "csv"
```

`Literal[...]` means anything other than those two strings fails
validation at startup with a clear Pydantic error. The DI provider
branches on this field.

### 7.3  Cached access

```python
@lru_cache
def get_settings() -> Settings:
    return Settings()
```

One process → one `Settings` instance. Tests that need to mutate the
environment call `get_settings.cache_clear()` after `os.environ[...] = ...`.

---

## 8. Logging and correlation

Logging is JSON-formatted structlog, configured once in the lifespan:

```python
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        _add_correlation_id,                      # stamps correlation_id
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(log_level),
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)
```

Each log line looks like:

```json
{"event": "sql_pool.created", "level": "info", "timestamp": "2026-04-23T14:37:59.347624Z",
 "correlation_id": "8c4e...", "build_tag": "2026-04-23-sql-step3"}
```

The `correlation_id` field comes from the `contextvars.ContextVar`
that `CorrelationIdMiddleware` set at the top of the request. That
means every log line emitted during one request can be grepped out of
the stream by a single ID — including logs emitted from inside
`asyncio.to_thread` calls (ContextVars propagate to spawned threads
in Python 3.11+).

**Known gap:** stdlib `logging` (uvicorn access logs, Python warnings)
doesn't currently route through structlog. Those come out as plain
text. Adding a `ProcessorFormatter` bridge is the one-line fix when we
need everything as JSON.

**Never log:**
- Raw request bodies.
- SQL parameters (they may carry sensitive values).
- The `db_conn_string` (it's `SecretStr`, which already prevents
  accidental `repr()` exposure — but don't `.get_secret_value()` into
  a log call).

---

## 9. Error handling and graceful degradation

Three distinct failure modes, handled at different layers:

**Upstream source down at startup.** Lifespan logs the error, leaves
`app.state.sql_pool = None`, and keeps the process alive. This matters
because a misconfigured DSN during a deploy shouldn't prevent the
rest of the app from serving.

**Upstream source down per request.** When `production_report_backend=sql`
and the pool is `None`, the DI provider raises `HTTPException(503, ...)`
with a diagnostic detail pointing at the startup log event name
(`sql_pool.create_failed` / `sql_pool.not_created`). The client gets
a clean 503 JSON body, not a stack trace.

**Source ping returns `ok=False`.** `SqlProductionReportSource.ping()`
catches every exception and converts it to `SourceStatus(ok=False, detail=...)`.
`/api/health` still returns **HTTP 200** with `status="degraded"` or
`status="down"` in the body — the dashboard polls `/api/health` to
decide which tiles to grey out, so crashing the health endpoint on a
bad source would defeat the purpose.

Everything else (unexpected `KeyError` in row parsing, network error
during `fetch_rows`, etc.) propagates to FastAPI's default 500 handler.

---

## 10. Testing

`backend/tests/conftest.py` provides two fixtures:

```python
@pytest.fixture
def sample_csv_path() -> Path:
    return SAMPLE_CSV_PATH  # context/sample-data/production-report/sample.csv

@pytest.fixture
def client(sample_csv_path) -> Iterator[TestClient]:
    app.dependency_overrides[get_production_report_source] = (
        lambda: CsvProductionReportSource(sample_csv_path)
    )
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
```

Two things make this work cleanly:

**Dependency override, not monkeypatch.** Tests tell FastAPI "use this
factory for this dependency." The rest of the app has no idea it's
in test mode. No import-time fiddling, no module globals to restore.

**Committed fixture data.** The sample TSV under
`context/sample-data/` is the canonical test input. Tests assert against
row counts, field values, and ordering that match the fixture file.
When the fixture evolves, tests evolve with it deliberately.

**Per-source unit tests** (`tests/integrations/test_sql_source.py`)
don't hit a real database. They use fake `Pool`/`Connection`/`Cursor`
async context managers that replay canned row data. That keeps the
test suite fast and deterministic while still exercising the
int→str coercion, JSON parsing, and null-DTM handling that make up
the source's contract.

Run: `cd backend && pytest` — currently **30 passing** (22 API-level,
8 SQL source).

---

## 11. Static frontend mount

One detail that tends to surprise people reviewing `main.py`:

```python
@app.get("/", include_in_schema=False)
async def root_index() -> FileResponse:
    return FileResponse(index_html)

app.mount("/", StaticFiles(directory=fd, html=True), name="frontend")
```

Why the explicit `/` handler *before* the mount?

`StaticFiles(html=True)` will serve `index.html` for `/` automatically —
but only under certain request shapes, and on Windows with some
reverse-proxy paths we saw a brief FOUC where a stale redirect was
served instead. Registering an explicit `@app.get("/")` first makes
the root-path response deterministic: one handler, one file. The
mount still handles `/app.js`, `/app.css`, and everything else.

The `/api/__ping` endpoint sits under `/api/` deliberately — that
namespace is never shadowed by the static mount, so it's a reliable
liveness probe even when the frontend dir moves or disappears.

---

## 12. Extension points

Two things you'll likely do next.

### 12.1  Adding a new production-report source

Say we add an Ignition Web API as a third source.

1. Create `integrations/production_report/ignition_source.py`.
2. Implement `ping()`, `fetch_rows()`, `list_site_ids()`, and `name`
   against the Protocol.
3. Add `"ignition"` to the `production_report_backend` Literal type.
4. Add a branch to `api/dependencies.py`.
5. Add any new config fields to `core/config.py`.

No changes to routes, services, or schemas.

### 12.2  Adding a new endpoint

Say we add `GET /api/equipment/status`.

1. Define the response model in `schemas/equipment.py`.
2. Define a source Protocol and at least one implementation in
   `integrations/equipment/` (mirror the production-report layout).
3. Define a service function in `services/equipment.py` that takes the
   Protocol.
4. Add a DI provider in `api/dependencies.py`.
5. Create `api/routes/equipment.py` with a thin handler.
6. Mount the router in `main.py`.

The rule of thumb from the project CLAUDE.md holds: routes validate
and delegate, services reason, integrations talk to the world,
schemas describe the wire. If you find yourself doing SQL or HTTP in
a route handler, back up — it belongs one layer down.

---

## 13. Deployment paths

The same FastAPI code runs in two deployment shapes, selected at
runtime — there are no `#ifdef`-style branches in the code itself.

**Local venv (primary dev loop).** `uvicorn app.main:app --reload`
from `backend/` with an activated Python 3.12 venv. Reads
`backend/.env`, uses the host's ODBC Driver 17 installation. Binds
host port 8000 by default.

**Docker Desktop + WSL2 (production-shaped).** `docker compose up
--build` from the repo root. The Dockerfile (`backend/Dockerfile`)
starts from `python:3.12-slim-bookworm`, installs Driver 17 from
Microsoft's apt repo, installs `requirements.txt`, and copies
`backend/`, `context/`, and `frontend/` into `/app/` so
`core/config.py`'s `parents[3]` path logic resolves the same way.
Compose publishes host port 8001 → container port 8000, reads the
same `backend/.env` via `env_file:` (never baked into the image),
and bind-mounts `context/` and `frontend/` read-only so sample-data
and frontend edits don't require a rebuild.

Two implications worth calling out:

- **`backend/.env` is the single source of truth for secrets.** Both
  paths read it, neither path copies it anywhere. Rotating a DB
  password is a one-file change.
- **Paths match.** The Dockerfile deliberately lands code at
  `/app/backend/app/...` so that the relative-path assumptions in
  `core/config.py` (`parents[3]` to reach repo root, plus
  `context/sample-data/...` and `frontend/` siblings) work without
  env-var overrides. Keep this in mind if you restructure config —
  both paths will need the same treatment.

See `RUNBOOK.md` for concrete commands, healthcheck behavior, and
troubleshooting both paths.

---

## 14. What's deliberately not here

For completeness, a short list of things you might expect in a
FastAPI architecture doc but aren't present because they aren't in
the codebase yet:

- **Authentication.** Deferred; interim deployment is network-restricted.
  When it lands, it'll be middleware-level (bearer token or OIDC) and
  documented here.
- **Response caching.** The `SnapshotStore` Protocol in `core/snapshot.py`
  is shipped as an interface for later. Routes don't use it today; they
  hit the source on every request. Revisit when polling concurrency
  makes it uneconomical.
- **Rate limiting / retry / circuit breakers.** Not needed on a
  read-only intranet API serving ~dozens of clients. When external
  REST sources land, retries with exponential backoff go in the
  integration layer, not the service layer.
- **Multi-worker concerns.** The in-memory snapshot store and per-process
  `@lru_cache` on settings assume a single worker. When we outgrow that,
  the snapshot store swaps to Redis (same Protocol) and settings become
  re-read on each worker boot (already true — `@lru_cache` is per-process).

---

*Last updated: 2026-04-23, against build tag `2026-04-23-sql-step3`.*
