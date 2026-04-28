# Architecture — production-metrics-dashboard

Technical reference for the development team. Covers the overall data
flow, how the backend is structured in OOP, how the dashboard consumes
it, and concrete recipes for adding endpoints and new data sources.

Read this top to bottom the first time. After that, use the recipes
and layout sections as references. Longer-form decision rationale
lives in `tasks/decisions/001-stack-and-source-boundary.md`. Day-to-day
commands and URLs live in `RUNBOOK.md`.

---

> **Phase 13 update (2026-04-28):** the document was authored when CSV
> and SQL were both production-source options selected by
> `PMD_PRODUCTION_REPORT_BACKEND`. Phase 13 consolidated to SQL-only --
> `SqlProductionReportSource` is now the single production
> implementation. The CSV reader survives under
> `backend/tests/_fixtures/csv_source.py` purely as a deterministic
> test fixture so the API test suite can run without SQL Server.
> The Protocol-pattern rationale below still stands (it's why the
> consolidation was a near-zero-code change at the consumer layer);
> code examples that reference `Settings.production_report_backend`
> or `Settings.production_report_csv_path` are historical -- those
> fields are gone.

---

## 1. What this is

A read-only HTTP API plus a static HTML/JS dashboard that together
surface plant production metrics to engineers, operators, and
management. The API aggregates data from three heterogeneous sources
behind one consistent JSON contract; the dashboard polls the API on
a 1-5 minute cadence and renders cards, tables, and (eventually)
charts.

- Backend: Python 3.12, FastAPI, Pydantic v2, uvicorn.
- Frontend: vanilla HTML + CSS + JS (no bundler, no Node). Light/dark
  theme with CSS variables. Served as static files by FastAPI in dev;
  fronted by IIS / Caddy / nginx in production.
- Data sources:
  - SQL Server (via `aioodbc`) — production reports, `Flow_Curated`.
  - External REST APIs (via `httpx.AsyncClient`).
  - Ignition tag historian — access pattern TBD.
- Deployment target: Windows Server, Docker on Windows.
- Intentionally read-only. No mutation endpoints; SQL account has
  read-only grants at the DB level as defense in depth.

---

## 2. 10,000-foot view

```
  +-----------------+         HTTP (poll every 1-5 min)
  |   Dashboard     |  -------------------------------------+
  |  (HTML + JS)    |                                       |
  +-----------------+                                       v
                                              +----------------------------+
                                              |         FastAPI            |
                                              |   app/main.py : create_app |
                                              +-----------+----------------+
                                                          |
                           +------------------------------+-----------------------------+
                           |                              |                             |
                           v                              v                             v
            +---------------------------+   +----------------------------+  +----------------------------+
            |  app/api/routes/*.py      |   |  app/services/*.py          |  |  app/schemas/*.py           |
            |  Thin HTTP handlers       |-->|  Business logic             |  |  Pydantic request/response  |
            |  (validate, call service, |   |  (aggregation, filtering,   |  |  models. Outbound contract. |
            |   return Pydantic model)  |   |   cross-source join, ...)   |  +----------------------------+
            +---------------------------+   +-------------+--------------+
                                                          |
                                                          v
                                         +--------------------------------------+
                                         | app/integrations/<source>/base.py    |
                                         |   Source Protocol (Python Protocol)  |
                                         +------------------+-------------------+
                                                            |
                                           +----------------+-----------------+-----------------+
                                           v                                  v                 v
                                 +-------------------+             +-------------------+   +----------+
                                 |  csv_source.py    |             |  sql_source.py    |   |  ...     |
                                 |  (today)          |             |  (next)           |   |          |
                                 +-------------------+             +-------------------+   +----------+
                                           |                                  |
                                           v                                  v
                                   sample.csv on disk                  SQL Server via aioodbc
```

The three columns moving right from FastAPI correspond to the "three
hats" every request wears: routing (HTTP shape), services (business
logic), and schemas (outbound contract). Integrations sit below the
services and are where source-specific code lives.

---

## 3. Request lifecycle — a single dashboard poll

