# Project: production-metrics-dashboard

## What This Is
This is a project for retrieving data from a SQL database and/or other external sources and APIs and
sending that data to a web page (html/React). This webpage is a production metrics dashboard for plant operators,
management and engineers.

Read-only API. Data sources are polled by the dashboard every 1–5 minutes —
not real-time. Target users span three audiences (engineers, operators,
management), which may drive multiple views once the frontend is decided.

## Tech Stack
- **Backend**: Python 3.12+, FastAPI, Pydantic v2, uvicorn
- **DB drivers**: aioodbc (async) + pyodbc (sync fallback) for SQL Server
- **HTTP client**: httpx.AsyncClient for external REST APIs (Flow, Timebase)
- **Frontend**: TBD — see Open Questions. Interim default: static HTML + vanilla JS polling `fetch()`
- **Testing**: pytest + pytest-asyncio + httpx test client
- **Container**: Docker on Linux for production — standalone microservices server, separate from the Windows hosts running SQL Server and Flow. Local dev: venv on Windows. See Deployment Notes.

> **Note on the stack.** The choices above are the user's recommendation based
> on prior SCADA work and comfort with the ecosystem. If during implementation
> Claude identifies a materially better tool, library, or pattern for a
> specific problem, raise it for discussion before substituting. Don't silently
> swap dependencies — but do challenge the defaults when there's a real reason.
> "Different from what I'd normally pick" is not a reason; "this library is
> unmaintained / has a known bug / is materially slower for our workload" is.

## Commands
- `./scripts/dev.sh` — start backend locally (uvicorn with reload)
- `cd backend && pytest` — run backend tests
- `cd backend && ruff check . && ruff format .` — lint + format
- `docker compose up --build` — run in container
- `docker compose logs -f api` — tail API logs

(Some of these are aspirational until the scripts/compose files exist. Check
`tasks/todo.md` for current setup status.)

## Architecture
Three data sources, tiered by level of curation, one unified API:

```
SQL Server (Flow_Curated)   — curated production reports        ─┐
Flow REST API               — curated interval metrics          ├─> FastAPI ─> Dashboard
Timebase API (planned)      — raw site-server time-series       ─┘   (polls every 1–5 min)
```

Each source is isolated behind its own integration module. Routes call
services; services call integrations; integrations handle the raw source.
**No direct SQL or HTTP calls from route handlers.**

### Folder roles
- `backend/app/api/routes/` — thin route handlers, grouped by domain
- `backend/app/services/` — request validation, caching, and packaging Flow's curated data across sources
- `backend/app/integrations/sql/` — shared SQL Server connection + pool
- `backend/app/integrations/production_report/` — Flow_Curated production-report Source + queries
- `backend/app/integrations/metrics/` — interval-metric Source (reads tag table, fans out to Flow REST)
- `backend/app/integrations/external/` — third-party REST clients (Flow, future Timebase)
- `backend/app/schemas/` — Pydantic models for request/response
- `backend/app/core/` — config, logging, shared utilities

## Code Conventions (project-specific)
Assumes global CLAUDE.md standards are already in effect. These add/override:

- **Async by default.** All I/O-bound code uses `async def`. aioodbc for SQL,
  httpx.AsyncClient for external APIs. Sync code is the exception and needs a reason.
- **Routes stay thin.** Handler validates input → calls one service function →
  returns a Pydantic model. No SQL, no HTTP, no business logic in routes.
- **SQL lives in files.** Non-trivial queries go in
  `backend/app/integrations/sql/queries/*.sql`, loaded at module import.
  Parameterized with `?` placeholders — never f-strings, `.format()`, or concatenation.
- **Response caching.** Polling is periodic (1–5 min), so cache expensive
  responses with a short TTL (30–60 sec) rather than hitting the source every
  request. Start in-memory; revisit if multi-worker becomes a requirement.
- **Graceful degradation.** External sources fail. Every integration call has
  a timeout. Failures surface as `HTTPException(503, detail={source, error})`
  so the frontend can show per-tile status rather than blanking the whole page.
- **Logging.** Structured JSON logs from day one. Every request gets a
  correlation ID. Never log raw webhook bodies or SQL parameters — they may
  contain sensitive values.

## Endpoint Design
Specific endpoints are not yet defined — they'll emerge as dashboard
requirements clarify. When adding them, follow these rules:

- **Naming**: `GET /api/<domain>/<resource>` (e.g. `/api/oee/current`, not
  `/api/getOee`). REST-ish, not strictly REST.
