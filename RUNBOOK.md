# Runbook

Quick reference for running and troubleshooting the
production-metrics-dashboard. Kept short on purpose — if you need the
"why," see `ARCHITECTURE.md`, `backend/ARCHITECTURE.md`, or
`backend/README.md`.

Two ways to run the backend on a Windows dev box:

1. **Local venv + uvicorn** — fast iteration, auto-reload, debugger in VSCode. Host port 8000.
2. **Docker Desktop + WSL2** — production-shaped, validates the image that ships. Host port 8001.

They can run side-by-side (different host ports, same `backend/.env`)
when you want to compare behavior.

## Prereqs

### Local venv path (one-time)

- Python 3.12 installed.
- Microsoft ODBC Driver 17 for SQL Server installed on the host (if
  you'll use the SQL backend).
- Create and activate the backend venv:

  ```powershell
  cd C:\Claude_Cowork\projects\production-metrics-dashboard\backend
  python -m venv venv
  .\venv\Scripts\Activate.ps1
  pip install -r requirements-dev.txt
  ```

### Docker path (one-time)

- Docker Desktop installed with WSL2 backend enabled (the default on
  modern Windows).
- `backend/.env` present and populated (the container reads it via
  compose's `env_file:` — the image itself never contains secrets).
  If you don't have one yet, copy `backend/.env.example` and fill in
  `DB_CONN_STRING`.

No ODBC driver install needed on the host for the Docker path — the
image installs it internally.

## Run the backend + dashboard (venv path)

From `backend/` with the venv active:

```powershell
# dev (auto-reload on code change)
uvicorn app.main:app --port 8000 --reload

# plain (no reload; use this if --reload misbehaves on Windows)
uvicorn app.main:app --port 8000

# default port 8000, with reload
uvicorn app.main:app --reload
```

Canonical dev port is **8000**. If port 8000 is stuck (zombie listener
from a previous run), see "Port 8000 is stuck" under Troubleshooting —
kill the zombie rather than route around it. 8001 remains available
as a fallback for this venv path; the Docker path owns 8001 by default
but compose-up will fail loudly if that port is in use.

## Run the backend + dashboard (Docker path)

From the repo root (PowerShell or a WSL2 shell):

```powershell
# build and start (first run or after code changes)
docker compose up --build

# start without rebuilding (subsequent runs)
docker compose up

# run detached so the terminal is free
docker compose up -d --build

# tail the container's structlog JSON output
docker compose logs -f api

# stop and remove the container
docker compose down
```

The image mirrors the repo layout internally at `/app/`, so
`core/config.py`'s `parents[3]` logic resolves the same way it does in
the venv. `context/` and `frontend/` are bind-mounted read-only so
edits to sample data and frontend files show up without a rebuild —
only Python code changes and `requirements.txt` changes warrant
`--build`.

### First-run smoke test

After `docker compose up --build` finishes its image build:

1. Wait for the log line `sql_pool.created` (≈ 10–20 s after startup).
2. Hit `http://127.0.0.1:8001/api/health` — should return 200 with
   `sql:production_report` reporting `ok: true`.
3. Hit `http://127.0.0.1:8001/` — dashboard should render live data.

If the pool fails to create (bad DSN, Azure firewall rule missing
your WSL2 NAT IP), you'll see `sql_pool.create_failed` in the logs.
The container stays up; `/api/health` reports the source as down; the
dashboard renders with tile-level error indicators rather than
blanking.

## URLs once the server is up

Replace `<port>` with **8000** for the venv path or **8001** for the
Docker path. Everything else is identical.

### Human pages
| What | URL |
|---|---|
| Dashboard | <http://127.0.0.1:8000/> |
| Swagger UI (interactive API docs) | <http://127.0.0.1:8000/docs> |
| ReDoc (read-only API docs) | <http://127.0.0.1:8000/redoc> |
| OpenAPI JSON schema | <http://127.0.0.1:8000/openapi.json> |

### API endpoints
| What | URL |
|---|---|
| Health check | <http://127.0.0.1:8000/api/health> |
| Sites list | <http://127.0.0.1:8000/api/sites> |
| Latest per workcenter (all sites) | <http://127.0.0.1:8000/api/production-report/latest> |
| Latest, filtered to site 101 | <http://127.0.0.1:8000/api/production-report/latest?site_id=101> |
| Range — one day for site 101 | <http://127.0.0.1:8000/api/production-report/range?site_id=101&from_date=2026-04-23&to_date=2026-04-23> |
| Range — April 2026 for site 101 | <http://127.0.0.1:8000/api/production-report/range?site_id=101&from_date=2026-04-01&to_date=2026-04-30> |
| Latest date for site 101 | <http://127.0.0.1:8000/api/production-report/latest-date?site_id=101> |
| Build fingerprint (debug) | <http://127.0.0.1:8000/api/__ping> |

Valid `/range` window width: 1-400 days (inclusive). Dates outside ISO-8601 format, `from_date > to_date`, or windows over 400 days return 422 from Pydantic / the handler.
values return HTTP 422 from FastAPI's query validation.

### New in Phase 5 — `conveyor_totals` envelope field

Both `/api/production-report/latest` and `/api/production-report/range`
responses include a `conveyor_totals` field. Sample shape:

```json
{
  "count": 2,
  "generated_at": "2026-04-23T15:30:00Z",
  "entries": [ ... ],
  "conveyor_totals": {
    "101:127": {
      "per_conveyor": { "C1": 8072.0, "C3": 2.2, "C4": 3543.3,
                        "C5": 2330.2, "C6": 0.0, "C7": 18.6, "C8": 0.0 },
      "product_mode":   { "C1": null, "C3": null, "C4": "#57",
                          "C5": "#57", "C6": null, "C7": null, "C8": null },
      "grand_total": 13966.3,
      "conveyors_counted": 7,
      "reports_counted": 1
    },
    "101:130": { ... }
  }
}
```

- Keys are `"<site_id>:<department_id>"` strings (JSON doesn't allow
  tuple keys).
- Only keys matching `/^C\d+$/` are summed. Crushers / screens / other
  equipment are deliberately excluded — see `PAYLOAD-CONTRACT.md` Rule 2
  footnote.
- Workcenters whose payloads contain no conveyor keys are omitted from
  the dict entirely.
- `grand_total` always equals `sum(per_conveyor.values())` (invariant
  asserted in every backend test).
- `product_mode` carries each conveyor's most *frequent*
  `Produced_Item_Description` across the window. Placeholder strings
  (`_`, `None`, empty) are excluded from the count, so a conveyor that
  ran `#57` a few times but was idle most of the week still reports
  `#57`. Ties are broken toward the newest report. Null when every
  observation is a placeholder / absent / non-string; the frontend
  renders null as em-dash via `placeholderize()`.
- The frontend uses this field to render the bar chart below each
  workcenter's table. Each bar's x-axis label is a two-line stack:
  conveyor name on top, mode product description below.

## Dashboard features (V1)

- **Site toggle** (topbar): switch between Big Canyon Quarry (site 101)
  and the Synthetic Demo (site 102). Switching fires an immediate fetch.
- **Theme toggle** (topbar): sun/moon icon next to the health pill.
  Light/dark persists via `localStorage`; first-time visitors default
  to `prefers-color-scheme`.
- **Time filter** (sidebar): Today / Week / Month. All three call
  `/api/production-report/range?from_date&to_date` with the window
  derived from the sidebar picker. Two modes:
  - Day → pick a calendar date via the native date input;
    `from=to=<picked>`. Workcenters with one report in the
    window render as KPI cards + per-asset table; multi-shift
    days where a workcenter has 2+ reports render as a history
    table. Default on first load is the newest date with data
    via `/api/production-report/latest-date`.
  - Month → pick a month + year from two dropdowns. Current
    month auto-caps at today (month-to-date); past months
    render the full month. Renders as a history table per
    workcenter.
  - Selection persists across refreshes via
    `localStorage['pmd-time-filter']`.
  - **Weather + notes + shift (Phase 8).** Each report row shows
    a weather icon + rounded temp in the Weather column, plus a
    Shift column. Click **View** in the Details column (or the
    Details button in the single-report panel header) to open a
    modal with the full weather grid (Avg Temp, Avg Humidity,
    Max Wind) and the free-form notes text. The icon is chosen
    by severity ranking from the STUFF'd condition list --
    'broken clouds, clear sky, light rain' shows the rain icon
    because rain is operationally relevant; the modal still
    shows the full list. ESC or backdrop click closes the modal.
  - Polling (30s) pauses when the selected window is fully in
    the past; re-arms when the selection pulls today back in.
  - Button click fetches immediately, doesn't wait for the next poll tick.
  - `/api/production-report/latest` still exists as a separate endpoint
    for any API consumer that wants "latest per workcenter regardless
    of date," but the dashboard no longer consumes it.
- **Auto-refresh**: every 30s by default.

### Polling cadence override

Override per tab with the `refresh` query param (milliseconds):

```
http://127.0.0.1:8000/?refresh=5000    # 5s — fast iteration
http://127.0.0.1:8000/?refresh=300000  # 5 min — prod-like cadence
```

## Tests

From `backend/` with the venv active:

```powershell
pytest                    # run all tests (expected: 30 passing)
pytest -v                 # verbose
pytest tests/api          # API tests only
pytest tests/integrations # source-layer unit tests (SQL + Flow)
pytest -k range           # single-pattern filter (only the /range cases)
```

Tests run in the venv path only today — they use the committed sample
TSV as a deterministic fixture, so there's no reason to shell into the
container to run them. If that changes (e.g., SQL-source tests against
a live DB), we'll add a `docker compose run --rm api pytest` recipe.

## Lint + format

From `backend/`:

```powershell
ruff check .              # lint
ruff format .             # apply format
ruff format --check .     # format dry-run (CI mode)
```

## Test fixture data

The committed file `context/sample-data/production-report/sample.csv`
is consumed by the test suite via `tests/_fixtures/csv_source.py` to
provide deterministic data without needing SQL Server. It is **not**
loaded by the production app (Phase 13 made SQL the only production
source). Edit it only when you want to adjust test behavior or
reproduce a SQL-side scenario in unit tests.

- File: `context/sample-data/production-report/sample.csv`.
- Open in a **plain text editor** (VS Code / Notepad++). Excel will
  mangle the tabs and JSON escapes.
- PAYLOAD column is a JSON string with `""` double-escaped quotes;
  keep that format when editing.
- Real vs synthetic rows: site 101 (IDs 40-101) real, site 102
  (IDs 201-262) synthetic. See the README alongside the file.

## Troubleshooting

### "Can't reach this page" or dashboard won't load

- URL must have a colon before the port: `http://127.0.0.1:8000/`
  (not `http://127.0.0.1/8000`).
- Check the uvicorn console / container log for
  `[main] build=... static_root=...` — that line should be present.
  If it says "NOT mounted," your `frontend/` folder isn't where the
  backend expects.

### Port 8000 is stuck ("Errno 10048")

Zombie uvicorn process from a previous run. Find and kill:

```powershell
# Find the PID on 8000
netstat -ano | findstr LISTENING | findstr ":8000"

# Kill it (replace 26016 with the PID from the above output)
taskkill /PID 26016 /F

# Confirm nothing is bound
netstat -ano | findstr LISTENING | findstr ":8000"
```

If that fails, the socket is a kernel-level zombie that usually clears
in a minute or two. Temporary workaround: `uvicorn app.main:app --port 8001`.

### `docker compose up` fails with "bind: address already in use"

Port 8001 on the host is taken. Find it the same way:

```powershell
netstat -ano | findstr LISTENING | findstr ":8001"
taskkill /PID <pid> /F
```

Or change the host-side mapping in `docker-compose.yml` (`"8001:8000"`
→ `"8002:8000"`, etc.) if 8001 is permanently claimed by something else.

### `sql_pool.create_failed` in the container log

Driver loaded but connection failed. Usually one of:

1. **DSN wrong** — `docker compose exec api python -c "import os; print(os.environ.get('DB_CONN_STRING'))"`
   and eyeball it. Braces around driver name must be single (not
   doubled `{{...}}` — python-dotenv doesn't collapse doubled braces).
   Server prefix must be `tcp:`.
2. **Azure firewall** — the Azure Managed SQL instance must allow the
   host's outbound IP. WSL2 NAT uses the host IP, so if the host works,
   the container works — unless something's proxying the WSL2 traffic
   separately.
3. **ODBC driver mismatch** — container has Driver 17; DSN must say
   `{ODBC Driver 17 for SQL Server}`, not 18.

### Server behavior doesn't match the code

You might be talking to a stale process. Fingerprint the running server:

```powershell
# venv path
curl.exe -s http://127.0.0.1:8000/api/__ping
# Docker path
curl.exe -s http://127.0.0.1:8001/api/__ping
# Expected: {"alive":true,"build_tag":"..."}
```

If the `build_tag` doesn't match what's in `app/main.py`'s `BUILD_TAG`
constant, your server is running old code — kill and restart (venv) or
`docker compose up --build` (Docker).

### `--reload` didn't pick up my change (venv path)

Happens occasionally on Windows, especially when files are edited
across the Cowork mount. Kill uvicorn (Ctrl-C, verify the prompt
returns), then restart without `--reload` to confirm the fresh code
is loaded.

### Code changes don't show in the container

The container has code baked in at build time — Python code changes
require `docker compose up --build`. `context/` and `frontend/` are
bind-mounted, so those changes show up immediately.

### Dashboard shows old behavior after code change

Browser cache. **Ctrl+Shift+R** to hard-refresh (bypasses the browser's
cached CSS/JS). Especially likely after `app.js` or `app.css` changes —
the server (venv or container) serves the new files cheerfully but
the browser keeps its copy.

## Exporting the current view

A single "Export" button in the topbar (left of the theme toggle)
writes the current mode's table data to `.xlsx`. Frontend-only --
uses the data already cached from the last poll, no API round trip.

- One flat sheet per export, named after the selection slug
  (`2026-04-23` for a day, `2026-04` for a month). One row per
  (workcenter, report, asset). Columns (Phase 8 added the last six):
  Site / Site ID / Dept ID / Prod. Date / Production ID / Asset /
  Availability % / Runtime (min) / Performance % / Total (tons) /
  Product Code / Product Description / Belt Scale % / Shift /
  Weather Conditions / Avg Temp / Avg Humidity / Max Wind / Notes.
  19 columns total. Weather + notes repeat across the assets of a
  given report (same shift = same weather), which Excel pivots
  collapse transparently.
- Null values export as truly-blank cells (not em-dash, not empty
  strings) -- Excel `AVERAGE` and `SUM` skip them, `COUNTA` returns
  0 on them.
- Percentage columns store raw numbers (e.g. 92.9) with an Excel
  number format `0.0"%"` so the display reads "92.9%" but the cell
  is numeric for aggregations.
- Filename: `production-metrics_<site-slug>_<selection-slug>_<YYYY-MM-DD_HHMM>.xlsx`.
  Examples: `production-metrics_big-canyon-quarry_2026-04-23_2026-04-24_0730.xlsx`
  (day pick) or `production-metrics_big-canyon-quarry_2026-04_2026-04-24_0730.xlsx`
  (month pick).
- Button is disabled until the first poll returns data for the
  current site + mode; when a window has no reports, it stays
  disabled.

The SheetJS build lives at `frontend/vendor/xlsx.full.min.js`
(Apache-2.0, 0.18.5); the license file is alongside it. No build
step, no CDN at runtime -- the library ships with the container
image / repo clone.

## Adding a new site to /api/metrics

When a new plant comes online and starts publishing interval metrics
to the enterprise MQTT broker via Flow, two things have to happen
before `/api/metrics/conveyor/*` will work for that site's tags:

1. **Ignition trigger writes rows to `[FLOW].[INTERVAL_METRIC_TAGS]`.**
   This is automatic if your Ignition deployment subscribes to the
   new site's MQTT topics and runs the upsert script in
   `scada/ignition/upsert_interval_metric_tag.py`. The first publish
   from each tag inserts a row -- no manual SQL needed. Verify by
   hitting `/api/metrics/conveyor/subjects?site_id=<new_site>` -- you
   should see the new tags in the response.

2. **Add the new Flow server's hostname to `docker-compose.yml`.**
   The container's DNS resolver doesn't see corporate DNS, so each
   Flow server needs an explicit static-host entry under
   `services.api.extra_hosts`. Procedure:

   1. From a Windows host that can resolve the new hostname, run
      `ping <new_flow_hostname>` (e.g. `ping dbp-otherquarry`). Note
      the IP it returns.
   2. Edit `docker-compose.yml` and add a line under `extra_hosts:`:

      ```yaml
      extra_hosts:
        - "dbp-bcq:10.44.135.12"             # site 101 (Big Canyon)
        - "dbp-otherquarry:10.44.x.x"        # site 102 (new site)
      ```

   3. Restart the container so the new entry lands in `/etc/hosts`:

      ```
      docker compose down
      docker compose up --build
      ```

   4. Smoke-test:

      ```
      curl "http://localhost:8001/api/metrics/conveyor/shiftly?site_id=<new_site>&from_date=YYYY-MM-DD&to_date=YYYY-MM-DD"
      ```

      A 200 with populated `entries` confirms the chain.
      A 504 with "Cannot reach Flow API: ConnectError" means the
      hostname resolved but port 4501 is unreachable -- check that
      the new Flow server is up and that the corporate firewall
      permits the WSL2 NAT IP to reach it.

The SQL table itself needs no changes -- it already stores the
full URL per row, including the site-specific hostname. Adding a
new site is purely an operational task at the Docker boundary.

If we ever migrate to corporate DNS resolution inside the container
(via `dns: [<corp_dns_ip>]` in the compose service), this whole
section goes away -- new sites Just Work as long as their Flow
server has a DNS A-record. Until then, the `extra_hosts` list is
the single source of truth.

## Where things live

| Want | Look here |
|---|---|
| Big-picture architecture | `ARCHITECTURE.md` |
| Backend FastAPI internals | `backend/ARCHITECTURE.md` |
| Project conventions | `CLAUDE.md` |
| Current plan / progress | `tasks/todo.md` |
| Prior session lessons | `tasks/lessons.md` |
| Architecture decisions | `tasks/decisions/` |
| Backend run instructions (detailed) | `backend/README.md` |
| Frontend structure | `frontend/README.md` |
| PAYLOAD JSON shape | `context/sample-data/production-report/payload-schema.md` |
| Dockerfile | `backend/Dockerfile` |
| Compose orchestration | `docker-compose.yml` |