The dashboard fires `GET /api/production-report/latest?site_id=101`.
Here's every hop the request makes:

1. **Browser** makes the `fetch()` call. `frontend/app.js` drives this
   on a `setInterval` cycle (default 30 s, overridable via
   `?refresh=5000` URL param). User interactions (site toggle,
   time-period buttons) fire an immediate fetch rather than waiting
   for the next tick.

2. **uvicorn / Starlette** accepts the TCP connection and hands the
   ASGI scope to the FastAPI application.

3. **`CorrelationIdMiddleware`** (`app/core/correlation.py`) reads
   any inbound `X-Correlation-ID` header, generates a new UUID if
   absent, stashes it in a `contextvars.ContextVar`, and ensures it
   is echoed in the response header. `structlog` picks this up via a
   processor and stamps it on every log line emitted during the
   request.

4. **Router dispatch.** FastAPI matches `GET /api/production-report/latest`
   to the handler in `app/api/routes/production_report.py`. The route
   declares its dependencies via `Annotated[..., Depends(...)]`:
   ```python
   ProductionReportSourceDep = Annotated[
       ProductionReportSource, Depends(get_production_report_source)
   ]

   async def latest(
       production_report: ProductionReportSourceDep,
       site_id: Annotated[str | None, Query(...)] = None,
   ) -> ProductionReportLatestResponse:
       ...
   ```

5. **Dependency injection.** `get_production_report_source` in
   `app/api/dependencies.py` is an `lru_cache`'d factory that returns
   a process-wide `CsvProductionReportSource` instance wired up from
   `Settings.production_report_csv_path`. Tests override this
   dependency via `app.dependency_overrides` to inject fixtures or
   alternate source implementations.

6. **Service call.** The route calls one business-logic function:
   ```python
   rows = await get_latest_per_workcenter(production_report, site_id=site_id)
   ```
   The service (`app/services/production_report.py`) does the actual
   work: calls `source.fetch_rows()`, applies the `site_id` filter,
   reduces to one row per `(site_id, department_id)` by
   `(prod_date, dtm)` max, and sorts the result.

7. **Source call.** `CsvProductionReportSource.fetch_rows()` opens
   the CSV via `asyncio.to_thread` (file I/O is blocking — wrapping
   in a thread keeps the event loop free), parses rows with
   `csv.DictReader`, unescapes the embedded JSON payload, and returns
   typed `ProductionReportRow` instances.

8. **Pydantic serialization.** The route wraps the rows in a
   `ProductionReportLatestResponse` (from `app/schemas/production_report.py`).
   FastAPI validates the model on the way out and emits JSON with the
   declared shape. Response schemas are single source of truth for
   OpenAPI / Swagger at `/docs`.

9. **Response.** JSON goes back to the browser with the correlation
   ID in its headers. The dashboard's JS parses it, renders the
   workcenter panels, schedules the next poll.

Worth noting: at no point does the route handler touch the file
system, parse CSV, know about SQL Server, or format dates. Every
layer has one job.

---

## 4. Backend layers and where things go

| Folder | Purpose | Rule of thumb |
|---|---|---|
| `backend/app/main.py` | App factory, lifespan, middleware registration, static-file mount. | Wiring only. No business logic. |
| `backend/app/api/routes/` | Thin HTTP handlers grouped by domain. One file per logical group (`health.py`, `sites.py`, `production_report.py`). | Validate input, call ONE service function, return ONE Pydantic model. No SQL, no HTTP to upstreams, no branching business logic. |
| `backend/app/api/dependencies.py` | Factory functions for FastAPI DI (`Depends(...)`). | Returns instances of the source Protocols, NOT concrete classes typed in route signatures. |
| `backend/app/services/` | Business logic, cross-source aggregation, filtering, derived KPIs. | Pure async functions; take a source (or multiple sources) by Protocol, return domain types. No HTTP response shaping here. |
| `backend/app/integrations/<source>/` | All source-specific code. One subfolder per source family (`production_report/`, later `ignition/`, `external/...`). | Protocol in `base.py`, one file per concrete implementation (`csv_source.py`, `sql_source.py`). |
| `backend/app/schemas/` | Pydantic models for request/response bodies. | Types the API over the wire. These define OpenAPI / Swagger. |
| `backend/app/core/` | Cross-cutting infrastructure: `config.py` (pydantic-settings), `logging.py` (structlog), `correlation.py` (X-Correlation-ID middleware + ContextVar), `snapshot.py` (SnapshotStore Protocol + in-memory impl). | Nothing domain-specific lives here. |

