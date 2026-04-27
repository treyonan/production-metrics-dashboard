# ADR-001 — Stack and source boundary

**Status:** Accepted — 2026-04-22
**Context:** Initial architecture for the Dolese Bros Co production-metrics
dashboard. Read-only aggregator over SQL Server, external REST APIs, and an
Ignition historian, served to a plant/management dashboard polling every
1–5 min. POC phase; Windows-only deployment; 50 concurrent viewers
projected.

## Decision

### Backend stack

- **Python 3.12, FastAPI, Pydantic v2, uvicorn.** Right tool for async
  fan-out across heterogeneous sources; Pydantic as the outbound contract;
  OpenAPI/Swagger falls out for free, which the SCADA team will use to
  understand/consume the API.
- **structlog** for JSON logs. stdlib `logging` works but requires more
  boilerplate for correlation-ID propagation; structlog's `contextvars`
  integration makes per-request fields trivial.
- **pytest + pytest-asyncio + httpx test client** for tests.
- **ruff** for lint + format (no separate formatter/linter).
- **venv + pip + requirements.txt** (direct deps, `~=` pins) + a
  `requirements-dev.txt` that includes runtime via `-r`. No `pip-tools`
  lockfile yet; revisit when it hurts.

### Source boundary

- Every external data source is isolated behind a **Protocol** in
  `backend/app/integrations/<source>/base.py`. Routes and services depend
  on the Protocol, never on a concrete class.
- Concrete implementations live alongside the Protocol
  (`csv_source.py`, later `sql_source.py`, `ignition_source.py`, etc.).
- Swapping source backends is a DI change (see
  `app/api/dependencies.py`), not a code change in consumers.

### Data strategy

- **CSV-first.** The production-report source reads the committed
  `context/sample-data/production-report/sample.csv`. This validates the
  API contract against a real consumer (the dashboard) before we take on
  the operational cost of SQL integration.
- **SQL second.** Slots in as a second implementation of
  `ProductionReportSource` once the dashboard is stable. SQL account is
  read-only at the DB level for defense in depth.
- **PAYLOAD typing deferred.** The upstream JSON shape is still
  stabilizing; current rows mix legacy and current variants. The API
  currently passes `payload` through as an untyped dict. Strict Pydantic
  models for the payload internals will land once the upstream shape is
  locked.

### Frontend

- **Vanilla HTML + JS + CSS**, no bundler, no Node in the build. Served
  as static files by FastAPI in dev; production fronts via IIS / Caddy /
  nginx.
- **Chart.js** (local copy, not CDN) for visualizations. Plant
  environments may not have reliable egress.
- **Aesthetic: Microsoft Fluent / Power BI-inspired light theme.**
  Reference: `examples/dashboard-mockup/index.html`. Segoe UI, accent
  `#0078d4`, dense business-intelligence layout (not plant-floor).
- **Audience V1: management/enterprise.** Multi-site from day one;
  GET endpoints accept `site_id` query params. Engineer/operator views
  come later as separate pages if needed.
- **Migration to React deferred** until concrete interactivity pressure
  (per-user state, coordinated drill-down, component reuse) justifies
  the build-tool tax. Vanilla stays until that point, and the move
  (when it happens) is a rewrite, not a mix.

### Runtime shape

- **Single uvicorn worker.** 50 concurrent viewers at 1–5 min polling is
  rounding-error load; multi-worker buys complexity, not throughput.
- **Background-refresh snapshot pattern** — `SnapshotStore` Protocol +
  `InMemorySnapshotStore` are already in place as a seam. When a source
  is slow or expensive, a background task will refresh snapshots on an
  interval and route handlers hand out whatever snapshot is current.
  Not yet instantiated; routes compute per-request for now.
- **Redis / distributed cache** deferred until multi-worker becomes
  real. Swap is a new `SnapshotStore` implementation.

### Observability

- **Per-request correlation ID.** `X-Correlation-ID` middleware
  generates one if absent and echoes it in the response; structlog
  stamps it on every log line emitted during that request.
- **Structured JSON logs** from day one.

### Deployment

- **Windows-only.** SQL Server and Ignition integration are
  Windows-centric here; forcing Linux costs more than it saves.
- **ODBC Driver 17** baseline (matches existing Dolese SCADA apps).
  ODBC 18 is fine if used, but the connection string must set
  `TrustServerCertificate=yes` against self-signed certs (18 defaults
  encryption on).
- **Windows Integrated Auth** as the prod SQL auth path. Dev/test may
  use SQL auth (`sa`) where Integrated Auth is impractical. Integrated
  Auth inside containers requires gMSA or host-network identity; that
  work is deferred until SQL integration is imminent.
- Single exposed app port (default 8000).

### Security

- No auth for V1 POC. Dashboard must be network-restricted (VPN /
  firewall / plant LAN only). Authentication (Windows AD / OIDC /
  bearer) is a gating requirement for any deployment outside local dev
  and will be its own decision record.
- Secrets via env vars only; `.env.example` lists required variables.
- Read-only API — no mutation endpoints at the HTTP or DB layer.

### Explicit non-goals for V1

- Authentication / authorization
- HA / clustering / horizontal scaling
- Redis / multi-worker caching
- Retry / circuit-breaker machinery beyond per-call timeouts
- Multi-tenant data model (one company, multiple sites is not
  multi-tenant)
- Docker containerization (local dev first; container work when
  deployment shape firms up)
- React / bundlers / Node in the build chain

## Consequences

- Swapping sources (CSV → SQL, adding Ignition or external REST)
  remains a scoped change local to `integrations/<source>/`.
- The dashboard team can iterate entirely on the frontend without
  waiting for SQL integration.
- When we do move to React or add auth or add Redis, each is a clearly
  scoped project with a documented triggering condition in this ADR.
- Historical rows in the CSV/SQL that predate the current PAYLOAD shape
  will require a decision when SQL integration lands: filter them,
  normalize them, or surface them raw. Parked.

## References

- Project `CLAUDE.md` — conventions
- `context/sample-data/production-report/payload-schema.md` — current
  payload documentation
- `examples/dashboard-mockup/index.html` — frontend aesthetic reference