- **Grouping**: One file per domain under `backend/app/api/routes/`
  (e.g. `oee.py`, `equipment.py`, `alarms.py`). Mount each with a prefix.
- **Response shape**: Every response is a Pydantic model, never a bare dict
  or list. Even `/api/health` has a schema.
- **Granularity**: For a polling dashboard, prefer one well-shaped response
  over many chatty ones. A single `/api/equipment/status` returning an array
  beats five endpoints the frontend has to coordinate.
- **From day one**: `GET /api/health` returning per-source reachability so
  the dashboard can surface which sources are up.
- **Versioning**: Skip it until it's needed. If/when breaking changes loom,
  add `/api/v1/` prefix rather than retrofitting.

## Security & Secrets
- `.env` is gitignored. `.env.example` lists required vars with dummy values.
- SQL credentials, Flow API key, Timebase credentials (when wired), other external API keys → env vars only.
- Read-only API — no mutation endpoints. The SQL account used by the API
  should have read-only grants at the DB level as defense in depth.
- Auth is deferred (see Open Questions). Interim: deploy behind firewall / VPN,
  bind to internal interface only.

## Deployment Notes
- **Target: Linux** (Docker on a standalone microservices server, separate
  from the Windows hosts running SQL Server and Flow). The API has no
  privileged co-location with any data source — it talks to all of them
  over the network.
- Install the Microsoft ODBC Driver 18 for SQL Server (Linux build) inside
  the container image. Connection to SQL Server is over network ODBC.
- Connection to Flow / Timebase is over HTTP via httpx.AsyncClient.
- Reverse proxy: nginx in front of the container handles TLS; the API
  binds to localhost inside the container.
- Single exposed app port (default 8000 inside container).
- Linux Docker image is small (a few hundred MB) and rebuilds quickly.
- Local dev: venv + uvicorn on a Windows workstation. See `RUNBOOK.md`
  for the dev path; production is Linux only.

## Domain Context
SCADA / industrial automation. Before touching data semantics, read:
- `context/domain.md` — SCADA terminology, OEE definitions, plant vocabulary
- `context/sql-schema.md` — Flow_Curated table structure, joins, gotchas
- `context/external-apis.md` — third-party API shapes and auth patterns

Past implementations worth studying (reference only, do not modify):
- `examples/oee-html-calculator/` — prior standalone OEE calculator; good
  reference for calculation methodology (A × P × Q)

## Open Questions
Track resolutions in `tasks/decisions/`:
1. **Frontend technology.** Static HTML + vanilla JS, React (Vite), or start
   HTML and migrate? Driver: how much interactivity is needed and who maintains it.
2. **Authentication.** Deferred. Must be resolved before any deployment beyond
   local. Options: none (network-restricted), basic/bearer token, Windows AD, OIDC.
3. **Audience split.** Engineers, operators, and management have different needs.
   One dashboard with role-based views, or separate pages per audience?
4. **Timebase API integration.** Whether and when to wire it as a third
   source. Trade-off: granularity vs. additional surface area to maintain.
   Flow's aggregations cover shiftly/hourly today; Timebase would unlock
   sub-minute tag-level access when needed.
5. **Caching backend.** In-memory (simple, single-worker) vs. Redis (multi-worker
   ready). Decide when deployment shape firms up.
6. **v1 endpoint scope.** What does the dashboard actually need to show first?
   Defer until a concrete UI mock or requirements list exists.

## When In Doubt
- Domain / data meaning → `context/`
- "How do I run this?" → `docs/runbook.md`
- "Why did we do it this way?" → `tasks/decisions/`
- Past mistakes to avoid → `tasks/lessons.md` (read at session start)
- Pattern examples to emulate → `reference/`

## Where New Content Goes

When creating new files, place them by type — not by who created them:

- New backend code → `backend/app/` (follow the folder roles section above)
- New frontend code → `frontend/src/`
- Tests → alongside the code in `tests/` subfolders mirroring source structure
- Domain docs, glossary entries, data documentation → `context/`
- Human-facing docs (runbooks, architecture) → `docs/`
- Specs for upcoming work → `tasks/specs/`
- ADR-style decision records → `tasks/decisions/`
- Pattern snippets to emulate → `reference/`
- Throwaway exploration, prototypes → `tasks/scratch/` (gitignored)

Do NOT create new top-level folders without discussing first. If it's
unclear where something belongs, ask rather than inventing a location.