A request flows top-to-bottom in that table: route → service → integration.
Dependencies point only downward. A route MAY import from services
and schemas; a service MAY import from integrations; integrations
MUST NOT import from routes or services.

---

## 5. The Source Protocol — our extension seam

This is the most important design choice in the backend and the one
you'll interact with most when adding functionality.

### The problem

We have three data sources today (SQL Server, external REST APIs,
Ignition) and will likely gain more. If route handlers or services
called each source directly, every new source would require changes
up and down the stack, and testing would require real infrastructure.

### The pattern

Each source family defines a **Python `Protocol`** in
`integrations/<family>/base.py`. Concrete classes (CSV, SQL, mock,
etc.) implement the Protocol. Services depend on the Protocol, never
on a concrete class.

Python Protocols are structural typing (duck typing with a type
declaration). A class matches a Protocol if its methods and
attributes match the shape — no `extends` keyword, no registration
required. `@runtime_checkable` lets us use `isinstance(obj, Protocol)`
at runtime when we need to, at a small cost.

### Current example: `ProductionReportSource`

```python
# backend/app/integrations/production_report/base.py
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class SourceStatus:
    ok: bool
    detail: str
    checked_at: datetime


@dataclass(frozen=True)
class ProductionReportRow:
    id: int
    prod_date: datetime
    prod_id: str
    site_id: str
    department_id: str
    payload: dict[str, Any]
    dtm: datetime


@runtime_checkable
class ProductionReportSource(Protocol):
    name: str

    async def ping(self) -> SourceStatus: ...
    async def fetch_rows(self) -> list[ProductionReportRow]: ...
    async def list_site_ids(self) -> list[str]: ...
```

The Protocol says: "anything with these methods and a `name` is a
production-report source." The CSV implementation
(`CsvProductionReportSource`) satisfies it by having those methods;
the SQL implementation (coming next) will satisfy it the same way.
Services and routes only know about the Protocol — they never import
the concrete classes.

### Why async everywhere

Every Protocol method is `async`. CSV reads are synchronous file
I/O, but the CSV source wraps them in `asyncio.to_thread(...)` so
the event loop stays free. This keeps the Protocol uniform: when we
add SQL (truly async via `aioodbc`) or REST (truly async via
`httpx`), no interface change. Adding a blocking source is cheap
(one `to_thread` wrapper); removing async-ness from the interface
later would be painful.

### What this buys us

- **Swap implementations with a DI change.** Point
  `get_production_report_source` at `SqlProductionReportSource`
  instead of `CsvProductionReportSource`. The route, service, and
  tests are unchanged.
- **Test without infrastructure.** Inject a fixture-backed source;
  no SQL Server, no ODBC driver, no network.
- **Introduce new sources without touching routes or services.**
  Adding a weather feed or an Ignition historian read doesn't churn
  the request-path code.

---

## 6. How the dashboard calls the API

The dashboard is a single static HTML file plus one CSS and one JS
file (plus a local `Chart.js`), served by FastAPI's `StaticFiles`
mount. No build step.

### Endpoints consumed

| Endpoint | When called | Purpose |
|---|---|---|
| `GET /api/sites` | On page load | Populate the top-bar site toggle. |
| `GET /api/health` | On load + every poll | Color-code the health pill in the top bar; fill the source-status panel in the sidebar. |
| `GET /api/production-report/latest?site_id={id}` | Today mode: on load + every poll + on site toggle | Render the per-workcenter panels (KPI cards + per-asset table). |
| `GET /api/production-report/history?site_id={id}&days={N}` | Week / Month mode: on mode switch + every poll + on site toggle | Render the per-workcenter history panels (KPI cards + per-date history table). |

### Time-period modes

The dashboard sidebar has three buttons — `Today`, `Week`, `Month` —
that switch the current data view. Each button maps directly to a
backend endpoint and a rendering variant:

| Mode | Endpoint | View |
|---|---|---|
| Today (default) | `/api/production-report/latest` | KPI cards + per-asset table (C1, C3–C8, ...). Single row per workcenter. |
| Week | `/api/production-report/history?days=7` | KPI cards (from the latest row in the window) + per-workcenter history table with columns `Prod. Date | Report ID | Availability % | Performance % | Runtime (min) | Total (tons)`. One row per production report. |
| Month | `/api/production-report/history?days=31` | Same layout as Week, 31-day window. |

Button clicks fire an **immediate fetch** via `refreshData()`; they
don't wait for the next 30s poll tick. Site-toggle clicks do the same.

The `/history` `days` parameter is validated at the query layer
(`1 ≤ days ≤ 365`); out-of-range values return HTTP 422.

### Polling loop (simplified)

```javascript
async function bootstrap() {
  sites = (await fetchJSON("/api/sites")).sites;
  currentSiteId = sites[0].id;
  renderSiteToggle(); renderSiteStrip(); renderChips();
  await Promise.all([refreshHealth(), refreshData()]);  // refreshData dispatches by mode
  setInterval(() => { refreshHealth(); refreshData(); }, REFRESH_MS);
}
```

`REFRESH_MS` defaults to 30000 but is overridable per-session via
`?refresh=<ms>` on the URL (useful for UX iteration).

### Theme (light / dark)

The frontend supports a light/dark theme via CSS variables scoped
under `:root[data-theme="..."]`. A toggle button in the topbar swaps
between the two states.

- Persistence: `localStorage['pmd-theme']` holds `"light"` | `"dark"`.
- First-visit default: `window.matchMedia('(prefers-color-scheme: dark)')`.
- FOUC prevention: a tiny inline `<script>` in `<head>` applies the
  stored theme to `<html data-theme="...">` **before** `app.css` loads,
  so there's no flash of the wrong palette on reload.
- Topbar colors stay dark-chrome in both themes (Fluent pattern); the
  canvas/sidebar/cards flip.

### Error handling

- Any 4xx/5xx is rendered into a red bar at the top of the main area
  via `showError(...)`. The dashboard does NOT blank itself on error
  — the last successfully-fetched data stays visible.
- Per-source health shows as OK / FAIL in the sidebar, independent of
  the overall HTTP status. A slow or unhealthy source degrades
  gracefully per-tile.

### Display conventions for mixed "empty" representations

The raw `PAYLOAD` distinguishes four empty states (see
`context/sample-data/production-report/payload-schema.md`). The
frontend collapses them uniformly on display:

| Value in payload | UI display |
|---|---|
| `null` (not calculable) | `—` |
| `0.0` (calculated zero) | `0.0` |
| `"_"` (placeholder string) | `—` |
| `"None"` (Site placeholder) | `—` |

`null` vs `0.0` is preserved in the JSON so the frontend can show the
difference if we need to later. Today, only `0.0` renders as a number.

---

## 7. Recipe: add a new endpoint

Worked example: you want `GET /api/production-report/{site_id}/{department_id}`
that returns the latest single row for one specific workcenter, with
HTTP 404 if the workcenter doesn't exist.

1. **Define the response schema** in `backend/app/schemas/production_report.py`
   (or a new module under `schemas/` if the shape is unique). Reuse
   existing types when possible.
   ```python
   class ProductionReportEntryResponse(BaseModel):
       entry: ProductionReportEntry
       generated_at: datetime
   ```

2. **Write the service function** in `backend/app/services/production_report.py`
   (or a new service module if it's a new domain). Services take the
   source by Protocol and return domain types (`ProductionReportRow`,
   not `ProductionReportEntryResponse` — shaping is the route's job).
   ```python
   async def get_workcenter_latest(
       source: ProductionReportSource, site_id: str, department_id: str,
   ) -> ProductionReportRow | None:
       rows = await get_latest_per_workcenter(source, site_id=site_id)
       for r in rows:
           if r.department_id == department_id:
               return r
       return None
   ```

3. **Add the route** in `backend/app/api/routes/production_report.py`.
   Thin — validate, call service, shape response, handle "not found".
   ```python
   @router.get(
       "/{site_id}/{department_id}",
       response_model=ProductionReportEntryResponse,
       summary="Latest row for one workcenter",
   )
   async def workcenter_latest(
       production_report: ProductionReportSourceDep,
       site_id: str,
       department_id: str,
   ) -> ProductionReportEntryResponse:
       row = await get_workcenter_latest(production_report, site_id, department_id)
       if row is None:
           raise HTTPException(404, detail=f"No data for {site_id}/{department_id}")
       return ProductionReportEntryResponse(
           entry=ProductionReportEntry(...row),
           generated_at=datetime.now(UTC),
       )
   ```

4. **Add tests** in `backend/tests/api/test_production_report.py`.
   Use the existing `client` fixture; it wires the real sample CSV
   into `app.dependency_overrides`.
   ```python
   def test_workcenter_latest_happy(client):
       r = client.get("/api/production-report/101/127")
       assert r.status_code == 200
       assert r.json()["entry"]["department_id"] == "127"

   def test_workcenter_latest_not_found(client):
       r = client.get("/api/production-report/101/999")
       assert r.status_code == 404
   ```

5. **`pytest`** from `backend/` with the venv active. Green? Done.
   No need to touch the integration layer.

Things NOT to do:

- Do not put business logic (filtering, sorting, 404 mapping) in the
  route. Routes are thin.
- Do not call `source.fetch_rows()` directly from the route. Services
  own source calls.
- Do not return a bare dict. Every response is a Pydantic model so the
  schema shows up in Swagger.

---

## 8. Recipe: add a new data source

Worked example: we want to pull material-lab quality results from an
external REST API at `https://lab.example.com/api/v2/results`.

The pattern below is the same whether the new source is another SQL
server, an FTP CSV drop, an S3 bucket, or something more exotic.

### 8.1 If it's a family we've never used before, create the package

```
backend/app/integrations/lab/
├── __init__.py
├── base.py               # Protocol + domain types
└── rest_source.py        # concrete httpx-based implementation
```

### 8.2 Define the Protocol and domain types in `base.py`

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable
from app.integrations.production_report.base import SourceStatus  # reuse!


@dataclass(frozen=True)
class LabResult:
    sample_id: str
    taken_at: datetime
    site_id: str
    product_code: str
    gradation: dict[str, float]
    compliant: bool


@runtime_checkable
class LabSource(Protocol):
    name: str

    async def ping(self) -> SourceStatus: ...
    async def fetch_results_since(self, site_id: str, since: datetime) -> list[LabResult]: ...
```

### 8.3 Implement against the concrete backend

```python
# backend/app/integrations/lab/rest_source.py
from datetime import UTC, datetime
import httpx
from .base import LabResult, LabSource
from app.integrations.production_report.base import SourceStatus


class RestLabSource:
    name = "rest:lab"

    def __init__(self, base_url: str, api_key: str, timeout_s: float = 5.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_s,
        )

    async def ping(self) -> SourceStatus:
        now = datetime.now(UTC)
        try:
            r = await self._client.get("/healthz")
            r.raise_for_status()
            return SourceStatus(ok=True, detail="reachable", checked_at=now)
        except httpx.HTTPError as exc:
            return SourceStatus(ok=False, detail=str(exc), checked_at=now)

    async def fetch_results_since(self, site_id, since):
        r = await self._client.get("/api/v2/results",
                                   params={"site_id": site_id, "since": since.isoformat()})
        r.raise_for_status()
        return [LabResult(**row) for row in r.json()["results"]]
```

### 8.4 Register a DI provider

```python
# backend/app/api/dependencies.py
@lru_cache
def get_lab_source() -> LabSource:
    s = get_settings()
    return RestLabSource(
        base_url=str(s.lab_base_url),
        api_key=s.lab_api_key.get_secret_value(),
    )
```

Add the config fields to `Settings` in `backend/app/core/config.py`
(with env defaults under the `PMD_LAB_*` prefix).

### 8.5 Write the service

```python
# backend/app/services/lab.py
async def get_recent_results(source: LabSource, site_id: str, hours: int = 24):
    since = datetime.now(UTC) - timedelta(hours=hours)
    return await source.fetch_results_since(site_id, since)
```

### 8.6 Wire the route

```python
# backend/app/api/routes/lab.py
router = APIRouter()
LabSourceDep = Annotated[LabSource, Depends(get_lab_source)]

@router.get("/recent", response_model=LabRecentResponse)
async def recent(source: LabSourceDep, site_id: str, hours: int = 24):
    results = await get_recent_results(source, site_id, hours)
    return LabRecentResponse(count=len(results), results=results)
```

And mount it in `app/main.py`:
```python
app.include_router(lab.router, prefix="/api/lab", tags=["Lab"])
```

### 8.7 Surface it in `/api/health`

Extend `routes/health.py` to ping every source in parallel with
`asyncio.gather(*source.ping() for source in [pr_source, lab_source])`
and add the result to `sources`. The frontend automatically picks up
the new card — no JS change needed unless you want a dedicated tile
layout.

### 8.8 Write the tests

Create `backend/tests/integrations/test_rest_lab_source.py` with
`httpx.MockTransport` so tests don't make real network calls. Create
`backend/tests/api/test_lab.py` with a fake implementation of
`LabSource` injected via `app.dependency_overrides`.

Done. Zero changes to the production-report source, its service, or
its routes.

---

## 9. Adding a second implementation of an existing Protocol

This is the SQL migration. When we're ready to read production reports
from SQL instead of the CSV, the recipe is:

1. Add `backend/app/integrations/production_report/sql_source.py` with
   a `SqlProductionReportSource` class that implements `ping`,
   `fetch_rows`, and `list_site_ids`.

2. Update `get_production_report_source` in `app/api/dependencies.py`
   to return the SQL implementation (gated on a settings flag if we
   want both available during cutover).

3. Update the health endpoint's source-type naming if needed
   (e.g. `sql:production_report` vs `csv:production_report`).

4. Add `SqlProductionReportSource` tests under
   `backend/tests/integrations/` that stand up a test SQL database
   (or use `aioodbc` with a real local instance, gated by an env var
   so CI can skip).

No change to the Protocol, the service, the route, the response schema,
or the frontend. That's the whole point.

---

## 10. Configuration

All settings are declared as typed fields on a `pydantic-settings`
class in `backend/app/core/config.py`:

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="PMD_", case_sensitive=False,
        extra="ignore",
    )

    api_title: str = "Production Metrics Dashboard API"
    api_version: str = "0.1.0"
    environment: str = "local"
    log_level: str = "INFO"
    production_report_csv_path: Path = _DEFAULT_CSV_PATH
    site_names: dict[str, str] = Field(default_factory=...)
    frontend_dir: Path = _DEFAULT_FRONTEND_DIR
```

Override any field via the `PMD_<FIELD_NAME>` environment variable or
a `backend/.env` file. `.env.example` documents the supported
variables. `get_settings()` is `lru_cache`'d so the class is
instantiated once per process; tests that mutate env should call
`get_settings.cache_clear()` and
`get_production_report_source.cache_clear()`.

When adding a new setting: add the field to `Settings`, add an example
to `.env.example`, document in `backend/README.md`.

---

## 11. Observability

### Correlation IDs

Every HTTP request gets an `X-Correlation-ID`:

- Honored from the incoming header if present (so the dashboard can
  assign one and trace the request end-to-end).
- Generated as a UUID4 if absent.
- Echoed in the response header.
- Stored in a `contextvars.ContextVar` and stamped on every
  `structlog` log record emitted during the request.

Implementation: `backend/app/core/correlation.py`.

### Structured JSON logs

`structlog` is configured in `app/core/logging.py` to emit
newline-delimited JSON. Each log record has `event`, `level`,
`timestamp`, and any context fields passed in (e.g.
`correlation_id`, `environment`, `source_name`, custom fields).

From anywhere in the app:
```python
from app.core.logging import get_logger
log = get_logger(__name__)
log.info("source.fetch_rows.completed", source=source.name, rows=len(rows))
```

### Build-tag fingerprint

`app/main.py` defines a `BUILD_TAG` constant and serves it at
`GET /api/__ping`. Useful for confirming which version of the code is
actually responding when `--reload` on Windows misbehaves or a zombie
uvicorn is holding a port. See `RUNBOOK.md` troubleshooting.

### Not yet integrated

- uvicorn's access logs and stdlib `logging` records do NOT flow
  through `structlog` yet. A `ProcessorFormatter` bridge is a small
  follow-up.
- No metrics (Prometheus / OpenTelemetry) yet. Deferred.

---

## 12. The snapshot-cache seam

Polling dashboards re-request the same expensive data many times.
Computing it per-request is wasteful. The pattern we'll move to is:

- A background task refreshes a cached payload on an interval
  (e.g. every 60 s).
- HTTP handlers return whatever snapshot is current.
- N concurrent viewers no longer multiply source load.

The **interface** for this already lives in `app/core/snapshot.py`:

```python
class SnapshotStore(Protocol):
    async def get(self, key: str) -> Snapshot[Any] | None: ...
    async def set(self, key: str, data: Any) -> Snapshot[Any]: ...

class InMemorySnapshotStore: ...   # default, process-local
```

No route currently uses it. That's deliberate — we shipped the seam
so that the eventual migration is a DI change (plus a background
task), not an architectural refactor. When we outgrow single-worker
and need a shared cache, a Redis-backed `SnapshotStore` slots in
without touching the call sites.

---

## 13. Testing

Three test categories live under `backend/tests/`:

| Folder | Purpose | Example |
|---|---|---|
| `tests/api/` | HTTP-level tests using FastAPI's `TestClient`. Exercise routes, serialization, error codes, correlation-ID echo. | `test_health.py`, `test_sites.py`, `test_production_report.py` |
| `tests/integrations/` | Source-level tests that run a concrete implementation against its backend. For CSV, that's the real sample file. For SQL later, an in-memory DB or a gated local instance. | `test_csv_source.py` |
| `tests/services/` (future) | Service-level tests against fake Protocol implementations, when a service gets complex enough to warrant direct coverage. | — |

### Current count: 22 tests

- `test_health.py` — 3 cases (OK response, correlation-ID echo, UUID generation)
- `test_sites.py` — 2 cases (both sites + names, sorted by id)
- `test_production_report.py` — 12 cases (6 `/latest` + 6 `/history`)
- `test_csv_source.py` — 5 cases (ping, missing file, fetch parses all, both sites covered, list_site_ids sorted)

### The `client` fixture

Defined in `backend/tests/conftest.py`. It does three things:

1. Clears `get_production_report_source`'s `lru_cache`.
2. Inserts an override in `app.dependency_overrides` that returns a
   `CsvProductionReportSource` pointed at the committed sample file.
3. Yields a `TestClient` wrapping the app.

This means every API test automatically gets a fresh, CSV-backed app
— no env var juggling, no SQL setup, no mocking required. When adding
tests for a new source, add a similar override.

### Running tests

From `backend/` with the venv active:
```
pytest
```

Config is in `backend/pytest.ini`:
- `asyncio_mode = auto` — no need to decorate async tests.
- `testpaths = tests`.
- `pythonpath = .` — imports resolve from `backend/`.

---

## 14. Repository layout (as of today)

```
production-metrics-dashboard/
├── ARCHITECTURE.md              # this file
├── CLAUDE.md                    # project conventions (source of truth for rules)
├── RUNBOOK.md                   # commands, URLs, troubleshooting
├── backend/
│   ├── app/
│   │   ├── main.py              # factory, lifespan, middleware, static mount, build-tag
│   │   ├── api/
│   │   │   ├── dependencies.py  # DI providers
│   │   │   └── routes/
│   │   │       ├── health.py
│   │   │       ├── sites.py
│   │   │       └── production_report.py    # /latest + /history
│   │   ├── core/
│   │   │   ├── config.py        # pydantic-settings
│   │   │   ├── logging.py       # structlog config
│   │   │   ├── correlation.py   # X-Correlation-ID middleware + ContextVar
│   │   │   └── snapshot.py      # SnapshotStore Protocol + in-memory impl
│   │   ├── integrations/
│   │   │   └── production_report/
│   │   │       ├── base.py      # ProductionReportSource Protocol + types
│   │   │       └── csv_source.py
│   │   ├── services/
│   │   │   ├── production_report.py    # get_latest_per_workcenter, get_history
│   │   │   └── sites.py
│   │   └── schemas/
│   │       ├── health.py
│   │       ├── sites.py
│   │       └── production_report.py    # Entry + LatestResponse + HistoryResponse
│   ├── tests/
│   │   ├── conftest.py          # client fixture
│   │   ├── api/
│   │   │   ├── test_health.py
│   │   │   ├── test_sites.py
│   │   │   └── test_production_report.py    # /latest + /history (12 cases)
│   │   └── integrations/
│   │       └── test_csv_source.py
│   ├── pytest.ini
│   ├── ruff.toml
│   ├── requirements.txt         # direct runtime deps
│   ├── requirements-dev.txt     # + pytest + ruff
│   └── README.md
├── frontend/
│   ├── index.html               # shell: topbar (logo, site toggle, theme toggle, health pill), sidebar, main
│   ├── app.css                  # Fluent-inspired palette, light + dark themes via CSS variables
│   ├── app.js                   # polling loop, renderers, mode state (Today/Week/Month), theme toggle
│   ├── vendor/chart.umd.js      # local Chart.js (loaded but unused; ready for charts)
│   └── README.md
├── context/
│   └── sample-data/
│       └── production-report/
│           ├── sample.csv               # TSV fixture (real + synthetic rows)
│           ├── payload-example.json     # one clean example row
│           ├── payload-schema.md        # PAYLOAD shape documentation
│           └── README.md                # real vs synthetic disclosure
├── examples/                    # read-only reference implementations
└── tasks/
    ├── todo.md                  # active plan + review notes
    ├── lessons.md               # corrections from prior sessions
    ├── decisions/               # ADRs (architecture decision records)
    └── specs/                   # specs for upcoming work
```

---

## 15. What is intentionally NOT here

The following are explicit non-goals today. Each is parked in the ADR
with its triggering condition:

- Authentication/authorization (deployment is network-restricted for POC)
- HA / horizontal scaling / multi-worker concerns
- Redis / distributed caching
- Retry / circuit-breaker machinery beyond per-call timeouts
- Multi-tenancy (one company, multiple sites is not multi-tenancy)
- Docker containerization (coming when deployment shape firms up)
- React / bundlers / Node (vanilla HTML + JS until concrete need)
- Charts (Chart.js is loaded locally in the frontend but no chart
  renders yet; the `/history` endpoint now returns time-series-shaped
  data that's ready to drive sparklines when we add them)

See `tasks/decisions/001-stack-and-source-boundary.md` for the full
rationale and decision criteria.

---

## 16. Further reading

- `CLAUDE.md` — project conventions, code-style rules, where-new-content-goes.
- `RUNBOOK.md` — commands, URLs, troubleshooting, edit-the-sample-data recipe.
- `tasks/decisions/001-stack-and-source-boundary.md` — stack + source boundary ADR.
- `tasks/lessons.md` — patterns and gotchas from prior work.
- `context/sample-data/production-report/payload-schema.md` — PAYLOAD JSON shape.
- `examples/dashboard-mockup/index.html` — aesthetic reference for the frontend.
- `backend/README.md` — how to run locally, environment variables.
- `frontend/README.md` — how the static assets are wired.
