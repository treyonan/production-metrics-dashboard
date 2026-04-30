# Todo

## Phase 1 — FastAPI skeleton + CSV source (COMPLETE)

- [x] Backend bootstrap (venv + `app/` + `tests/`)
- [x] Dependency hygiene (`requirements.txt` + `requirements-dev.txt` + root `.gitignore`)
- [x] FastAPI skeleton (`main.py`, `core/config.py`, `core/logging.py`, `core/correlation.py`)
- [x] Source abstraction + CSV impl
- [x] Snapshot cache interface (seam only)
- [x] `/api/health` endpoint
- [x] `/api/production-report/latest` endpoint
- [x] Ruff check + format clean

## Phase 2 — Dashboard v1 (COMPLETE)

### Backend v1.1 — multi-site
- [x] `/api/sites` endpoint
- [x] `ProductionReportSource.list_site_ids()` on Protocol + CSV impl
- [x] `site_names` settings lookup (101 → Big Canyon Quarry, 102 → synthetic demo)
- [x] `?site_id=X` filter on `/latest`
- [x] Sites router + static frontend mount in `main.py`
- [x] Belt-and-suspenders: explicit `@app.get("/")` before the static mount
- [x] Debug `/api/__ping` + build-tag fingerprint + startup route dump

### Synthetic multi-site data
- [x] Site 102 synthesized from site 101 (scaled 0.7×); 62 rows appended
- [x] `context/sample-data/production-report/README.md` documents real vs synthetic

### Frontend scaffold
- [x] `frontend/index.html`, `app.css`, `app.js` (vanilla, no build step)
- [x] `frontend/vendor/chart.umd.js` local copy (offline-capable)
- [x] `frontend/README.md`

## Phase 2.1 — Dashboard UX (COMPLETE)

### Theme toggle
- [x] Light/dark palette via CSS variables
- [x] Toggle button in topbar with sun/moon SVG icons
- [x] Persists via `localStorage['pmd-theme']`; falls back to `prefers-color-scheme`
- [x] FOUC-prevention script in `<head>` applies theme before CSS loads

### Workcenter header metadata
- [x] Panel header shows `Prod. Date` and `Report ID` (mono-spaced) alongside the workcenter name and status pill

### Time-period filter (Today / Week / Month)
- [x] New backend endpoint `GET /api/production-report/history?site_id=X&days=N`
- [x] `get_history()` service function (rolling calendar-day window, inclusive of today UTC)
- [x] `ProductionReportHistoryResponse` schema
- [x] `days` validated at the query layer (1 ≤ N ≤ 365, 422 otherwise)
- [x] Three buttons in sidebar TIME FILTER panel (Today=/latest, Week=7d, Month=31d)
- [x] Button click fires an immediate fetch (not waiting for the 30s tick)
- [x] Today view: KPI cards + per-asset table (existing)
- [x] Week/Month view: KPI cards (latest in window) + per-workcenter history table with columns `Prod. Date | Report ID | Availability % | Performance % | Runtime (min) | Total (tons)`

### ADR + spec
- [x] `tasks/decisions/001-stack-and-source-boundary.md`
- [x] `tasks/specs/001-sql-integration-layer.md`

### Runtime verification
- [x] `pytest` on 3.12 Windows venv — **22 passing** (16 original + 6 new /history)
- [x] `uvicorn app.main:app` starts cleanly
- [x] Dashboard renders + polls; Today/Week/Month switch immediately
- [x] Theme toggle works light ↔ dark
- [x] `Report ID` visible in workcenter header

## Phase 3 — SQL integration (COMPLETE)

### Source abstraction + SQL implementation
- [x] `backend/app/integrations/sql/pool.py` — `create_pool(dsn, minsize=1, maxsize=4)` wrapping `aioodbc`
- [x] `backend/app/integrations/sql/queries.py` — `load_query(queries_dir, name)` helper
- [x] `SqlProductionReportSource` implements the `ProductionReportSource` Protocol
- [x] Query files: `ping.sql` (health probe) + `select_all.sql` (explicit column list)
- [x] Type-contract preservation: int→str cast on `SITE_ID` / `DEPARTMENT_ID`; `PAYLOAD` via `json.loads`; nullable `DTM`

### Config + DI
- [x] `PMD_PRODUCTION_REPORT_BACKEND` (csv|sql) — defaults to csv
- [x] `PMD_DB_CONN_STRING` / `DB_CONN_STRING` via `AliasChoices` as `SecretStr`
- [x] `get_production_report_source` dispatches on backend; raises 503 when SQL pool missing
- [x] Lifespan creates pool on startup (if backend=sql), closes on shutdown, degrades gracefully on failure

### Tests + docs
- [x] 8 new unit tests for `SqlProductionReportSource` with FakePool/FakeConnection/FakeCursor
- [x] `tasks/specs/001-sql-integration-layer.md` — D1–D10 decisions recorded
- [x] `ARCHITECTURE.md` + `RUNBOOK.md` reflect the two-backend model
- [x] `backend/.env.example` — placeholder template (post-incident; real creds live in `.env`, gitignored)
- [x] `requirements.txt` — `aioodbc~=0.5.0`, `pyodbc~=5.2.0`

### Runtime verification (live Azure Managed SQL)
- [x] `sql_pool.created` logged on startup with `PMD_PRODUCTION_REPORT_BACKEND=sql`
- [x] `/api/health` — `sql:production_report` reports `ok: true` ("SELECT 1 returned 1")
- [x] `/api/production-report/latest?site_id=101` — returns real Big Canyon Quarry rows
      (dept 127, prod_date 2026-04-22, C1 Availability 92.9% / C4 Performance 128.1%)
- [x] Dashboard renders live SQL data

## Phase 4 — Docker on Windows (COMPLETE)

**Goal:** containerized deployment of the FastAPI service on a Windows
dev box using Docker Desktop + WSL2 (Linux containers). The existing
`uvicorn app.main:app` dev loop from VSCode must keep working unchanged
— the container path is purely additive.

### Approach

- **Base image:** `python:3.12-slim-bookworm`. Small, well-supported,
  Microsoft ships ODBC Driver 17 packages for it.
- **ODBC driver:** install `msodbcsql17` + `unixodbc` via Microsoft's apt
  repo. Matches the host driver version so the same DSN string in
  `backend/.env` works in both paths without modification.
- **Build context:** repo root (not `backend/`). The container needs
  `backend/` (app code), `context/` (sample CSV fallback), and `frontend/`
  (static files) — keeping the same layout inside the container at
  `/app/` preserves the `parents[3]` path logic in `core/config.py`.
- **Single-stage Dockerfile** for v1. Multi-stage is a later tightening;
  start debuggable.
- **`.env` NEVER baked into the image.** compose uses `env_file:
  backend/.env` so secrets stay on disk; same file the venv path reads.
- **No code changes to the app.** Settings paths, DI, lifespan all
  work as-is once the repo layout is mirrored inside the container.
- **Ports:** host 8001 → container 8000. Venv path uses host 8000 so
  the two can coexist for side-by-side debugging.

### Files to create — DONE

- [x] `backend/Dockerfile` — python:3.12-slim-bookworm + ODBC Driver 17 + app
- [x] `.dockerignore` (repo root) — excludes `venv/`, `__pycache__/`,
      `.pytest_cache/`, `.ruff_cache/`, `backend/.env`, `.git/`, build artifacts
- [x] `docker-compose.yml` (repo root) — single `api` service, host 8001→container 8000,
      `env_file: backend/.env`, Python-stdlib healthcheck, dev bind-mounts for context/ and frontend/
- [x] `.gitattributes` — force LF on `Dockerfile`, `*.sh`, `*.sql`, `*.py` (autocrlf defense)

### Files to update — DONE

- [x] `RUNBOOK.md` — rewritten with dual-path (venv 8000 / Docker 8001) instructions, Docker troubleshooting, test count bumped to 30
- [x] `backend/ARCHITECTURE.md` — new §13 "Deployment paths" covering both paths
- [x] `tasks/todo.md` — checked items off as we went

### Verification matrix — passed on the Windows host (2026-04-23)

- [x] `docker compose up --build` completes without errors
- [x] Container log shows `sql_pool.created` (real Azure SQL reachable
      from the WSL2 NAT)
- [x] `http://localhost:8001/api/health` returns 200 with
      `sql:production_report` `ok: true` from the Windows host browser
- [x] `http://localhost:8001/api/production-report/latest?site_id=101`
      returns real Big Canyon Quarry rows
- [x] Dashboard loads at `http://localhost:8001/`
- [x] `docker compose down` stops cleanly, no orphan containers
- [x] **Regression check:** `uvicorn app.main:app --port 8000 --reload`
      from the VSCode terminal still works against the same `.env`;
      30/30 tests still pass in the venv

### Explicit non-goals for Phase 4

- Multi-stage build (image-size tightening — later)
- Non-root container user (hardening — later)
- TLS termination (reverse-proxy's job)
- docker-compose override files for dev vs prod (single compose file for now)
- Windows-container variant (WSL2/Linux is the chosen path)
- Pushing the image to a registry (local build only)

### Open questions

- **ODBC driver version drift:** host is on Driver 17, container image
  installs 17. If plant IT standardizes on Driver 18 later, both move
  together — trivial swap but worth flagging.
- **SQL Server firewall:** the Azure Managed SQL instance must allow
  outbound from the WSL2 NAT IP. Host works today; the container
  traffic egresses from the same host IP, so it should Just Work™ —
  verify during the smoke test rather than assume.

## Phase 5 — Conveyor totals bar chart (COMPLETE)

**Goal:** below each workcenter's existing asset table, render a bar
chart summarising belt-scaled conveyor tonnage for the active
interval. One bar per conveyor (strict `/^C\d+$/`), bar height = sum
of `CX.Total` across every production report in the window. Grand
total rendered as a text label ("Conveyor Total — X tons") above the
chart, NOT as its own bar.

### Scope / semantics

- **Bar set:** only keys matching `/^C\d+$/`. Non-conveyor assets
  (crushers, screens, future equipment) excluded because they have no
  belt scale and therefore no meaningful `Total`. This diverges from
  the shape-based asset discovery used for table rows, per Trey's
  direction 2026-04-23.
- **Today (1 report):** bar height = that single `CX.Total`.
  `Workcenter.Total` may be null while conveyor sums are real, so the
  chart's grand total is distinct from the KPI card.
- **Week (up to 7 reports):** bar height = sum of that conveyor's
  `Total` across every report in the window. Matches Trey's sample
  matrix exactly (column totals in that table = conveyor bar heights).
- **Month (up to 31 reports):** same logic, larger window.
- **Null/missing handling:** treat null / missing `Total` as 0.
- **Empty-state:** no chart rendered when no reports in window OR
  every conveyor's sum is 0 (the existing "no data in window"
  placeholder covers the former; a chart-local "no belt-scale data"
  message covers the latter).
- **Bar order:** numeric by conveyor number (C1, C3, C4, ...),
  matching the table above for visual consistency.

### Backend work

- [x] New service function `compute_conveyor_totals` in
      `backend/app/services/production_report.py`, returning
      `dict[tuple[str, str], ConveyorAggregate]`. NaN / inf / garbage
      Totals coerced to 0 via `math.isfinite` guard.
- [x] New Pydantic model `ConveyorTotals` in
      `backend/app/schemas/production_report.py`:
      `per_conveyor`, `grand_total`, `conveyors_counted`, `reports_counted`.
- [x] Extended both envelope models with `conveyor_totals: dict[str, ConveyorTotals]`,
      keyed by `"<site_id>:<department_id>"`, default empty.
- [x] Route handlers compute + attach via `_totals_map` helper; no new endpoints.
- [x] 17 unit tests in `backend/tests/services/test_conveyor_totals.py`:
      Trey's sample matrix (reference case), null / missing / garbage /
      NaN / inf / numeric-string Totals, strict-CX exclusion of
      Workcenter/Site/Circuit/Crusher/Screen, multi-workcenter keying,
      numeric vs lexical sort (C1/C3/C7/C10), empty + malformed payloads,
      parametrised bad CX values. Cross-sum invariant asserted throughout.
      Validated in sandbox with an in-process harness (21/21 on the
      hand-run); pytest on Trey's host still to confirm.

### Frontend work

- [x] `renderConveyorChart(hostEl, totals)` helper added; both Today
      and History panels append a `.wc-chart` host to their `wc-body`
      and invoke it. Module-scope `_currentConveyorTotals` stashes the
      envelope field per poll; panel renderers don't need signature changes.
- [x] Chart.js config — single-series bar, theme-aware colors via
      `_themeColors()` pulling `--accent`/`--border`/`--text`;
      `maxBarThickness: 48`, animation disabled, y-tick integer formatting,
      tooltip `"{value} tons"`. Subtitle rendered in HTML above the canvas
      (not via Chart.js's own title plugin) so it can reuse `.chart-subtitle`
      styling alongside other dashboard text.
- [x] Instance lifecycle via module-scope `_chartInstances` Set;
      `destroyAllCharts()` runs at the top of `renderData` before the
      `innerHTML = ""` wipe.
- [x] Empty-state caption: "No belt-scale data in window" when totals
      missing, no conveyors, or `grand_total <= 0`.

### Docs

- [x] `PAYLOAD-CONTRACT.md` — footnote under Rule 2 covering the
      strict-CX exception for the tonnage chart (belt scales only).
- [x] `backend/ARCHITECTURE.md` §6.4 — shared-envelope paragraph
      describing `conveyor_totals` for both endpoints.
- [x] `RUNBOOK.md` — new "`conveyor_totals` envelope field" subsection
      with a worked sample and semantics callouts.
- [x] `tasks/todo.md` — checked off (this line).

### Verification matrix — passed on the Windows host (2026-04-23)

- [x] `pytest` — **50 passing** on Python 3.12 Windows venv (30 prior +
      20 new, including parametrised cases from
      `test_cx_value_not_a_dict_is_skipped`).
- [x] Today view: conveyor bars render below Big Canyon Quarry
      workcenter panels; grand-total label above the chart.
- [x] Week view: bar heights increase vs Today (up to 7× the data).
- [x] Month view: largest bars / grand total.
- [ ] Empty-state: hack the sample CSV to remove all `CX` entries
      from a row → panel for that dept shows the no-belt-scale
      caption, not a broken chart. (Not yet verified by hand; logic
      is covered by `test_workcenter_with_no_cx_is_omitted`.)
- [x] No visible console errors or chart-rendering glitches
      through normal interaction.
- [x] **Theme-toggle instant update (2026-04-23 patch):** switching
      light ↔ dark updates chart text color, grid lines, and bar
      accent immediately rather than at the next 30s poll tick.
      Implementation: `_lastPayload` cache + `renderData` rerun on
      toggle; no API round-trip.

### Explicit non-goals

- Non-conveyor equipment charts (out-of-scope per scope decision).
- Per-shift / intra-day grouping (Week/Month is cumulative across
  the window, not broken out by report).
- Drill-down interactions (click-to-filter, etc.).
- Chart export (PNG / CSV) — deferred.
- Secondary-axis / multi-series (the chart is single-series bar by
  design).
- PAYLOAD-CONTRACT itself — contract stays DRAFT pending Trey's team
  review; this feature is consistent with the current draft.

### Open questions — resolve before coding

- None blocking. Chart placement (directly below the asset table),
  color (single theme accent), subtitle wording ("Conveyor Total —
  X tons"), and empty-state behavior all decided in conversation
  2026-04-23.

## Phase 5.1 — Strict time-filter semantics (COMPLETE 2026-04-23)

**Trigger:** Trey noticed that workcenter 130 disappeared under Week
view (its latest report was 2026-04-16, one day outside the 7-day
window ending 2026-04-23) but showed up under Today and Month. Today
was using `/latest` which returns "latest per workcenter regardless
of date" -- semantically inaccurate for a tile labelled "Today."

**Decision:** strict calendar-day semantics across all three modes.
No fallback, no merging with latest-per-workcenter. Empty views are
accurate information, not a bug to paper over.

### Changes
- [x] `frontend/app.js` — `MODES.today` now carries `days: 1` (was
      `null`). `dataUrlForMode()` drops the `/latest` branch; all modes
      use `/history?days=N`. Today-mode rendering reduces entries to
      latest-per-(site_id, department_id) since `/history?days=1` can
      return multiple entries per workcenter on multi-report days.
- [x] `RUNBOOK.md` — time filter table updated.
- [x] Backend untouched. `/latest` endpoint preserved for future
      consumers that want "latest regardless of date."
- [x] No docker rebuild required (frontend is bind-mounted).

### Known behavior (intended)
- Today may be empty when nothing has reported yet today. This is the
  signal users need, not a failure mode.
- A workcenter silent for more than 7 days falls out of Week entirely.
  Same logic for Month (>31 days).
- Pre-existing timezone subtlety: `today` is computed from UTC, not
  plant-local time. Production-report timestamps are naive datetimes;
  if prod_date is authored in plant-local and "today" straddles
  midnight UTC, a late-evening report may appear a day later in the
  dashboard. Not fixed here; flagged for later when multi-timezone
  data lands.

## Phase 5.2 — Drop KPI grid from Week/Month panel (COMPLETE 2026-04-23)

**Trigger:** Trey asked whether the Availability / Performance / Runtime
KPI cards in Week/Month view represented period averages. They didn't
— they were the *latest* report's snapshot, labeled under a Week/Month
tile. The mismatch between label and data invited misreading.

**Decision:** remove the KPI grid in Week/Month view entirely. Today
view keeps its KPI grid (those cards ARE the primary artifact for a
single-report view). Week/Month panels now render
`[panel-header] + [history-table] + [conveyor-chart]` — no redundant
snapshot tier. The table's top row (pre-sorted newest-first) plus the
status pill in the panel header cover "current state at a glance";
the chart covers period tonnage; the table covers everything in
between.

### Changes
- [x] `frontend/app.js` — `renderHistoryPanel` body drops the
      `kpiGridFromWorkcenter(latestWc)` line; comment explains why.
      `latestWc` still held for the header's status pill.
- [x] No backend change, no docker rebuild (frontend is bind-mounted).

### Deferred
- **Table `Total` column semantics** (Trey's prior question). Currently
  shows `Workcenter.Total` from the upstream payload — frequently null,
  doesn't reconcile with the bar-chart grand total. Candidate fix:
  sum-of-conveyors per row. Trey said he'd decide separately; not
  bundled with this change.
- **Period-aggregate KPI view.** If we ever want a true period rollup
  at the top of Week/Month (`avg(Availability)`, `sum(Runtime)`, etc.),
  that's a separate add — NOT a revival of the latest-snapshot grid
  we just removed.

## Phase 5.3 — Conveyor chart: per-conveyor product label (COMPLETE 2026-04-23)

**Trigger:** Trey wanted each conveyor bar to also show what product
is associated with that belt over the period.

**Shape:** two-line x-axis label per bar. Top line is the conveyor
name (C1, C3, ...), bottom line is the per-conveyor
``Produced_Item_Description`` mode across the window.

**Semantic choice:** MODE, not latest.
- Mode = most frequent value for that conveyor across the reports in
  the window.
- Placeholder values (``_``, ``None``, empty) are excluded from the
  count -- a conveyor that ran ``#57`` a few times but was idle the
  rest of the week still reports ``#57``. Operators care about what
  product was on the belt, not how often it was idle.
- Ties are broken toward the newest report (Counter's stable-order
  tie-break on newest-first-inserted values).
- Null when every observation is placeholder / absent / non-string;
  frontend renders null as em-dash.

### Changes
- [x] `backend/app/services/production_report.py` -- `ConveyorAggregate`
      gains a `product_mode: dict[str, str | None]` field; compute
      collects non-placeholder observations per (workcenter, conveyor)
      and resolves to the most-frequent value via `Counter.most_common`.
      Newest-first input order ensures ties break toward the newest.
- [x] `backend/app/schemas/production_report.py` -- `ConveyorTotals`
      gains a `product_mode` field; documented.
- [x] `backend/app/api/routes/production_report.py` -- `_totals_map`
      passes the new field through.
- [x] `backend/tests/services/test_conveyor_totals.py` -- six new
      tests: mode picks the most-frequent value, ties break newest,
      placeholders excluded from count, all-placeholders -> None,
      missing / non-string -> None, key order aligns with
      `per_conveyor`. Existing tests unaffected (no dataclass-equality
      comparisons).
- [x] `frontend/app.js` -- chart labels become `[[conv, desc], ...]`;
      Chart.js renders each as a two-line tick. Reads `totals.product_mode`
      and uses `placeholderize()` to render null as em-dash (backend has
      already filtered placeholders out of the mode calculation).
- [x] `RUNBOOK.md` -- sample JSON snippet shows the new field; two new
      bullets describe semantics and rendering.
- [x] `backend/ARCHITECTURE.md` §6.4 -- one-sentence note about the
      new field and its frontend use.

**Verified on host 2026-04-23:** `pytest` reports 56 passing (54 prior
+ 6 new Phase 5.3 mode tests - 4 Phase 5.3 pre-revision tests = 56).
Dashboard displays correct mode product under each conveyor bar.

**Docker rebuild required** (backend changed).

**Visual fallback if it looks cramped:** option (C) from the Phase 5.3
discussion is the backup -- product text floating above each bar, via
the chartjs-datalabels plugin. Small additional dependency; keeps the
x-axis single-line. Revisit only if (A) looks bad with real data.

## Phase 6 — XLSX export of current-mode table data (IMPLEMENTED 2026-04-23, browser QA pending)

**Trigger:** Trey asked for an "Export XLSX" button on the dashboard
that dumps the current-mode table data to a .xlsx the user can open in
Excel.

### Decisions (from the clarifying round, 2026-04-23)
- **Scope:** one button, top-of-page, current mode. A single click
  exports every workcenter's table data for whichever mode
  (Today / Week / Month) is currently selected into one flat sheet.
  Not per-panel; not per-workcenter.
- **Format:** XLSX only. CSV explicitly deferred.
- **Implementation:** frontend-only. Uses `_lastPayload` (already
  cached for the theme-toggle path) rather than a new backend endpoint.

### What the exported file contains

**Today mode** -- one flat sheet `Today` with one row per
workcenter x asset (mirrors the per-asset table rendered today):

| Site | Site ID | Department ID | Asset | Availability % | Runtime (min) | Performance % | Total (tons) | Product Code | Product Description | Belt Scale % |

**Week / Month mode** -- one flat sheet `Week` or `Month` with one row
per report x workcenter (mirrors the history table rendered today):

| Site | Site ID | Department ID | Prod. Date | Report ID | Availability % | Performance % | Runtime (min) | Total (tons) |

Data-shape rules:
- Columns mirror what's currently rendered in the corresponding
  table, plus `Site`/`Site ID` for traceability (the button exports
  the whole payload for the selected site, and users may save multiple
  files across sites).
- Null values -> **empty cells**, not em-dash. Em-dash is a
  frontend-rendering convention; exports shouldn't carry it (it breaks
  Excel aggregations).
- Percentages stored as **numbers** (e.g. 92.9) with a `0.0"%"` cell
  number format applied to the percentage columns. Preserves Excel
  math; display still reads "92.9%".
- Runtime stored as a number with `0.0` format. Tons as an integer
  with `#,##0` format.
- Dates stored as ISO strings in v1 (portable). Upgrade to Excel date
  serials later if Trey wants Excel date math.
- Conveyor-totals chart data is **NOT** included in v1. Scope is
  "table data," per the ask.

### Filename

`production-metrics_<site-slug>_<mode>_<YYYY-MM-DD_HHMM>.xlsx`

Example: `production-metrics_big-canyon-quarry_week_2026-04-23_1427.xlsx`.

Slug: lowercased site name, spaces -> `-`, non-alnum stripped. Falls
back to `site-<id>` if the site name is missing.

### Files to create

- `frontend/vendor/xlsx.full.min.js` -- SheetJS community edition
  (Apache-2.0), mirrors the `chart.umd.js` vendoring pattern.
  **Requires Trey's explicit OK to `WebFetch` from `cdn.sheetjs.com`**
  before I pull it -- global CLAUDE.md restricts external fetches to
  specifically-named domains.

### Files to modify

- `frontend/index.html`
  - Add `<script src="vendor/xlsx.full.min.js"></script>` above `app.js`.
  - Add `<button id="export-btn" class="export-btn" disabled>...</button>`
    in the topbar, between `#theme-toggle` and `#health-pill`.
- `frontend/app.css`
  - Styling for `.export-btn` to match `.theme-toggle` (same size,
    hover/focus affordance, disabled state muted).
- `frontend/app.js`
  - Add `exportCurrentMode()` that reads `_lastPayload`, `currentMode`,
    `currentSiteId`, `sites`, shapes rows per mode, builds an XLSX
    workbook via SheetJS, and triggers the download via
    `XLSX.writeFile(wb, filename)`.
  - Add helpers `shapeTodayRows(payload)` and `shapeHistoryRows(payload)`
    that turn the entries array into an array-of-objects suitable for
    `XLSX.utils.json_to_sheet`. Isolated so they're testable by hand
    in the console.
  - Add `applyColumnFormats(ws, spec)` that sets `ws['!cols']` widths
    and cell `z` format codes for percentage / integer columns.
  - Disable the button when `_lastPayload` is null or
    `_lastPayload.entries.length === 0`. Toggle enabled/disabled at
    the end of `renderData()` and in the `empty-state` branch.
  - Wire the button click in `bootstrap()`.

### Files untouched

- Backend code. Zero route, schema, service, or integration changes.
- Docker image. Frontend is bind-mounted; the new
  `vendor/xlsx.full.min.js` lands without a rebuild.
- Tests. Frontend is vanilla JS with no test harness today; manual
  verification only.

### Verification matrix (manual)

- **Today view, site 101** -- button enabled after first poll. Click ->
  file downloads as `production-metrics_big-canyon-quarry_today_<ts>.xlsx`.
  Opens in Excel with one sheet named "Today", rows for every
  C1/C3/C4 across every workcenter in the payload.
- **Week view** -- same button click -> file named `..._week_...`, "Week"
  sheet with multiple rows per workcenter (one per report).
- **Month view** -- same, 31-day window.
- **Null Performance on C3** -- exports as an empty cell, not em-dash,
  and doesn't break the column's percentage number format.
- **Percentage column sanity** -- `=AVERAGE(E2:E20)` in Excel returns
  the expected numeric mean (not `#VALUE!`). Column displays "92.9%"
  not "92.9".
- **Site switch** -- change site in the sidebar, wait for one poll,
  export again -- filename reflects the new site slug, rows are the
  new site's data only.
- **Empty-state** -- force an empty payload (site with no reports in
  window); button becomes disabled. Flipping back to a populated mode
  re-enables it.
- **Theme toggle** -- still works after export. Polling still ticks.
  No regression in dashboard render.
- **Network tab** -- button click triggers **no** API request
  (frontend-only confirmation).
- **Dev-loop regression** -- uvicorn on 8000 and Docker on 8001 both
  serve the new button and export correctly.

### Explicit non-goals for v1

- CSV export (deferred; XLSX-only per decision).
- Per-panel export buttons (scope: top-of-page, one button).
- Backend export endpoint (frontend-only per decision).
- Conveyor-totals chart data in the workbook.
- Multi-sheet workbooks (one flat sheet per mode is the v1 shape).
- Excel date serials (ISO strings for v1).
- Streaming / chunked download.
- Server-side auditing or access control on exports.

### Open design questions

- **OQ1 -- Date serials.** Should prod_date be an Excel date cell
  (supports date math / filters) rather than an ISO string? Trivial
  upgrade; flagged to confirm before I build.
- **OQ2 -- Conveyor totals as a second sheet.** Deliberately out of
  v1, but low-cost to add later. Revisit after v1 ships.
- **OQ3 -- Empty-state behavior.** Disable the button (current plan)
  vs. export a sheet with headers and no rows? Current plan avoids
  "why did I download an empty file" confusion.
- **OQ4 -- Shape choice.** One flat sheet with Site/Dept columns
  (pivot-friendly, current plan) vs. one sheet per workcenter
  (matches the dashboard visually). Flat wins on Excel usability;
  confirm before I build.

### Sequence to implement (after approval)

1. Download SheetJS community edition; stage under
   `frontend/vendor/xlsx.full.min.js`. **Requires explicit go to
   `WebFetch` from `cdn.sheetjs.com`.**
2. Rewrite `frontend/index.html` via `bash`-heredoc to add the script
   tag + button markup. Tail-verify.
3. Rewrite `frontend/app.css` via heredoc (or a single Edit +
   tail-verify) to add `.export-btn` styling.
4. Rewrite `frontend/app.js` via heredoc -- the lesson about Edit-tool
   truncation on this mount applies with extra force here since
   `app.js` is the main frontend file.
5. Manual verification on the uvicorn dev loop first, then on the
   Docker path as a regression check.
6. Check Phase 6 items off in `tasks/todo.md` and add a one-line note
   to `RUNBOOK.md` describing the new button.

### Implementation progress (2026-04-23)

Code landed in the three frontend files + a new vendored SheetJS.
Programmatic verification of the shaping logic is green; on-device
(browser) verification is still pending Trey's run.

Done:
- [x] `frontend/vendor/xlsx.full.min.js` (SheetJS 0.18.5, Apache-2.0,
      ~882 KB, md5 `31e9848e80e1ddf43c5aa31009cd2b7b`). Pulled from
      `registry.npmjs.org/xlsx` via `npm pack xlsx@0.18.5` and
      unpacked; `cdn.sheetjs.com` is not on the sandbox egress
      allowlist, so the tarball path is the one we can reproduce
      in future automations. License file at
      `frontend/vendor/xlsx.LICENSE.txt`.
- [x] `frontend/index.html` — `<script src="vendor/xlsx.full.min.js">`
      added above `app.js`; `<button id="export-btn" class="export-btn"
      disabled>` added in the topbar between `#theme-toggle` and
      `#health-pill` with a download-arrow SVG + "Export" label.
- [x] `frontend/app.css` — `.export-btn` styling matches
      `.theme-toggle` surface with hover/active/disabled variants.
- [x] `frontend/app.js` — new `// --- XLSX export (Phase 6) ---`
      section with `slugifySite`, `timestampSlug`, `numOrEmpty`,
      `strOrEmpty`, `shapeTodayRows`, `shapeHistoryRows`,
      `applyColumnFormats`, `exportCurrentMode`,
      `updateExportButtonState`. `refreshData` calls
      `updateExportButtonState()` right after caching `_lastPayload`;
      `bootstrap()` wires the button click.
- [x] Node `--check` passes on `app.js`.
- [x] Programmatic verification: Node harness builds synthesized
      `/history` envelopes covering null Performance, placeholder
      `_`/`None` Product Code/Description, null Total, null Runtime
      (Actual_Runtime_Hours fallback), multi-workcenter grouping,
      numeric vs lexical asset sort. Harness constructs workbooks
      via `XLSX.utils.json_to_sheet` + `applyColumnFormats`, writes
      buffer via `XLSX.write`, reads it back with `cellNF: true`,
      and asserts cell types (`t`), values (`v`), and format codes
      (`z`) at specific addresses. All 30 assertions green on both
      Today and Week shapes. Sample file sizes ~18 KB each.
- [x] **Null-handling refinement caught during verification.** First
      pass used `""` for blanks; read-back showed those land as
      explicit empty-string cells, which `COUNTA` counts. Changed to
      `null` so `XLSX.utils.json_to_sheet` truly omits the cell --
      matters when a plant engineer uses `=COUNTA(J:J)` to check
      "how many conveyors reported a product code?" The behavior
      distinction is documented inline in the `numOrEmpty` /
      `strOrEmpty` comments.

Pending:
- [ ] Manual browser verification on the Windows host per the
      "Verification matrix (manual)" checklist above. Specifically:
      - [ ] Click Export in Today mode; open .xlsx; confirm headers,
            rows match the on-screen table, percentage columns
            display "92.9%" with underlying numeric values.
      - [ ] Switch to Week mode; click Export; file named `..._week_...`.
      - [ ] Switch to Month mode; click Export; file named `..._month_...`.
      - [ ] `=AVERAGE()` on the Availability % column in Excel returns
            a numeric mean (not `#VALUE!`).
      - [ ] Null Performance on C3 renders as empty cell (not em-dash,
            not empty-string, not `#NUM!`).
      - [ ] `=COUNTA()` on the Product Code column returns only the
            populated rows (placeholder `_` rows don't count).
      - [ ] Site switch mid-session changes the filename slug.
      - [ ] Empty-state (no reports in window) disables the button.
      - [ ] Theme toggle still works post-export; polling still ticks.
      - [ ] Network tab confirms button click triggers **no** API call.
      - [ ] Regression: uvicorn on 8000 and Docker on 8001 both serve
            the new button (frontend is bind-mounted; no rebuild).
- [ ] `RUNBOOK.md` one-liner mentioning the new button (adding now).

Deliberate departures from the plan:
- The shaping helpers return `null` for "no data," not `""`.
  This was a refinement caught during programmatic verification and
  is materially better for Excel behavior. Plan text above says
  "empty cells"; `null` achieves that; `""` would not have.

## Phase 7 — Day-picker + month-picker time filter (IMPLEMENTED 2026-04-24, browser QA pending)

**Trigger:** Trey asked to replace the rolling Today/Week/Month time
filter with absolute-date controls. The three-button group never
matched how operators actually ask about production data -- "Today"
is typically empty until end-of-shift, "Week" is a weird unit for a
monthly rhythm, and the useful questions are "yesterday / last
Thursday / this month so far / all of March."

### Decisions (from the clarifying round, 2026-04-24)

- **D1 -- Default on page load:** most recent day with data. A small
  bootstrap endpoint `/api/production-report/latest-date?site_id=X`
  returns the newest `prod_date` for that site; frontend pre-selects
  it in the day picker. Sidesteps the empty-state problem that made
  "Today" frustrating.
- **D2 -- Month picker shape:** month dropdown + year dropdown,
  side-by-side. Year defaults to current, populated with the last
  ~5 years. Handles "look at December from January" and preserves
  access to older windows without cluttering the UI.
- **D3 -- Multi-shift day rendering:** all shifts as a history table
  (one row per report). Single-shift days keep the current Today
  layout (KPI cards + asset table) since that's the per-report view
  and remains the cleanest artifact for a single-report window.
  Multi-shift days switch to the history-table layout that month
  view already uses -- consistent with "2+ reports in this window."
- **D4 -- Backend shape:** new `/api/production-report/range`
  endpoint; **remove** `/api/production-report/history`. Rolling-N
  semantics are not what the new frontend asks, `/history` has no
  other consumers, and git covers the revert case (see "Why remove"
  below). One endpoint per semantic question.
- **D5 -- Persistence:** `localStorage['pmd-time-filter']` holds
  `{mode: 'day' | 'month', dayDate?: 'YYYY-MM-DD', monthYear?: number,
  monthMonth?: 1-12}`. On load, restore selection if present; fall
  back to D1 (latest-date bootstrap).
- **D6 -- Timezone:** `prod_date` treated as UTC (unchanged from
  Phase 5.1). Filter bounds are inclusive calendar dates. Documented
  explicitly on the `/range` endpoint. Revisit when multi-timezone
  sites land.
- **D7 -- Polling:** 30s poll continues when the selected window
  includes today (day = today, OR month = current month). Pause the
  timer otherwise; re-arm when the selection changes to include
  today. Fixed-past windows don't need polling -- the data is
  settled.

### Why remove `/history` rather than keeping it

Dead-code-as-safety-net is what git is for. Keeping `/history?days=N`
in the source after the frontend stops using it costs:
- Regression testing on every ODBC driver / aioodbc / Python bump
- OpenAPI surface area for a route nothing calls
- Future reader confusion about whether it's the "right" endpoint
- Documentation drift between `/history` and `/range` behaviors

What it buys: nothing git revert doesn't already provide. If we ever
need it back, `git revert <commit>` restores it intact.

If a rolling-N-days view is wanted later (a `/history`-shaped use
case), it's a one-liner on top of `/range` -- the caller computes
`from = today - N + 1`, `to = today` and calls `/range`. No new
endpoint needed, just a client-side convention.

### Backend work

**New endpoints.**
- `GET /api/production-report/range?site_id=X&from_date=YYYY-MM-DD&to_date=YYYY-MM-DD`
  returning `ProductionReportRangeResponse`. Query validation via
  Pydantic: both dates required, `from_date <= to_date`, max window
  400 days (defense against accidental full-table scans), ISO dates
  only (422 otherwise).
- `GET /api/production-report/latest-date?site_id=X` returning
  `LatestDateResponse { site_id, latest_date: date | None }`. Null
  when the source has no reports for the site. Used only on frontend
  bootstrap to seed the default day picker.

**New schemas** (in `backend/app/schemas/production_report.py`).
- `ProductionReportRangeResponse { count, site_id, from_date,
   to_date, generated_at, entries, conveyor_totals }`. Envelope
  identical to the existing history shape except `days` is replaced
  by `from_date` + `to_date`.
- `LatestDateResponse { site_id, latest_date: date | None }`.

**New service functions** (in `backend/app/services/production_report.py`).
- `get_range(source, site_id, from_date, to_date) -> list[ProductionReportRow]`
  -- filter by site + inclusive date window, newest-first sort. No
  new aggregation logic; the route handler still calls
  `compute_conveyor_totals(rows)` the same way.
- `get_latest_date(source, site_id) -> date | None` -- derives
  from `fetch_rows()` via max(prod_date). Default implementation
  against the Protocol; SQL source could override later with a
  `SELECT MAX(PRODDATE) WHERE SITE_ID = ?` query if fetch_rows ever
  becomes expensive. Not optimizing preemptively.

**Source Protocol.** No signature change. Both new services derive
from `fetch_rows()` + filter. If/when performance warrants, add
`fetch_by_range(from_date, to_date)` and `get_latest_date()` to the
Protocol with default implementations that fall back to
`fetch_rows()`.

**Removed.**
- `/api/production-report/history` route + handler
- `get_history()` service function
- `ProductionReportHistoryResponse` schema
- Query file additions if any (none today — history uses the shared
  `select_all.sql`)

**Preserved.**
- `/api/production-report/latest` (unrelated; "latest per workcenter
  regardless of date")
- `compute_conveyor_totals` (pure function over rows; aggregation
  logic unchanged -- Trey confirmed the chart totals must follow the
  new window and they do by construction)
- `/api/sites` (unchanged; stays focused on identity)
- `/api/health` (unchanged)

### Frontend work

**Sidebar TIME FILTER card redesign** (`frontend/index.html`,
`frontend/app.css`).
- Mode toggle at top of the card: Day / Month (two-button group,
  same `.gbr`/`.gb` pattern the current Today/Week/Month uses, so
  CSS lift is minimal).
- Day mode: `<input type="date" id="day-date">`. Native picker.
  `min` set to earliest-available date (computed from site's first
  report — same idea as latest-date but for min; optional
  convenience), `max` set to today.
- Month mode: two `<select>` controls side-by-side:
  `<select id="month-month">` (January..December) +
  `<select id="month-year">` (last 5 years).
- Only the active mode's controls are visible; mode toggle swaps.

**State management** (`frontend/app.js`).
- Module-scope state replaces `currentMode`:
  ```
  currentSelection = {
    mode: 'day' | 'month',
    dayDate: 'YYYY-MM-DD',         // day mode
    monthYear: 2026,               // month mode
    monthMonth: 4,                 // month mode, 1-12
  }
  ```
- `dataUrlForSelection(sel, siteId)` builds the `/range` URL:
  - day: `from=to=dayDate`
  - month: `from=YYYY-MM-01`, `to=min(last_of_month, today)` (so
    current month auto-caps at today; past months get full range)
- `selectionIncludesToday(sel)` helper for the polling gate.

**Bootstrap sequence** (new).
1. Restore `pmd-time-filter` from localStorage if present.
2. Else: `fetch('/api/production-report/latest-date?site_id=...')`,
   seed day mode with `latest_date` (or today if null).
3. Render sidebar controls reflecting the selection.
4. First `refreshData()` call uses the URL built from the selection.

**Polling control.**
- After each selection change, call `retunePolling(sel)`:
  - if `selectionIncludesToday(sel)` -> ensure the 30s interval is
    running (re-arm if previously cleared).
  - else -> `clearInterval(refreshTimer)` and set it to null; the
    one-shot `refreshData()` on selection change still fires.

**Rendering dispatch** (preserves D3).
- After `/range` response lands, group entries by `department_id`.
  For each group:
  - `len == 1` -> `renderTodayPanel(entry)` (KPI cards + asset table,
    current single-report layout).
  - `len >= 2` -> `renderHistoryPanel(deptId, entries)` (history
    table, current multi-report layout).
- Remove the `mode === "today"` branching in `renderData`; replace
  with the per-workcenter count branching above.

**Empty state wording.**
- Day pick with no data: `"Nothing reported for 2026-04-23."`
- Month pick with no data: `"Nothing reported for April 2026."`

**Export integration.**
- `exportCurrentMode()` renamed to `exportCurrentSelection()`.
- Filename patterns:
  - day: `production-metrics_<slug>_<YYYY-MM-DD>_<ts>.xlsx`
  - month: `production-metrics_<slug>_<YYYY-MM>_<ts>.xlsx`
- Sheet names similarly (`YYYY-MM-DD` or `YYYY-MM`).
- The shaping helpers (`shapeTodayRows` / `shapeHistoryRows`) are
  renamed to reflect what they actually render -- one is the
  single-report asset-table shape, the other is the multi-report
  history shape. Per-workcenter panel count branching in the export
  mirrors the rendering branching: export uses whichever shaper
  matches each group's entry count.

### Tests

**Backend.**
- Port `backend/tests/routes/test_history.py` -> `test_range.py`.
  Most test bodies translate directly since the envelope shape is
  the same -- the change is `from_date` / `to_date` params instead
  of `days`.
- New tests for `/range`:
  - valid from_date / to_date -> 200, envelope shape
  - `from_date > to_date` -> 422
  - missing either -> 422
  - window > 400 days -> 422
  - non-ISO date -> 422
  - inclusive bounds: `from=to=picked_date` returns reports with
    `prod_date::date == picked_date`
  - empty window (site has no reports in range) -> 200 with
    `entries=[]` and `conveyor_totals={}`
- New tests for `/latest-date`:
  - site with reports -> returns the newest `prod_date.date()`
  - site with no reports -> `latest_date: null`
  - missing `site_id` -> 422 (required)

**Frontend.** No automated tests today. Manual verification only.

### Documentation updates

- `backend/ARCHITECTURE.md` §6: rewrite `/history` section as
  `/range` + `/latest-date`. Note the removal of `/history`.
- `RUNBOOK.md`:
  - "Dashboard features" section: update the TIME FILTER
    description.
  - "Exporting the current view" section: update filename patterns
    (new YYYY-MM-DD / YYYY-MM scheme).
- `PAYLOAD-CONTRACT.md`: no changes (envelope shape identical).
- `tasks/decisions/`: new ADR 002 documenting the shift from rolling
  to absolute windows, pointing at D1-D7 here.

### Verification matrix (post-implementation)

Backend:
- [ ] `pytest` green (ported + new tests)
- [ ] `/range?from=2026-04-01&to=2026-04-24&site_id=101` returns
      same rows as the old `/history?days=24&site_id=101` did
      (sanity check that filter semantics match)
- [ ] `/range` with `from_date > to_date` -> 422
- [ ] `/range` with window > 400 days -> 422
- [ ] `/latest-date?site_id=101` returns the right date against live
      Azure SQL
- [ ] `/history` returns 404 (endpoint removed cleanly)

Frontend:
- [ ] First load: day picker pre-selects latest-reported day from
      `/latest-date`; panel renders data for that day
- [ ] Pick yesterday: table shows yesterday's reports
- [ ] Pick today (before any reports land): empty-state reads
      "Nothing reported for <today>"
- [ ] Pick a no-data Sunday: empty-state with correct date
- [ ] Month=current / Year=current: month-to-date view, 30s polling
      active
- [ ] Month=March / Year=2026: full March view, polling paused
- [ ] Switch month -> back to current: polling re-arms
- [ ] Persistence: refresh the page, selection sticks
- [ ] Single-shift day: KPI cards + asset table per workcenter
      (current Today layout)
- [ ] Multi-shift day: history table per workcenter (current month
      layout)
- [ ] Export filename day mode: `..._2026-04-23_<ts>.xlsx`
- [ ] Export filename month mode: `..._2026-04_<ts>.xlsx`
- [ ] Export sheet name reflects selection
- [ ] Chart grand total matches `sum(CX.Total)` across the selected
      window (unchanged logic; verify by hand against a picked day)
- [ ] Theme toggle still works; no regressions
- [ ] Network tab: selection change triggers exactly one
      `/range` fetch; no `/history` calls anywhere

### Explicit non-goals for Phase 7

- Year selector beyond the last ~5 years. Add later if needed.
- Date-range picker (pick two arbitrary dates). Day + month cover
  the 95th percentile; full range picker is a v2 if operators
  actually want it.
- Cross-window comparison (e.g. this-month vs last-month overlay).
- Timezone-aware bounds (still UTC, still naive `prod_date`; same
  caveat as Phase 5.1).
- Longer polling interval for past windows (currently either 30s
  or paused). Could be tuned later.
- Jump-to-latest-reported-day button inside the empty-state. Nice
  to have; v1.1.
- `earliest-date` endpoint (for setting the day picker's `min`
  attribute). Using `latest_date` only; `min` defaults to a
  reasonable fixed date like 2020-01-01. Can add if users scroll
  off usable data.
- Schema-driven dropdown generation (month names, year list).
  Hardcoded in `app.js` for v1.

### Open design questions (resolve if needed during implementation)

- **OQ1 -- Month picker "future month" handling.** If the user
  picks `Month=December / Year=2026` in April 2026, should we show
  "nothing reported" (consistent with how empty windows render) or
  clamp to today (so the user sees month-to-date with an inconsistent
  label)? Proposal: render the empty state; label reads "Nothing
  reported for December 2026." Consistent with past-empty behavior
  and avoids the "why does December show April data?" surprise.
- **OQ2 -- Day mode `min` attribute on input[type=date].** Native
  picker enforces it client-side. Proposal: set `min="2020-01-01"`
  (earlier than any plausible source data) and `max=today`. Cheap,
  prevents most garbage pickers. Add a real `/earliest-date`
  endpoint only if this proves insufficient.
- **OQ3 -- Rendering mode per workcenter vs per-response.** D3 says
  single-shift day -> Today layout, multi-shift day -> history
  table. Two workcenters on the same day could have different shift
  counts. Proposal: per-workcenter (the branching happens inside the
  group loop), so one site can have a KPI-card panel and a
  history-table panel side-by-side on the same day if the data
  shape warrants. Documented as intentional.
- **OQ4 -- ADR scope.** Is this change large enough to merit
  `tasks/decisions/002-absolute-time-filter.md`? I think yes --
  it's a semantic shift, not a UX tweak. Proposal: write the ADR
  during Phase 7; link D1-D7 in the body.

### Sequence to implement (after approval)

1. Backend: new Pydantic schemas (`ProductionReportRangeResponse`,
   `LatestDateResponse`).
2. Backend: new service functions (`get_range`, `get_latest_date`).
3. Backend: new route handlers (`/range`, `/latest-date`).
4. Backend: remove `/history` route + `get_history` + history schema.
5. Backend: port tests from `test_history.py` to `test_range.py`;
   write new tests for `/latest-date`.
6. Backend: run `pytest` + `ruff check` + `ruff format`; verify
   against live Azure SQL.
7. Frontend: redesign TIME FILTER card (HTML + CSS).
8. Frontend: state management (`currentSelection`, URL builder,
   polling gate).
9. Frontend: bootstrap with `/latest-date` + localStorage
   persistence.
10. Frontend: rendering dispatch (per-workcenter shift-count
    branching).
11. Frontend: empty-state wording.
12. Export integration: filename pattern + sheet name updates.
13. Docs: RUNBOOK, `backend/ARCHITECTURE.md`, new ADR in
    `tasks/decisions/`.
14. Manual verification on uvicorn (port 8000), then Docker (port
    8001) as regression.
15. Check Phase 7 items off in `tasks/todo.md`.

### Risk / sequencing notes

- The backend changes ship cleanly as a single unit (new endpoints +
  removed `/history`) because nothing currently calls `/history`
  except the frontend, and the frontend is changing in the same PR.
  No deprecation window needed.
- The frontend changes can ship in one PR or two: (A) rewire to new
  endpoints but keep the 3-button UI temporarily, then (B) swap the
  UI for the day/month pickers. Slightly lower risk but two-phase
  work. Proposal: single PR, since the backend and frontend are
  strongly coupled here and rolling them together is less confusing.
- Edit-tool truncation lesson still applies. All file rewrites for
  `app.js` and similarly long files go via bash heredoc or Python.
- Export integration (Phase 6) depends on `currentMode` today; after
  Phase 7 it'll depend on `currentSelection`. That dependency change
  is real and must land in the same PR or the Export button breaks.

### Implementation progress (2026-04-24)

All planned code landed. Python and Node syntax checks clean;
shape-verification harness runs 22/22 green on the new
asset-row export path. Browser verification still pending Trey's
Windows-host run-through.

Backend done:
- [x] `backend/app/schemas/production_report.py` -- added
      `ProductionReportRangeResponse` and `LatestDateResponse`;
      removed `ProductionReportHistoryResponse`.
- [x] `backend/app/services/production_report.py` -- added
      `get_range(*, from_date, to_date, site_id)` (keyword-only
      args to prevent accidental positional misuse) and
      `get_latest_date(*, site_id)`; removed `get_history()`. Both
      derive from `fetch_rows()` + filter, so the CSV and SQL
      sources require no changes.
- [x] `backend/app/api/routes/production_report.py` -- added
      `/range` handler with route-level validation (from > to,
      window > 400 days), `/latest-date` handler with required
      site_id. Removed `/history` handler and associated imports.
      `compute_conveyor_totals` import and call pattern unchanged.
- [x] `backend/app/main.py` -- `BUILD_TAG` bumped to
      `2026-04-24-phase7-range` so the new code is fingerprint-able
      in startup logs / `/api/__ping`.
- [x] `backend/tests/api/test_production_report.py` -- 6 `/latest`
      tests preserved verbatim; 12 new `/range` tests cover the
      ported history cases plus from>to, oversized window,
      non-ISO dates, missing params, inclusive-single-day,
      empty-window envelope, and 400-day boundary; 3 new
      `/latest-date` tests cover happy-path, unknown-site null,
      and required-site_id; 1 regression guard asserts
      `/history` returns 404.
- [x] `py_compile` clean on every backend file (excluding
      `core/snapshot.py` which uses Python 3.12 PEP 695 generic
      class syntax that 3.10 can't parse -- compiles fine on
      Trey's 3.12 venv).
- [x] No orphaned `get_history` / `ProductionReportHistoryResponse`
      references anywhere except intentional migration notes in
      service + schema docstrings.

Frontend done:
- [x] `frontend/index.html` -- TIME FILTER card rebuilt. Day/Month
      mode toggle using the existing `.gbr`/`.gb` style; day-body
      with `<input type=date id="day-date" min="2020-01-01">`;
      month-body with `<select id="month-month">` (January..December)
      and `<select id="month-year">` (populated by JS with current
      year + 4 back).
- [x] `frontend/app.css` -- new `.filter-body`, `.filter-label`,
      `.date-input`, `.month-pickers`, `.month-select` rules. Accent
      outline on focus matches the theme-toggle affordance.
- [x] `frontend/app.js` -- rewritten (734 -> 899 lines). Key
      changes:
      - `currentMode` replaced by `currentSelection` object
        (`{mode, dayDate, monthYear, monthMonth}`) with
        localStorage persistence (`pmd-time-filter`) and a
        shape-validator so bad JSON doesn't break bootstrap.
      - `dataUrlForSelection(sel, siteId)` builds the `/range` URL
        from the current selection. Month mode's `to_date` caps at
        today for the current month (OQ1).
      - `fetchLatestDate(siteId)` + bootstrap logic to seed the
        day picker with the newest-date-with-data for the default
        site, falling back to today if the site has no reports.
      - `wireTimeFilterControls()` handles mode-toggle clicks,
        date-input change, and month/year dropdown change; each
        fires `onSelectionChanged()` -> save + rerender chips +
        retune polling + immediate fetch.
      - `retunePolling()` clears the 30s interval when the
        selection is fully past (no new data is going to land),
        re-arms when it pulls today back in. Runs after every
        selection change + after each successful fetch.
      - `renderData(payload)` (mode parameter dropped) groups
        entries by `department_id` and dispatches per-workcenter:
        1 entry -> `renderSingleReportPanel` (KPI + asset table),
        2+ entries -> `renderHistoryPanel` (history table). A
        day can have mixed layouts side-by-side (OQ3).
      - Empty-state wording uses `selectionLabel(sel)`: "Nothing
        reported for 2026-04-23." / "Nothing reported for April
        2026."
      - Export (Phase 6) renamed `exportCurrentMode` ->
        `exportCurrentSelection`. Single unified `shapeAssetRows`
        replaces the two old shapers. 13-column schema includes
        Prod. Date + Report ID; single- and multi-shift windows
        share the layout. Filename: `..._<selection-slug>_<ts>.xlsx`.
        Sheet name matches the slug (`2026-04-23` or `2026-04`).
- [x] Node `--check` clean.
- [x] Shape-verification harness: 22/22 assertions green on a
      synthesized envelope with a 2-shift day (dept 127) next to
      a 1-shift day (dept 129). Null-handling carries through
      (null Performance/Total -> missing cells; `_` placeholder
      -> missing cell); newest-first within dept preserved;
      numeric + format codes applied correctly; slug format
      produces `2026-04-23` / `2026-04` as expected.

Docs done:
- [x] `tasks/decisions/002-absolute-time-filter.md` -- new ADR
      documenting context, decision, alternatives considered,
      positive/negative consequences.
- [x] `backend/ARCHITECTURE.md` -- §6.4 rewritten as `/range`,
      §6.5 added for `/latest-date`, §6 closing paragraph updated
      to describe the shared `conveyor_totals` field on both
      endpoints. Module-map comment updated. Query-validation
      reference updated to cite `from_date`/`to_date` typing.
- [x] `RUNBOOK.md` -- URL table swapped `/history` rows for
      `/range` + `/latest-date` examples; validation note updated;
      Dashboard features section rewritten to describe Day/Month
      modes; pytest filter example bumped to `-k range`;
      Exporting section updated to the new unified asset-row
      schema and filename pattern.
- [x] `tasks/todo.md` -- Phase 7 header flipped to IMPLEMENTED;
      this block added.

Pending:
- [ ] Browser QA on the Windows host per the Phase 7 verification
      matrix. Specifically worth probing:
      - [ ] Day picker pre-selects the newest date with data for
            site 101 on first load.
      - [ ] Pick yesterday -> table renders yesterday's reports.
      - [ ] Pick today before any reports land -> empty-state
            reads "Nothing reported for <today>."
      - [ ] Pick a Sunday / no-data day -> empty-state.
      - [ ] Month mode, current month, current year -> month-to-date
            view with polling active.
      - [ ] Month mode, past month -> polling paused.
      - [ ] Switch from past month back to current month -> polling
            re-arms.
      - [ ] Refresh the page after a selection -> selection persists.
      - [ ] Single-shift day -> KPI cards + asset table per panel.
      - [ ] Multi-shift day (if present in real data) -> history
            table for that workcenter only; other workcenters stay
            on the asset-table layout.
      - [ ] Chart grand total tracks the selected window (Phase 5
            logic is unchanged but worth a visual sanity check).
      - [ ] Export day mode -> `..._2026-04-23_<ts>.xlsx`.
      - [ ] Export month mode -> `..._2026-04_<ts>.xlsx`.
      - [ ] Export sheet name matches the slug.
      - [ ] `=AVERAGE()` on percentage columns returns a numeric
            mean in Excel; null cells are skipped.
      - [ ] Theme toggle still instant-updates chart colors.
      - [ ] Network tab: selection change -> exactly one `/range`
            call, no `/history` calls anywhere.
      - [ ] Docker path (port 8001) behaves identically to venv
            (port 8000). Backend image rebuild required
            (`docker compose up --build`) since backend code
            changed; frontend is bind-mounted so the new UI is
            already in place.
- [ ] `pytest` on the Windows 3.12 venv. The test file is
      syntax-valid but hasn't been run against the real FastAPI +
      Pydantic stack.

Deliberate departures from the plan:
- The plan's "per-workcenter rendering dispatch" (OQ3) was
  implemented exactly as proposed -- no change.
- The export shape became a *single* asset-row schema instead of
  two distinct shapes (the old Phase 6 behavior). Rationale: the
  new per-workcenter layout means a single export could need to
  cover both single- and multi-shift workcenters on the same day;
  picking one schema lets the user pivot in Excel rather than
  dealing with context-dependent column counts. Prod. Date +
  Report ID are now always present so rows are self-identifying.
- The sample-data fixture dates (March-April 2026) are not
  pinned to specific constants in the new range tests.
  `_FULL_COVERAGE_FROM = "2025-05-01"` / `_FULL_COVERAGE_TO =
  "2026-06-04"` is a 400-day window chosen to cover the sample
  without depending on the sample's exact boundaries -- if the
  fixture moves forward by a year, the tests will need the
  window moved forward too. Flagged for future maintenance.

## Phase 8 — Weather + notes enrichment + details modal (IMPLEMENTED 2026-04-24, browser QA pending)

**Trigger:** Trey wants each production-report row enriched with shift,
weather (conditions / avg temp / avg humidity / max wind), and free-form
notes, coming from two adjacent SQL tables already joined by an existing
stored procedure `[UNS].[GET_PRODUCTION_RUN_REPORTS]`.

### Decisions

- **D1 -- SQL approach.** Option B: replicate the SP's joins in our own
  `select_all.sql` rather than `EXEC`-ing the SP. Keeps the
  Phase 3 pattern (query files under `integrations/production_report/
  queries/`), stays one round-trip per `/range`, avoids N-per-department
  SP calls. The SP itself is documented as the canonical reference in
  a comment at the top of the new query file.
- **D2 -- LEFT JOIN on history.** The SP uses INNER JOIN against
  SITE_PRODUCTION_RUN_HISTORY, which would drop any report that doesn't
  have a history row. Our query uses LEFT JOIN so every report still
  comes back (matches today's `select_all.sql` "return all rows"
  behavior). Null shift/weather on a historyless row is acceptable.
- **D3 -- Dataclass + schema.** `ProductionReportRow` gains six optional
  fields with defaults of `None`: `shift`, `weather_conditions`,
  `avg_temp`, `avg_humidity`, `max_wind_speed`, `notes`. Pydantic
  `ProductionReportEntry` mirrors the same fields, all optional on the
  wire. CSV source returns None for all six (no weather data in the
  sample file).
- **D4 -- Rendering.** Unified Details modal across both panel types.
  Multi-report panel gains three new columns (Shift / Weather / Details
  button); Details button opens a modal with full weather grid + full
  notes text. Single-report panel gains Shift in the header, a weather
  chip row next to the metadata, and a Details button opens the same
  modal. One modal component, one interaction model.
- **D5 -- Weather summary format.** `"<Condition>  <AvgTemp>°F"` in
  the table cell (e.g. `"Sunny  72°F"`). Temperature is the most
  commonly-referenced value on a plant floor; humidity and wind are in
  the modal. Revisit if a site prioritizes humidity or wind.
- **D6 -- Export.** Tail-append six columns on the existing asset-row
  sheet: Shift / Weather Conditions / Avg Temp / Avg Humidity / Max
  Wind / Notes. Weather/notes repeat across a workcenter's assets for
  the same report -- accepted as the cost of one-sheet flat schema
  (pivot in Excel to collapse).

### Backend

- [ ] `backend/app/integrations/production_report/base.py` --
      `ProductionReportRow` gains six optional fields.
- [ ] `backend/app/integrations/production_report/queries/select_all.sql` --
      rewritten to the enriched query (two LEFT JOINs; SP referenced in
      the top comment as the canonical source of the join logic).
- [ ] `backend/app/integrations/production_report/sql_source.py` --
      `_row_to_dataclass` updated to read the new 13-column layout.
      Column-order comment updated.
- [ ] `backend/app/integrations/production_report/csv_source.py` --
      no functional change; dataclass defaults handle missing fields.
- [ ] `backend/app/schemas/production_report.py` --
      `ProductionReportEntry` gains six optional fields mirroring the
      dataclass.
- [ ] `backend/app/api/routes/production_report.py` -- `_to_entry`
      helper passes new fields through.
- [ ] `backend/tests/integrations/test_sql_source.py` -- existing test
      tuples expanded to 13 columns; new test asserting the new fields
      land on the dataclass.
- [ ] `backend/app/main.py` -- `BUILD_TAG` bumped.

### Frontend

- [ ] `frontend/index.html` -- modal markup (hidden backdrop + dialog
      with weather grid + notes block + close button).
- [ ] `frontend/app.css` -- `.details-modal-*` styles, weather chip row,
      ESC key / click-outside affordance.
- [ ] `frontend/app.js` --
      - `openDetailsModal(entry)` / `closeDetailsModal()` with ESC and
        click-outside handlers; focus trap inside dialog while open.
      - `weatherSummary(entry)` helper -> compact "<Condition>  <Temp>°F"
        string (or em-dash if weather absent).
      - `detailsButton(entry)` DOM helper -> small icon button.
      - `renderSingleReportPanel`: Shift added to header metadata;
        weather chip row in header area; Details button next to status.
      - `renderHistoryPanel`: Shift / Weather / Details columns in
        history table; `historyRow` emits Shift + Weather summary +
        Details button (replaces the row-click model we discussed in
        option 2 earlier).
      - `shapeAssetRows`: six tail-appended columns.

### Docs

- [ ] `tasks/decisions/003-enrichment-joins.md` -- ADR documenting D1-D6.
- [ ] `backend/ARCHITECTURE.md` -- §5.2 impl table updated; §6.3/6.4
      response-shape notes updated; §4.5 type-contract table extended.
- [ ] `RUNBOOK.md` -- Exporting section (19 columns now);
      Dashboard-features section mentions weather/notes/shift and the
      modal.

### Verification

Programmatic:
- [ ] `py_compile` clean on all touched backend files.
- [ ] `node --check` clean on `app.js`.
- [ ] Shape harness (extend the Phase 6/7 one) verifies the new export
      columns land where expected, weather+notes repeat across asset
      rows for the same report, and null weather/notes from the CSV
      source produce truly-blank cells.

On the Windows host (pending Trey's run):
- [ ] `pytest` green; test count grows by ~1-3.
- [ ] `/range` response for site 101 includes the six new fields on
      every entry; null on entries whose history row is absent.
- [ ] Dashboard renders the weather summary in the history table and
      the Shift column; clicking Details opens the modal with the full
      grid + notes.
- [ ] ESC and click-outside close the modal; focus returns to the
      Details button that opened it.
- [ ] Export includes the six new columns tail-appended.
- [ ] Live SQL against Azure Managed SQL returns populated weather
      fields (confirms the SP tables are reachable and the LEFT JOINs
      resolve).

### Implementation progress (2026-04-24)

All planned code landed. py_compile clean on every touched backend
file; node --check clean on app.js. Backend unit-test file expanded
from 8 to 10 tests (two new: `test_fetch_rows_reads_enrichment_fields`
and `test_fetch_rows_tolerates_null_enrichment_from_left_join_miss`).
Browser QA still pending Trey's Windows-host run-through.

Backend done:
- [x] `base.py` -- `ProductionReportRow` grew 6 optional fields with
      `field(default=None)`. No caller migration needed; existing
      construction sites (CSV + SQL sources, tests) stay valid.
- [x] `queries/select_all.sql` -- rewritten with LEFT JOINs against
      `SITE_PRODUCTION_RUN_HISTORY` and `SITE_PRODUCTION_RUN_COMMENTS`.
      Top-of-file comment names the SP as the canonical reference
      and documents the LEFT-vs-INNER divergence.
- [x] `sql_source.py` -- `_row_to_dataclass` reads the 13-column
      row; `_to_float_or_none` helper coerces Decimal / numeric to
      float. Column-order doc updated.
- [x] `csv_source.py` -- unchanged; dataclass defaults carry the
      Nones through transparently.
- [x] `schemas/production_report.py` -- `ProductionReportEntry`
      gains 6 optional fields mirroring the dataclass.
- [x] `routes/production_report.py` -- `_to_entry` passes the new
      fields through.
- [x] `main.py` -- `BUILD_TAG` bumped to
      `2026-04-24-phase8-enrichment`.
- [x] `test_sql_source.py` -- all fake-cursor tuples expanded to
      13 columns via a `_row()` keyword-arg helper so future field
      additions stay contained. Two new tests for the enrichment
      path (populated + NULL-from-LEFT-JOIN-miss). The existing
      8 tests re-verify the unchanged contract.

Frontend done:
- [x] `index.html` -- Details modal markup added (backdrop +
      dialog + close button). Hidden on load; shown by
      `openDetailsModal()`.
- [x] `app.css` -- `.details-modal-*` styles, `.details-btn`
      styles, weather-strip, `.wi-wrap` icon wrapper (14px default,
      28px modal, 13px strip), modal weather layout (icon header
      row + 3-column metric grid + "All conditions: ..." line).
- [x] `app.js` -- top-level changes:
      - `_modalLastFocus` module state for focus restoration.
      - 11 inline SVG weather icons in `WEATHER_ICONS` dict.
      - `WEATHER_SEVERITY` ordered worst-first; `pickWeatherIcon`
        scans the STUFF'd condition string and returns the first
        matching severity bucket. Unknown phrasings log a
        `console.warn` once per unique string.
      - `renderWeatherIcon(iconKey, extraClass)` builds a DOM span
        with `innerHTML` set to the SVG.
      - `weatherSummary(entry)` now returns a DOM element: icon +
        temp (or icon alone, or temp alone, or em-dash).
      - `weatherStrip(entry)` prepends the icon to the chip row.
      - `openDetailsModal(entry)` builds the three-section body
        (Report / Weather / Notes) with the 28px icon in the
        weather header and the full STUFF'd list as a trailing
        "All conditions: ..." line.
      - Modal close button wired in `bootstrap()`; backdrop click
        and ESC key wired transiently inside open/close.
      - `renderSingleReportPanel` grew `Shift:` in header
        metadata, a weather chip strip when weather is present,
        and a Details button next to the status pill.
      - `renderHistoryPanel` grew Shift / Weather / Details
        columns in the history table; `historyRow` emits the
        matching cells.
      - `shapeAssetRows` (export) tail-appends Shift / Weather
        Conditions / Avg Temp / Avg Humidity / Max Wind / Notes
        as six new columns (13 -> 19). `exportCurrentSelection`
        adds XLSX number formats for the new numeric columns
        (`0.0"°F"`, `0.0"%"`, `0.0`).

Docs done:
- [x] `tasks/decisions/003-enrichment-joins.md` -- full ADR with
      D1-D6, alternatives considered, consequences.
- [x] `backend/ARCHITECTURE.md` -- new §6.6 documenting the six
      enrichment fields + their sources + CSV/LEFT-JOIN null
      semantics.
- [x] `RUNBOOK.md` -- Exporting section updated to 19 columns;
      Dashboard features section describes the Details modal,
      icon severity ranking, and modal interaction (ESC /
      backdrop click to close).

Pending:
- [ ] Browser QA on the Windows host. Things to exercise:
      - [ ] Dashboard renders. Hard-refresh (Ctrl+Shift+R) after
            Docker rebuild since backend changed.
      - [ ] `/api/__ping` shows `build_tag:
            "2026-04-24-phase8-enrichment"`.
      - [ ] `/api/production-report/range?...` envelope includes
            the six new fields on every entry; `None`/null for
            rows whose LEFT JOIN misses; populated for rows with
            a history + comments row.
      - [ ] History table shows Shift / Weather / Details
            columns; icon + temp in the Weather cell.
      - [ ] Single-report panel header shows Shift + weather
            strip; Details button opens the modal.
      - [ ] Modal: icon + primary condition header; three metric
            cells; full STUFF'd condition list under them; notes
            block at the bottom.
      - [ ] ESC closes the modal; backdrop click closes; close
            (X) button closes; focus returns to the Details
            button that opened it.
      - [ ] Export includes the six new columns. `=AVERAGE()` on
            Avg Temp / Avg Humidity columns returns a number.
      - [ ] Theme toggle still works; icons track the color.
      - [ ] A shift with a multi-condition `WEATHER_CONDITIONS`
            (e.g. `"broken clouds, clear sky, light rain"`) gets
            the rain icon in the table but shows the full list
            in the modal.
      - [ ] A shift with `WEATHER_CONDITIONS == NULL` and no
            notes shows em-dash in Weather / Shift columns, no
            weather strip in the panel header, and the modal
            shows the "No weather data" / "No notes" empty
            states.
- [ ] `pytest` on the Windows 3.12 venv. Test count grows to
      ~24 (API tests unchanged; SQL source tests 8 -> 10).
- [ ] Live SQL check against Azure Managed SQL: confirm the
      HISTORY + COMMENTS tables are reachable + the LEFT JOINs
      populate.

Follow-up flagged but not blocking:
- If the DBA is open to it, ask them to add ID / SITE_ID /
  DEPARTMENT_ID / DTM to the SP's SELECT list. That would let us
  collapse the join duplication by replacing `select_all.sql`'s
  query body with `EXEC [UNS].[GET_PRODUCTION_RUN_REPORTS]`, and we
  delete the LEFT JOINs from our own SQL. Not urgent; flagged for
  a future phase.
- If operations reveals that WEATHER_CONDITIONS phrasing varies
  more than the current severity ranking anticipates, extend
  `WEATHER_SEVERITY` rather than adding a new data path. The
  console.warn surfaces unknown phrasings for triage.

## Phase 9 — Interval metrics: Flow REST integration (IMPLEMENTED 2026-04-27, browser QA pending)

**Trigger:** Implement the interval-metrics retrieval path agreed in
the Phase 8/data-flows discussion. Backend pulls per-tag history URLs
from `[FLOW].[INTERVAL_METRIC_TAGS]`, fans out to Flow's REST API via
httpx, and serves the consolidated time-series under
`/api/metrics/conveyor/{interval}`.

### Decisions (from the design conversation, 2026-04-25 → 2026-04-27)

- **D1 -- Auth.** `FLOW_API_KEY` from `backend/.env` is the bearer
  token directly. No exchange / refresh / token-caching. Mirrors the
  existing Ignition example client which does
  `Authorization: Bearer <api_key_string>`.
- **D2 -- URL substitution.** Literal `str.replace` of
  `[PeriodStart]` / `[PeriodEnd]` with ISO-8601 millisecond UTC
  strings (e.g. `2026-04-01T00:00:00.000Z`). No URL-encoding of the
  bracket placeholders or the timestamps; they're not URL-special
  in this position.
- **D3 -- Pagination strategy.** Option (a): accept the URL-baked
  `limit=1000`. If a single-tag fetch returns exactly 1000 points,
  surface a `truncated: true` field in the response envelope so the
  consumer knows to narrow the window. Don't auto-chunk in v1.
- **D4 -- Timeout / retry.** httpx 30s per request, no automatic
  retry. Failures bubble up as `503 Service Unavailable` from the
  route layer, mirroring how SQL-pool failures surface.
- **D5 -- Caching.** SnapshotStore (the Protocol seam from Phase 1
  in `core/snapshot.py`) used at the service layer with TTL gating.
  Default TTLs: 5 min hourly, 15 min shiftly. Cache key is the full
  filter combination.
- **D6 -- Defensive limits at the route layer.**
  - Max window: 31 days for hourly, 400 days for shiftly.
  - Max points cap: 50,000 entries per response. 422 with a hint
    about narrowing if exceeded.
- **D7 -- Filter composition.** All endpoint filters compose:
  `site_id` + dates required, `department_id` / `subject_id` /
  `metric` optional. Same endpoint serves Ignition single-tag
  fetches, dashboard bulk fetches, and future multi-site reports.
- **D8 -- Discovery endpoint.** `GET /api/metrics/conveyor/subjects`
  returns just the tag inventory + last-seen DTM. No HTTP fan-out.
  Useful for Ignition dropdowns and dashboard inventory pages.

### Files to create

```
backend/app/integrations/
├── external/
│   ├── __init__.py
│   └── flow_client.py            -- httpx.AsyncClient wrapper
└── metrics/
    ├── __init__.py
    ├── base.py                    -- IntervalMetricSource Protocol + IntervalMetricPoint dataclass
    ├── sql_source.py              -- reads INTERVAL_METRIC_TAGS, fans out to FlowClient
    └── queries/
        └── select_tags.sql        -- parameterized SELECT against [FLOW].[INTERVAL_METRIC_TAGS]
```

```
backend/app/services/metrics.py    -- service layer (window filter, fan-out, snapshot store)
backend/app/api/routes/metrics.py  -- /api/metrics/conveyor/{interval} + /subjects
backend/app/schemas/metrics.py     -- IntervalMetricsResponse, IntervalMetricEntry, IntervalMetricSubject
```

```
backend/tests/integrations/test_flow_client.py
backend/tests/integrations/test_metrics_sql_source.py
backend/tests/services/test_metrics.py
backend/tests/api/test_metrics.py
```

### Files to modify

- `backend/app/core/config.py` -- add `flow_api_key: SecretStr | None`,
  `flow_api_timeout_seconds: float`, `metrics_cache_ttl_hourly_s: int`,
  `metrics_cache_ttl_shiftly_s: int`.
- `backend/app/api/dependencies.py` -- add
  `get_interval_metric_source(request)` provider; raises 503 if SQL
  pool or `FLOW_API_KEY` are missing.
- `backend/app/main.py` -- mount metrics router; create the
  `InMemorySnapshotStore` on `app.state.snapshot_store` in lifespan;
  bump `BUILD_TAG`.

### Endpoint signatures

```
GET /api/metrics/conveyor/{interval}
        ?site_id=101                  [required]
        &department_id=127            [optional]
        &subject_id=C4                [optional]
        &metric=tons                  [optional]
        &from_date=2026-04-01         [required, ISO YYYY-MM-DD]
        &to_date=2026-04-24           [required, ISO YYYY-MM-DD]

  → IntervalMetricsResponse {
      count, subject_type, interval, site_id, department_id,
      subject_id, metric, from_date, to_date, generated_at,
      truncated: bool, entries: [IntervalMetricEntry]
    }

GET /api/metrics/conveyor/subjects
        ?site_id=101                  [required]
        &department_id=127            [optional]

  → IntervalMetricSubjectsResponse {
      count, subject_type, site_id, department_id,
      subjects: [IntervalMetricSubject {
        subject_id, metric_names, intervals, last_seen
      }]
    }
```

### Verification

Programmatic:
- [ ] `py_compile` clean on all new files.
- [ ] Tests pass against fake aioodbc pool + mock httpx (no real SQL,
      no real Flow API calls).

On the Windows host (pending Trey's run):
- [ ] `pytest` green.
- [ ] `/api/__ping` shows the new `BUILD_TAG`.
- [ ] `FLOW_API_KEY` present in `backend/.env`.
- [ ] `[FLOW].[INTERVAL_METRIC_TAGS]` populated with at least one
      row (Trey's Ignition trigger writes it).
- [ ] `/api/metrics/conveyor/shiftly?site_id=101&from_date=...&to_date=...`
      returns a populated envelope.
- [ ] `/api/metrics/conveyor/subjects?site_id=101` lists tags.
- [ ] Docker container can reach `dbp-bcq:4501` (or whatever the
      Flow host is). If not, `extra_hosts` in `docker-compose.yml`.
- [ ] Cache TTL behaviour: second request within TTL doesn't fan
      out to Flow (visible in container logs).

### Implementation sequence

1. Schemas + Protocol + dataclass (no dependencies).
2. `FlowClient` (httpx wrapper). Tests against mock httpx.
3. `SqlIntervalMetricSource` (reads tag table, fans out via FlowClient).
   Tests against fake pool + mock httpx.
4. Service layer (window filter, max-points enforcement, snapshot caching).
5. Route handlers + Pydantic envelope.
6. Wire DI provider + main.py + config additions.
7. Verify against live Flow API on Trey's host.

### Implementation progress (2026-04-27)

Backend code-complete. py_compile clean across the whole backend
(excluding `core/snapshot.py` which uses Python 3.12 PEP 695 generic
class syntax that 3.10 can't parse -- compiles fine on Trey's 3.12
venv). 27 new tests across 4 test files, all py_compile clean. No
orphan references; new symbols wired through in main.py + dependencies.

Files created:
- [x] `backend/app/schemas/metrics.py` -- IntervalMetricEntry,
      IntervalMetricsResponse, IntervalMetricSubject (schema),
      IntervalMetricSubjectsResponse.
- [x] `backend/app/integrations/external/flow_client.py` -- FlowClient
      (httpx wrapper), format_flow_iso, substitute_period,
      parse_url_limit, FlowFetchResult dataclass. Accepts an
      optional transport parameter for test injection.
- [x] `backend/app/integrations/metrics/base.py` -- IntervalMetricSource
      Protocol, IntervalMetricPoint dataclass, IntervalMetricSubject
      dataclass, FetchPointsResult.
- [x] `backend/app/integrations/metrics/sql_source.py` --
      SqlIntervalMetricSource. Reads tag rows, fans out via
      asyncio.gather to FlowClient, parses Flow timestamps
      (handles both 3-digit ms and 7-digit .NET fractional seconds),
      surfaces truncation flag.
- [x] `backend/app/integrations/metrics/queries/select_tags.sql` --
      Optional-filter pattern with `(? IS NULL OR col = ?)` for
      department_id / asset / metric_name / interval. 10 bound
      params total (4 are optional pairs).
- [x] `backend/app/integrations/metrics/queries/select_subjects.sql`
      -- Aggregated discovery query, grouped per (asset, dept,
      metric, interval) with MAX(DTM); Python aggregates further
      to one IntervalMetricSubject per asset.
- [x] `backend/app/services/metrics.py` -- get_interval_metrics
      (window/size validation, SnapshotStore TTL caching),
      list_metric_subjects (pure delegation).
- [x] `backend/app/api/routes/metrics.py` --
      GET /api/metrics/conveyor/{interval} (Literal["hourly", "shiftly"]
      path param), GET /api/metrics/conveyor/subjects.
- [x] `backend/tests/integrations/test_flow_client.py` -- 8 tests
      via httpx.MockTransport (URL substitution, headers, response
      parsing, error propagation, truncation detection, empty values,
      aopen guard). 3 of 8 are pure-function helper tests.
- [x] `backend/tests/integrations/test_metrics_sql_source.py` -- 7
      tests via fake aioodbc + FakeFlowClient (timestamp parsing,
      ping, fan-out, truncation flag, empty-tag short-circuit,
      list_subjects aggregation).
- [x] `backend/tests/services/test_metrics.py` -- 6 tests
      (inverted window, oversized window, oversized result,
      cache-within-TTL, truncation forward, list_subjects delegation).
      Cache-hit test verifies the source is called exactly once
      across two identical requests.
- [x] `backend/tests/api/test_metrics.py` -- 6 tests via TestClient
      + dependency_overrides (subjects endpoint, history happy path,
      Literal interval rejection, inverted window, missing site_id,
      truncation flag forwarding).

Files modified:
- [x] `backend/app/core/config.py` -- added flow_api_key (SecretStr,
      AliasChoices PMD_FLOW_API_KEY / FLOW_API_KEY),
      flow_api_timeout_seconds, metrics_cache_ttl_hourly_s,
      metrics_cache_ttl_shiftly_s, metrics_max_points,
      metrics_max_window_days_hourly, metrics_max_window_days_shiftly.
- [x] `backend/app/api/dependencies.py` -- added
      get_interval_metric_source. Returns 503 with a clear detail
      naming the missing dependency (sql_pool, flow_client, or both).
- [x] `backend/app/main.py` -- imports for metrics router,
      InMemorySnapshotStore, FlowClient. Lifespan creates
      app.state.snapshot_store unconditionally and
      app.state.flow_client when FLOW_API_KEY is set. Closes
      flow_client before sql_pool on shutdown. Mounts metrics
      router under /api/metrics. Adds OpenAPI tag. BUILD_TAG bumped
      to "2026-04-27-phase9-metrics".

Pending:
- [ ] `pytest` on the Windows 3.12 venv. Test count grows to ~83
      (~56 prior phases + 27 new metrics tests). All structural;
      no real DB or HTTP needed.
- [ ] Live Flow API spot-check from Trey's host: confirm the bearer
      token works, the URL substitution is accepted, and a one-tag
      shiftly fetch returns the expected shape. May need
      `extra_hosts` in docker-compose.yml if `dbp-bcq` doesn't
      resolve from inside the container.
- [ ] Confirm `[FLOW].[INTERVAL_METRIC_TAGS]` has at least one row
      (Trey's Ignition trigger writes it; row appears on first
      MQTT publish per tag).
- [ ] `/api/__ping` shows the new BUILD_TAG.
- [ ] `/api/metrics/conveyor/subjects?site_id=101` returns the
      tag inventory.
- [ ] `/api/metrics/conveyor/shiftly?site_id=101&from_date=...&to_date=...`
      returns populated entries.
- [ ] Cache observation: a second identical request within 5/15
      minutes should not produce new outbound HTTP traffic
      (visible in container logs).

Frontend integration is intentionally out of scope for this phase --
that's the next chunk per Trey's request 2026-04-27.

Deliberate departures from the plan:
- `unit` field on `IntervalMetricPoint` defaults to None for now.
  The tag table doesn't carry a `unit` column today (only the MQTT
  payload's `measure.uom = "Tons"` would supply it, and the
  Ignition trigger doesn't extract it). Adding `unit` to the
  schema + trigger is a small follow-up; doesn't block this phase.
- Pagination strategy is "accept the cap + flag truncated" per
  D3. No automatic chunk-and-retry. Worth revisiting only if
  observation shows real consumers hitting the cap regularly.

## Phase 10 — Trends view: monthly rollups (IMPLEMENTED 2026-04-27, browser QA pending)

**Trigger:** Manager request for "chart of each field that can be
filtered by month and trended by month." Plus Trey's preference to
keep math out of the frontend by aggregating in a backend service.

### Decisions (from the design conversation, 2026-04-27)

- **D1 -- Math lives in the backend.** New
  `/api/production-report/monthly-rollup` endpoint computes per-month
  totals server-side. Frontend just renders. Reasons: math in Python
  is testable; other consumers (Ignition / Excel) get the same
  numbers; migration to Flow-sourced monthly metrics later is a
  contained swap inside the service.
- **D2 -- Phase 10a (backend) and Phase 10b (frontend) are sequenced.**
  10a ships an additive backend endpoint with no frontend impact.
  10b adds the tabs + trends view consuming it. Either can ship
  independently if needed.
- **D3 -- First-cut metrics: `total_tons` and `tph` per workcenter
  per month.** Averages (Availability, Performance) and
  product-specific cuts (e.g. #57) come in later sub-phases of 10.
- **D4 -- Service uses production-report data today; Flow monthly
  metrics later.** When Flow publishes monthly aggregates of the
  metrics ops cares about, the service's internal data path swaps
  from `source.fetch_rows()` to
  `metric_source.fetch_points(interval='monthly')`. Wire contract
  to consumers stays identical.
- **D5 -- Tab system in the existing index.html, hash-routed.**
  `#dashboard` (default) shows the existing view; `#trends` shows
  the new trends view. Site selector + theme toggle stay in the
  shared topbar.
- **D6 -- Client-side grouping, server-side math.** The endpoint
  returns one flat row per `(department_id, month)` with the
  aggregates pre-computed. Frontend groups by `department_id` for
  the multi-line chart. No JS arithmetic on the metric values.

### Phase 10a -- Backend monthly-rollup service

Files to create / modify:

- [ ] `backend/app/schemas/production_report.py` -- add
      `MonthlyRollupEntry` and `MonthlyRollupResponse` Pydantic models.
- [ ] `backend/app/services/production_report.py` -- add
      `get_monthly_rollup()` service function and `MonthlyRollup`
      frozen dataclass. Reuses Phase 5's CX-discovery via
      `compute_conveyor_totals()`. Emits one rollup per
      `(department_id, year-month)`.
- [ ] `backend/app/api/routes/production_report.py` -- add
      `/monthly-rollup` route. Validates `from_month`/`to_month`
      as YYYY-MM strings, enforces ~3-year max span, returns 422
      on bad input.
- [ ] `backend/tests/api/test_production_report.py` -- 6-8 new tests
      against the sample CSV: happy path, missing params,
      malformed month, inverted window, oversized window, empty
      result for a window with no data, division-by-zero guard

## Phase 11 -- Site metadata in modal + XLSX export (IMPLEMENTED 2026-04-28, browser QA pending)

### Goal

Render every key/value pair from `entry.payload.Metrics.Site` in the
existing Details modal alongside Weather and Notes. Display must be
**dynamic** -- the operator-input field set is explicitly open-ended
per `payload-schema.md`, and different sites or future payloads may
carry different keys.

### Why frontend-only

The payload is already a passthrough field on
`ProductionReportEntry.payload` (`dict[str, Any]`). The Site object
arrives at the frontend untouched. No backend, schema, or SQL change
is required -- this is purely a render concern in `openDetailsModal()`.

### Decisions

- **D1 -- Frontend-only**, no Pydantic model, no API change. The
  schema doc explicitly calls Site "open-ended"; adding a typed model
  now would lock the shape and create churn when fields are added
  upstream.
- **D2 -- Reuse `dm-meta` styling.** The existing 2-column key/value
  grid used for the Report section is the right pattern; same look
  for an analogous data block.
- **D3 -- Section order: Report -> Site -> Weather -> Notes.** Site
  is operator-captured plant context, sits naturally next to weather
  and notes which are also shift-context fields.
- **D4 -- Render in insertion order.** `Object.keys()` returns keys
  in insertion order; that matches whatever sequence upstream emits,
  which is the right "as-the-operator-saw-it" ordering.
- **D5 -- Label formatting.** snake_case -> "Title Case With Spaces"
  (e.g. `Loader_Operator_One` -> "Loader Operator One"). Keep the
  upstream "One/Two" wording rather than rewriting to "1/2" -- matches
  what operators see in the source system.
- **D6 -- Value formatting** consistent with the rest of the modal:
  - `null` -> em-dash
  - `"None"` (string literal) -> em-dash (per `payload-schema.md`
    Quirks: `"None"` is a placeholder, not real data)
  - `""` (empty string) -> em-dash
  - numbers -> `String(value)`
  - strings -> as-is
  - nested objects -> `JSON.stringify(value)` (defensive; Site has
    no nesting today but the schema doc warns the shape is fluid)
- **D7 -- Empty / missing Site.** If `entry.payload?.Metrics?.Site`
  is absent or has zero own-keys, render the standard `dm-empty`
  line ("No site data for this report.") matching the Weather and
  Notes empty-state pattern.

### Files to modify

- [x] `frontend/app.js` -- added `_formatSiteLabel`, `_formatSiteValue`,
      `_siteMetaRows` helpers near `_weatherCell`; inserted the
      Site section in `openDetailsModal()` between Report and Weather.
      Uses `entry.payload?.Metrics?.Site` with optional-chain-style
      guards so undefined payloads don't blow up the modal.
- [x] `frontend/app.css` -- no changes (reused `dm-section-label`,
      `dm-meta`, `dm-meta-key`, `dm-meta-value`, `dm-empty` classes
      from existing modal sections).

### Phase 11b -- Site fields in XLSX export

Per the standing rule (`memory/feedback_export_mirrors_display.md`):
**every field in the modal must also be in the export.**
Site fields added to the modal in Phase 11 must therefore become
columns in the XLSX too.

#### Decisions

- **D8 -- Column placement: append at end of row** (after `Notes`).
  Preserves existing column order so anyone with pivot tables built
  on Phase 8's column set keeps working without rebuilds.
- **D9 -- Column naming: bare formatted labels** via
  `_formatSiteLabel(key)`, e.g. "Loader Operator One". Matches the
  modal headers. No prefix (collision risk with existing columns is
  low; revisit only if upstream adds a Site field whose formatted
  label collides with an existing header like "Notes" or "Shift").
- **D10 -- Dynamic column discovery.** Gather every unique Site key
  across all entries in the current selection, preserving first-seen
  insertion order. Emit one column per discovered key. Each row gets
  a value for every discovered key; null when that specific report's
  Site lacks the key. Mirrors the modal's dynamic-by-design rendering.
- **D11 -- Value mapping**: null / undefined / "" / "None" -> truly
  blank cell (so `=COUNTA()` returns 0, `=AVERAGE()` skips). Strings
  as-is. Numbers as-is. Future nested objects -> `JSON.stringify`.
  Reuses the strOrEmpty/numOrEmpty pattern already in the export.

#### Files

- [x] `frontend/app.js` -- modified `shapeAssetRows()` to discover
      Site keys upfront and append one column per key. Added
      `_siteValueForExport(v)` helper near `numOrEmpty`/`strOrEmpty`.

#### Verification

- [ ] Export from site 101, day view: confirm five Site columns
      appear at the end of the sheet, after `Notes`.
- [ ] Open exported file in Excel: confirm `"None"` Site values are
      truly blank cells (=COUNTA returns 0; not the literal text).
- [ ] DevTools test: inject a new Site key in `_lastPayload`, click
      Export, confirm the new column appears in the output.
- [ ] Multi-shift day or month view: confirm Site columns repeat
      correctly per (workcenter, report, asset) row -- same Site
      data appears for every asset of a given report (same-shift
      pattern as Weather/Notes).

## Phase 12 -- Department name lookup + display (IMPLEMENTED 2026-04-28, browser QA pending)

### Goal

Replace `Department ID: <int>` with the department's human-readable
name in the dashboard (panel headers, history-panel headers, Trends
legends) by adding a cross-database LEFT JOIN to
`[DailyProductionEntry].[dbo].[Departments]` on every production-report
fetch. Keep both `department_id` and `department_name` in the API
response, modal, and XLSX export -- the dashboard hides the ID from
primary UI but never loses it.

### Decisions

- **D1 -- LEFT JOIN, not INNER.** A production report with no matching
  Departments row still comes back, just with `department_name=null`.
  Per Trey's Q4 the name will never be null in practice, but defensive
  LEFT JOIN protects against schema or data drift.
- **D2 -- Cross-database query.** Use fully-qualified
  `[DailyProductionEntry].[dbo].[Departments]`. Same SQL Server
  instance is assumed (Trey: "you should have access"). If a future
  separation forces a linked-server, that's a separate concern.
- **D3 -- Display column is `Name`** (Trey clarification, not `Department`
  as the original example showed). JOIN selects `d.[Name] AS DEPT_NAME`.
- **D4 -- Type tolerance for nullability.** `department_name: str | None`
  on both `ProductionReportRow` and `ProductionReportEntry` for now.
  CSV source returns `None`. Phase 13 (CSV removal) will tighten to
  `str` once CSV is gone.
- **D5 -- ID stays in the contract.** `department_id` is unchanged.
  Existing API consumers (and any pivot tables built on the export's
  "Department ID" column) keep working without modification.
- **D6 -- Display rules:**
  - Panel headers (workcenter, history): show `Department: <name>`.
    Fallback to `Department ID: <id>` if name is null.
  - Trends view legend / category axis: show `<name>` directly. Same
    null fallback.
  - Details modal: add `Department Name` row alongside the existing
    `Department ID` row. Both visible.
  - XLSX export: add a `Department` column immediately after
    `Department ID`. Doesn't disturb existing column order.
- **D7 -- CSV source kept intact for this phase.** Returns
  `department_name=None`. Phase 13 removes CSV entirely; not bundled
  here so Phase 12 can ship and be verified without simultaneous
  test-suite migration.
- **D8 -- Underscores in `Name` are normalized to spaces.** The
  upstream `Departments.[Name]` column may carry underscores
  (e.g. `North_Crusher`). The dashboard / export should read
  "North Crusher". Done once at the SQL layer via
  `REPLACE(d.[Name], '_', ' ') AS DEPT_NAME` so the transformation
  is the single source of truth and every downstream surface
  (panel headers, Trends legends, modal, XLSX export) inherits it
  for free. Consistent with the project's "export mirrors display"
  rule -- users see the same string everywhere. If a future caller
  needs the raw underscored form, we add a separate column then;
  YAGNI now.

### Files modified

- [x] `backend/app/integrations/production_report/queries/select_all.sql`
      -- added cross-database
      `LEFT JOIN [DailyProductionEntry].[dbo].[Departments] d
      ON d.[Id] = rr.DEPARTMENT_ID` and
      `REPLACE(d.[Name], '_', ' ') AS DEPT_NAME` (D8 normalization).
- [x] `backend/app/integrations/production_report/base.py` -- added
      `department_name: str | None = field(default=None)` to
      `ProductionReportRow`.
- [x] `backend/app/integrations/production_report/sql_source.py` --
      `_row_to_dataclass` reads DEPT_NAME from `row[13]` with
      defensive `str()` + None-check; updated column-order docstring.
- [x] `backend/app/integrations/production_report/csv_source.py` --
      no change required; dataclass default supplies `None` since
      `_parse_row` doesn't enumerate the optional Phase 8/12 fields.
- [x] `backend/app/schemas/production_report.py` --
      added optional `department_name` to `ProductionReportEntry`
      AND `MonthlyRollupEntry` (the Trends rollup also surfaces it).
- [x] `backend/app/api/routes/production_report.py` -- `_to_entry`
      and `_to_rollup_entry` both propagate `department_name`.
- [x] `backend/app/services/production_report.py` -- added
      `department_name` to the `MonthlyRollup` dataclass; populated
      from `group[0].department_name` (all rows in a (dept, month)
      bucket share the dept). Bundled here so Trends chart legends
      can read names, not just IDs -- avoids a separate frontend
      lookup map.
- [x] `backend/tests/integrations/test_sql_source.py` -- extended the
      `_row` tuple helper to include `dept_name`; added two new
      tests (positive read + LEFT JOIN miss); asserted on the new
      JOIN/REPLACE in `test_load_query_reads_ping_and_select_all`.
- [x] `frontend/app.js`:
  - Added `deptName` and `deptHeader` helpers near `fmt1`/`placeholderize`.
  - Single-report panel header uses `deptHeader(entry.department_name, entry.department_id)`.
  - History panel lifts the name off `entries[0]` and uses `deptHeader`.
  - Modal shows a new `Department Name` row right after `Department ID`
    (em-dash on null since the ID row above already covers identity).
  - Export inserts `Department` column right after `Department ID`,
    sourced via `strOrEmpty(entry.department_name)` so null becomes
    a truly blank cell.
  - Trends view legend uses `deptLabel(dept)` which calls `deptName`
    on the rollup entry's `department_name`.

### Verification

- [ ] `pytest` passes against the existing CSV fixtures.
- [ ] Live SQL: hit `/api/production-report/latest` against the deployed
      Linux container. Confirm every entry has a populated
      `department_name` matching `[Departments].[Name]` for that
      `DEPARTMENT_ID`.
- [ ] Dashboard: workcenter panels and history panels show the name.
      Modal shows both id and name. Export `.xlsx` has a `Department`
      column right after `Department ID`.
- [ ] Trends view: chart legend reads names, not IDs.
- [ ] Negative path (defensive): in DevTools console, mutate one
      entry's `department_name` to null, re-render, confirm the
      panel falls back to `Department ID: <id>` rather than rendering
      "Department: null".

### Out of scope (deferred to Phase 13)

- Removing the CSV source entirely (Trey approved removal but it's a
  separate refactor with its own test-suite migration).
- Tightening `department_name` from `str | None` to `str` (waits on
  CSV removal).
- Caching the Departments lookup table (the JOIN runs once per
  request and the table is small; revisit only if metrics show a
  problem).
- Multilingual or per-tenant overrides of department names.

## Phase 14 -- Manager-style monthly bar charts on the Trends tab (PLANNED)

### Goal

Extend the Trends tab with the manager's monthly bar-chart set
(`examples/production-charts/`). All data comes from the existing
production-report payload; no SCADA-side or interval-metrics work
required. Site-specific topology is read dynamically from the
`Circuit.<id>.Description` and `Circuit.<id>.Line.<id>.Description`
fields in the payload -- no frontend hard-coding of "57-1" / "Main
Circuit" / etc.

### Decisions

- **D1 -- Aggregation: simple averages.** The PDF's "Average of TPH
  Fed", "Average of Run Time %", "Average of 57-1 TPH" etc. are all
  simple means across daily reports (`mean(daily Rate)`, NOT
  `sum(Total)/sum(Runtime)`). Confirmed with Trey 2026-04-28. Can
  revisit weighted averages later as a separate metric without
  breaking the wire contract.
- **D2 -- Surface: extend the existing Trends tab, don't introduce a
  new "Management" tab yet.** Existing line charts (Total Tons by
  Workcenter, TPH by Workcenter) stay; new bar charts join them in
  the same grid. Re-evaluate tab separation after the Trends grid
  fills out -- if it gets visually crowded, the manager's bar charts
  graduate to their own tab in a future phase.
- **D3 -- Universal rendering via Description fields.** Frontend
  reads `payload.Metrics.Circuit` dynamically: top-level circuits
  render as bar groups labeled from `Description`, sub-Lines render
  as paired bars labeled from their own `Description`. No
  conveyor-membership table needed in the payload; the Line node
  already carries the aggregated Runtime + Total. A different site
  with different topology renders its own circuits/lines from its
  payload with zero frontend code change.
- **D4 -- "Total" charts compose from line-level data.** "Total 57's
  TPH" = `Line.A.tph + Line.B.tph` (sum of per-line averages, per
  the PDF). Same for "Total 57's Yield" and "Total 57's Produced".
  The backend emits per-line monthly aggregates plus per-circuit
  monthly aggregates (for the cross-line totals); the frontend
  renders whichever the chart needs.
- **D5 -- Yield definition.** `yield_per_report = Line.Total /
  Workcenter.Total`. Monthly yield = mean of per-report yields. PDF
  numbers cross-check: site 101 January, 57-1 monthly yield ≈ 0.35;
  Line A.A daily Total ≈ 1080 vs Workcenter.Total ≈ 3260 → 0.33
  per-report yield, monthly average ≈ 0.35. Close enough that this
  is the right formula.
- **D6 -- One chart panel per workcenter.** Each production-report
  payload is per-workcenter, so a single-workcenter chart matches
  the data grain naturally and matches the manager's PDF style
  (one series of bars per month, no per-dept multiplexing). Trends
  layout: existing cross-workcenter line charts stay at the top
  (Total Tons by Workcenter / TPH by Workcenter) as the
  side-by-side overview; below them, sections grouped by
  workcenter render the bar charts. Each workcenter section
  contains its own copy of the Phase 14a workcenter charts and the
  Phase 14b circuit/line charts. A workcenter with no Circuit
  hierarchy in its payload (Wash Plant likely) just shows the
  workcenter-level charts and skips the circuit panels.
- **D7 -- Fallback for Rate and Availability when null.**
  - `avg_tph_fed` per report: prefer `Workcenter.Rate`; if null,
    fall back to `Workcenter.Total / Workcenter.Runtime` when both
    are present and Runtime > 0. Else None for that report.
  - `avg_runtime_pct` per report: prefer `Workcenter.Availability`;
    if null, fall back to `min(100, Runtime / Scheduled_Runtime *
    100)` when both are present and Scheduled_Runtime > 0. Else
    None.
  - Monthly average across reports skips Nones; if every report in
    a (dept, month) bucket is None, the monthly value is None and
    the chart shows a gap for that month.

### Phase 14a -- Workcenter monthly bar charts (IMPLEMENTED 2026-04-28, browser QA pending)

Three chart panels per workcenter, added to the Trends grid in
per-workcenter sections (one section per dept):
- **Total TPH Fed** -- monthly mean of `Workcenter.Rate` (with
  fallback to `Total / Runtime` per D7). Bar chart, single series,
  one bar per month.
- **Runtime %** -- monthly mean of `Workcenter.Availability`
  (with fallback to `Runtime / Scheduled_Runtime * 100` per D7).
  Same shape.
- **Performance %** -- monthly mean of `Workcenter.Performance`,
  which equals `Rate / Ideal_Rate * 100` (OEE Performance
  Efficiency / throughput utilization vs. nameplate). No fallback
  chain -- if upstream Performance is null we drop that report
  from the mean. Bundled into 14a alongside TPH Fed and Runtime %
  so the workcenter section gives an A x P (-Q) view in one place.

#### Files to modify

- [ ] `backend/app/services/production_report.py` -- extend
      `MonthlyRollup` with `avg_tph_fed: float | None` and
      `avg_runtime_pct: float | None`. Compute in `get_monthly_rollup`
      as `mean(Workcenter.Rate for r in group if Rate is not None)`
      and `mean(Workcenter.Availability for r in group)`. None when
      no reports contribute a non-null value.
- [ ] `backend/app/schemas/production_report.py` -- add the same
      fields to `MonthlyRollupEntry` with descriptions.
- [ ] `backend/app/api/routes/production_report.py` --
      `_to_rollup_entry` propagates the new fields.
- [ ] `backend/tests/api/test_production_report.py` -- extend the
      shape-expected set in
      `test_monthly_rollup_rollup_entry_fields_present`. Add at
      least one positive test that verifies `avg_tph_fed` is the
      mean of input Rates.
- [ ] `frontend/app.js` -- two new `_renderTrendPanel(...)` calls in
      `renderTrends()`. Use `Chart.js` `bar` type. Title each panel,
      label per-bar values inline (matches the PDF style).
      Per-workcenter colors reuse `TREND_COLORS`.

#### Verification

- [ ] `pytest` passes; new tests cover the avg fields.
- [ ] Hit `/api/production-report/monthly-rollup` against fresh data
      and eyeball that `avg_tph_fed` and `avg_runtime_pct` agree
      with manual averages of Workcenter.Rate / Workcenter.Availability.
- [ ] Trends tab renders the two new bar chart panels alongside the
      existing line charts.
- [ ] Compare numbers to the manager's PDF for a known month (e.g.
      April 2026 if the data set has it).

### Phase 14b -- Circuit / Line monthly bar charts

Six chart panels powered by one new endpoint. The endpoint walks the
Circuit hierarchy across reports and emits per-(circuit, line, month)
aggregates dynamically.

#### New endpoint

`GET /api/production-report/circuit-monthly-rollup?site_id=...&from_month=YYYY-MM&to_month=YYYY-MM&department_id=...`

Response shape (dynamic per site):
```json
{
  "site_id": "101",
  "department_id": "127",
  "from_month": "2026-01",
  "to_month": "2026-04",
  "generated_at": "...",
  "circuits": [
    {
      "id": "A",
      "description": "Main Circuit",
      "monthly": [
        { "month": "2026-04", "total_tons": ..., "runtime_hours": ...,
          "avg_tph": ..., "avg_yield": ..., "report_count": 30 }
      ],
      "lines": [
        { "id": "A", "description": "57-1", "monthly": [...] },
        { "id": "B", "description": "57-2", "monthly": [...] }
      ]
    },
    { "id": "B", "description": "CR Circuit", "monthly": [...], "lines": [] }
  ]
}
```

Aggregation rules per (circuit, month) and per (circuit, line, month):
- `total_tons` = sum of `node.Total` across reports in window
- `runtime_hours` = sum of `node.Runtime` across reports
- `avg_tph` = mean of per-report `node.Total / node.Runtime` where
  `node.Runtime > 0`. None when no reports qualify.
- `avg_yield` = mean of per-report `node.Total / Workcenter.Total`
  where `Workcenter.Total > 0`. None otherwise.
- `report_count` = number of reports contributing to this bucket.

#### Six chart panels driven by the endpoint

| Chart | Data path |
|---|---|
| 57's TPH per Circuit | Circuit A's lines, paired bars by line.description, value = `line.monthly[m].avg_tph` |
| Total 57's TPH | Circuit A circuit-level, single bar, value = `circuit.monthly[m].avg_tph` (or sum of lines' avg_tph -- mathematically equivalent for the sum-of-means formulation) |
| 57's Yield | Same shape as 57's TPH per Circuit, value = `line.monthly[m].avg_yield` |
| Total 57's Yield | Same shape as Total 57's TPH, value = `circuit.monthly[m].avg_yield` |
| Total 57's Produced | Circuit A circuit-level, single bar per month, value = `circuit.monthly[m].total_tons` |
| 57's tons per circuit | Same shape as 57's TPH per Circuit, value = `line.monthly[m].total_tons` |

Frontend renders these by iterating the response's circuits and
their lines. Labels come from `description`. A site whose
`Circuit.X.Description` is "Stone Crusher" renders that label
instead of "Main Circuit" with no code change.

#### Files to add / modify

- [ ] `backend/app/services/production_report.py` -- new
      dataclasses `LineMonthly`, `CircuitMonthly`,
      `CircuitMonthlyRollup` (the response wrapper). New service
      function `get_circuit_monthly_rollup(source, *, site_id,
      from_month, to_month, department_id)` that walks each
      report's `Metrics.Circuit` tree and emits the rollup.
- [ ] `backend/app/schemas/production_report.py` -- Pydantic
      mirrors of the above with descriptions.
- [ ] `backend/app/api/routes/production_report.py` -- new route
      `/circuit-monthly-rollup`. Same parameter validation as
      `/monthly-rollup`.
- [ ] `backend/tests/api/test_production_report.py` -- 4-6 new
      tests: shape, dynamic descriptions, missing circuits, lines
      vs. no-lines circuits, yield-zero handling.
- [ ] `frontend/app.js` -- `refreshTrends` now fetches BOTH
      `monthly-rollup` and `circuit-monthly-rollup`. Renders the
      six new chart panels alongside the existing four (workcenter
      lines + 14a workcenter bars).

#### Verification

- [ ] `pytest` passes.
- [ ] Hit the new endpoint with January 2026 data; confirm avg_tph
      and avg_yield numbers match the manager's PDF for Big Canyon
      Jan-Apr 2026.
- [ ] Site 102 (synthetic): confirm the dynamic rendering doesn't
      break -- if site 102's payloads have a different `Circuit`
      shape or no `Description` fields, the dashboard either
      degrades gracefully (skip that panel for the site) or renders
      the bars labeled by the raw `Circuit` keys (`A`, `B`).
- [ ] Theme toggle light/dark works for all new panels.

### Phase 14c -- Conveyor product-grouped comparison (DEFERRED)

Compare conveyors that ran the same product over the window. Group
by `Produced_Item_Code`, render paired bars per conveyor.

Lower priority; the Phase 14b line-level charts already give the
production-management view. Plan in detail when 14a/b ship.

### Phase 14d -- Wash Plant TPH by Shift (DEFERRED)

Wash plant is a separate department_id at site 101. Same machinery
as Phase 14a (avg of Workcenter.Rate per month) but grouped by
`(department_id, shift, month)`. Requires confirming the wash plant
emits production reports through `[UNS].[SITE_PRODUCTION_RUN_REPORTS]`
with `entry.shift` populated via the Phase 8 history join.

### Out of scope (entire Phase 14)

- Time-weighted averages instead of simple averages (D1 explicitly
  defers; can add as a separate metric later).
- A "Management" tab separate from Trends (D2 explicitly defers).
- Adding conveyor-to-line membership at the payload level (D3
  explicitly avoids; line-level metrics are already in the Circuit
  hierarchy).
- Backfilling historical data with the new payload field set --
  assumes upstream data is already populating Workcenter.Rate /
  Availability / Total / Scheduled_Runtime as documented in the
  payload schema.

## Phase 13 -- Remove CSV as a production source (IMPLEMENTED 2026-04-28, browser QA pending)

### Goal

Remove CSV from the production code path. SQL becomes the only
configured production-report source going forward; APIs (Flow) remain
the metric source as before. The 28+ tests that currently use the
CSV-backed `client` fixture continue to work -- CSV becomes
test-fixture infrastructure rather than a production option.

### Decisions

- **D1 -- Production-only removal.** `CsvProductionReportSource` is
  dropped from production wiring (Settings, DI, lifespan, package
  exports) but the file stays under
  `backend/app/integrations/production_report/csv_source.py` with a
  prominent `TEST-ONLY -- not registered in production` banner. The
  `tests/conftest.py` `client` fixture imports it directly (not via
  `__init__`) and uses it as a deterministic fixture-backed source.
  Migrating the 28+ tests to mocked SQL would be ~10x more work for
  no production-side benefit.
- **D2 -- `department_name` tightens to non-null `str`.** Trey
  confirmed "name will never be null." With CSV gone from production,
  every row goes through SQL. SQL source synthesizes a `f"Dept {id}"`
  fallback (and logs a warning) on the rare LEFT JOIN miss so we
  never raise a ValidationError on a real production response.
  Pydantic models drop the `| None` on department_name. Frontend
  fallbacks remain as defense-in-depth (cheap, harmless).
- **D3 -- Settings simplification.** Remove
  `production_report_backend`, `production_report_csv_path`, and
  `_DEFAULT_CSV_PATH` from `core/config.py`. `db_conn_string` becomes
  required (no default of `None`); startup fails fast if it's missing
  rather than degrading to CSV.
- **D4 -- sample.csv stays under `context/sample-data/`.** It's the
  test fixture and conceptually paired with `payload-schema.md` /
  `payload-example.json` which document the canonical PAYLOAD shape.
  Moving it would ripple through doc references for no real win.
  The Dockerfile still COPYs `context/` so the docs ship in the
  image; the `.dockerignore` could exclude `sample.csv` specifically
  to keep the image lean (small saving, optional).
- **D5 -- Historical docs are not rewritten.** `tasks/decisions/*`,
  `tasks/specs/*`, prior `tasks/todo.md` entries, and `lessons.md`
  are records of decisions made at the time. They keep mentioning
  CSV. Only current-state docs (CLAUDE.md, RUNBOOK.md, ARCHITECTURE.md,
  PAYLOAD-CONTRACT.md, docs/*, README.mds, backend/.env.example,
  session-*-prompt.md) are updated to reflect SQL-only.
- **D6 -- Health endpoint name unchanged.** SqlProductionReportSource's
  `name` stays `"sql:production_report"`. Tests using the CSV fixture
  still see `"csv:production_report"` in their fixture context --
  that's expected, the test isn't running against the production
  source.

### Files to delete
- [ ] `backend/tests/integrations/test_csv_source.py` -- 5 tests that
      verified `CsvProductionReportSource` behavior in isolation. No
      production value once CSV is non-production; the fixture is
      exercised end-to-end by every API test that uses `client`.

### Files to modify

#### Backend production code

- [ ] `backend/app/core/config.py` -- remove `_DEFAULT_CSV_PATH`,
      `production_report_csv_path`, `production_report_backend`.
      `db_conn_string` becomes `SecretStr` (no default `None`).
- [ ] `backend/app/api/dependencies.py` -- collapse
      `get_production_report_source` to a single SQL path. No
      conditional branching, no Settings read. Import-list cleaned.
- [ ] `backend/app/main.py` -- lifespan unconditionally creates the
      SQL pool. Remove the `if backend == 'sql'` gate. Update
      structlog event names if needed.
- [ ] `backend/app/integrations/production_report/__init__.py` --
      remove `CsvProductionReportSource` from `__all__`/exports.
- [ ] `backend/app/integrations/production_report/base.py` -- tighten
      `department_name` field on `ProductionReportRow` to `str` (no
      `| None`); update docstring.
- [ ] `backend/app/integrations/production_report/sql_source.py` --
      `_row_to_dataclass` synthesizes `f"Dept {id}"` and logs a
      warning when DEPT_NAME column is NULL (LEFT JOIN miss).
      Tighten field via the dataclass constraint.
- [ ] `backend/app/schemas/production_report.py` -- tighten
      `department_name` on `ProductionReportEntry` AND
      `MonthlyRollupEntry` to non-null `str`. Update docstrings.
- [ ] `backend/app/integrations/production_report/csv_source.py` --
      add `# TEST-ONLY -- not registered in production` banner.
      Module docstring updated. Class behavior unchanged.
- [ ] `backend/.env.example` -- remove `PMD_PRODUCTION_REPORT_BACKEND`
      and `PMD_PRODUCTION_REPORT_CSV_PATH` lines. Mark
      `DB_CONN_STRING` as required.

#### Tests
- [ ] `backend/tests/conftest.py` -- update fixture docstring to
      clarify CSV is test-only fixture data, not a production source.
      Keep the import + override pattern.
- [ ] `backend/tests/api/test_health.py` -- audit for hardcoded
      `production_report_backend` assertions; update.
- [ ] `backend/tests/services/test_conveyor_totals.py` -- audit
      (currently constructs `ProductionReportRow` directly).
- [ ] Audit other test files surfaced in the grep
      (`test_metrics.py`, `test_metrics_sql_source.py`,
      `test_sql_source.py`) for explicit CSV references; update.
- [ ] After tighten of `department_name` to `str`, tests that
      construct `ProductionReportRow` without that field will need
      updating (or we keep the dataclass default to a synthesized
      sentinel and surface that as a test-only quirk).

#### Frontend
- [ ] `frontend/app.js` -- one comment update at line 1585
      (`CSV path or pre-Phase-12 server` -> `defensive fallback`).
      No behavior change.

#### Documentation (current-state only)
- [ ] `CLAUDE.md` -- remove "CSV" from Tech Stack and Architecture
      sections. Update "When in Doubt" if it mentions CSV.
- [ ] `RUNBOOK.md` -- remove the CSV-source setup section and any
      references in troubleshooting / config tables.
- [ ] `ARCHITECTURE.md` (root) -- remove CSV path from data-flow
      diagrams and source-layer descriptions.
- [ ] `backend/ARCHITECTURE.md` -- remove CSV path from source
      abstraction discussion.
- [ ] `PAYLOAD-CONTRACT.md` -- review (likely just one mention).
- [ ] `docs/data-flows.md` -- remove CSV path.
- [ ] `docs/server-deployment.md` -- remove
      `PMD_PRODUCTION_REPORT_BACKEND` from the `.env` config example.
- [ ] `backend/README.md` -- remove CSV setup.
- [ ] `context/sample-data/production-report/README.md` -- update
      to "test fixture data" framing.
- [ ] `session-starter-prompt.md` -- review.

### Verification

- [ ] `pytest` passes (expect 100 tests after deleting the 5 CSV-source
      isolation tests).
- [ ] App starts without `PMD_PRODUCTION_REPORT_BACKEND` set in env.
- [ ] App fails fast (clear error) when `DB_CONN_STRING` is missing.
- [ ] `/api/health` reports `sql:production_report` against a real
      backend.
- [ ] `/api/production-report/latest` returns `department_name` as
      a `str` (never `null`) in production response.
- [ ] LEFT JOIN miss path: synthesize a row whose `DEPARTMENT_ID`
      doesn't exist in `Departments`, hit `/latest`, confirm response
      has `department_name="Dept <id>"` and a warning was logged.
- [ ] `grep -ri csv backend/app/` returns nothing except the
      TEST-ONLY banner inside csv_source.py.
- [ ] `grep -ri csv` against current-state docs returns nothing.

### Out of scope
- Migrating the API test suite to mocked SQL fixtures (substantial
  test rewrite; low ROI given CSV is now non-production).
- Removing `context/sample-data/` entirely.
- Adding auth, rate limits, or other unrelated production-readiness
  improvements.

### Phase 11.1 -- Group Site fields by base type (IMPLEMENTED 2026-04-28)

Upstream emits Site keys interleaved by ordinal
(`Loader_Operator_One`, `Shot_Number_One`, `Loader_Operator_Two`, ...)
which makes the modal hard to scan. Grouped by prefix instead so all
loader operators sit together, then all shot numbers, etc.

Helper added: `_sortSiteKeys(keys)` detects trailing `_One`.."_Ten"
or pure-digit `_1`/`_2` suffixes, groups by prefix in first-seen
order, sorts by ordinal within each group. Keys with no ordinal
remain in their first-seen position as single-member groups.

- [x] `_sortSiteKeys`, `_parseSiteOrdinal`, `_ORDINAL_WORDS` added
      near `_formatSiteLabel`.
- [x] `_siteMetaRows` (modal) wraps `Object.keys()` in `_sortSiteKeys`.
- [x] `shapeAssetRows` (export) wraps the discovered key list in
      `_sortSiteKeys` so column order matches modal order.

Modal and export stay in sync because both go through the same sort.

### Verification

- [ ] Day view, latest report on site 101: open Details modal and
      confirm all five sample-payload Site keys render with formatted
      labels.
- [ ] Same report: confirm `Shot_Number_One: "None"` displays as
      em-dash, not the literal string `"None"`.
- [ ] Site 102 (synthetic, may have no/sparse Site data): confirm
      empty-state path renders without a console error.
- [ ] Simulate a future schema change in DevTools console:
      `_lastPayload.entries[0].payload.Metrics.Site.New_Field = "test"`
      then re-open the modal -> confirm the new key renders with no
      code change. (Validates D1 / D4 / D5.)
- [ ] Theme toggle light/dark: confirm the new section respects
      existing `dm-meta` styling without color drift.

### Out of scope

- Backend changes -- none needed; payload already passes through.
- Pydantic typing of Site -- explicitly deferred per D1.
- Per-field tooltips / help text -- operators recognize these
  field names from the source system.
- Surfacing Site fields anywhere other than the modal (e.g. as
  separate columns in the table or the XLSX export). Out of scope
  unless explicitly requested -- the table is already wide and
  the export columns are stable.
      on tph when runtime is 0.
- [ ] `backend/app/main.py` -- bump `BUILD_TAG`.

Endpoint shape:

```
GET /api/production-report/monthly-rollup
        ?site_id=101                  [required]
        &from_month=2026-01           [required, YYYY-MM]
        &to_month=2026-04             [required, YYYY-MM]
        &department_id=127            [optional]

  → MonthlyRollupResponse {
      site_id, from_month, to_month, generated_at,
      rollups: [
        {
          department_id, month (YYYY-MM),
          total_tons, total_runtime_minutes, tph, report_count
        }, ...
      ]
    }
```

### Phase 10b -- Frontend trends view

Files to modify (frontend-only; no backend changes):

- [ ] `frontend/index.html` -- tab strip in the topbar
      (Dashboard / Trends), hash-router scaffolding, trends-view
      DOM container.
- [ ] `frontend/app.css` -- tab styles, trends layout (chart-grid,
      month-range picker, multi-line legend).
- [ ] `frontend/app.js` -- hash-routed view switcher, month-range
      pickers (from-year, from-month, to-year, to-month), trends-
      view fetch + render with Chart.js line charts. Two charts in
      first cut: Total Tons per Workcenter by Month, TPH per
      Workcenter by Month.

### Phase 10c -- Future metrics (after 10a + 10b ship)

- [ ] Availability average per workcenter by month.
- [ ] Performance average per workcenter by month.
- [ ] Product-specific cuts (e.g. #57 only): adds product filter
      to the rollup service + new chart variants.

### Future migration to Flow-sourced monthly metrics

When Flow is configured to publish monthly aggregates (Total,
Runtime, etc.) for the conveyor measures we care about, the
internal data path inside `get_monthly_rollup()` swaps from
`source.fetch_rows()` (production reports) to
`metric_source.fetch_points(interval='monthly')`. The Pydantic
response shape doesn't change; the frontend doesn't notice. The
service likely persists for context-tied cuts (per-product,
per-operator) that interval metrics can't express.

### Verification matrix

- [ ] `pytest` green, including the new monthly-rollup tests.
- [ ] `/api/__ping` shows the new BUILD_TAG.
- [ ] `/api/production-report/monthly-rollup?site_id=101&from_month=2026-01&to_month=2026-04`
      returns rollups against live SQL.
- [ ] Trends tab renders multi-line charts with months on X axis;
      switching back to Dashboard tab restores existing UI.
- [ ] Hash routes survive page refresh (`#trends` stays on trends).
- [ ] Theme toggle + site selector affect both tabs consistently.

### Implementation progress (2026-04-27)

Both halves landed: backend monthly-rollup endpoint and frontend
trends view with Chart.js line charts. py_compile + node --check
clean. New tests cover the new endpoint end-to-end via the existing
TestClient + sample-CSV fixture; no real SQL required for tests.

**Phase 10a -- Backend (done):**

- [x] `backend/app/schemas/production_report.py` -- added
      `MonthlyRollupEntry` and `MonthlyRollupResponse` Pydantic
      models. Documented field-by-field including the null-tph
      contract for zero-runtime months.
- [x] `backend/app/services/production_report.py` -- added
      `MonthlyRollup` frozen dataclass and `get_monthly_rollup()`
      service function. Reuses Phase 5's `compute_conveyor_totals`
      for tonnage; runtime aggregated via a small
      `_runtime_minutes_from_workcenter` helper that mirrors the
      dashboard's `Runtime` / `Actual_Runtime_Hours * 60` fallback.
      tph computed only when runtime > 0; null otherwise.
- [x] `backend/app/api/routes/production_report.py` -- added
      `/monthly-rollup` route with `from_month` / `to_month` as
      YYYY-MM strings. Validates format, ordering, and a
      37-month cap. Returns 422 with descriptive details on bad
      input. Internal helpers (`_parse_month_string`,
      `_last_day_of_month`, `_months_between`, `_to_rollup_entry`)
      live alongside.
- [x] `backend/app/main.py` -- BUILD_TAG bumped to
      `2026-04-27-phase10-trends`.
- [x] `backend/tests/api/test_production_report.py` -- 8 new tests:
      envelope shape, entry-fields-present, dept-filter, inverted
      window 422, malformed YYYY-MM 422, oversized window 422,
      unknown-site empty result, divide-by-zero guard for tph.

**Phase 10b -- Frontend (done):**

- [x] `frontend/index.html` -- view-tabs strip (Dashboard / Trends)
      in the topbar after the site selector. New `#dashboard-view`
      and `#trends-view` canvas containers; existing dashboard UI
      moved verbatim under `#dashboard-view`. New trends-view
      structure with from-month / to-month native `<input
      type="month">` controls and a `#trends-grid` for the chart
      panels.
- [x] `frontend/app.css` -- `.view-tabs` + `.vtab` styles matching
      the existing topbar button vocabulary; `.trends-main`,
      `.trends-controls`, `.trends-grid`, `.trend-panel`,
      `.trend-chart-wrap`, `.trend-chart-canvas` styles. Trend
      panels reuse the card surface conventions; charts get a
      fixed 260px height (line charts read better at that ratio
      than the conveyor bar chart's 180px).
- [x] `frontend/app.js` -- new module state (`currentView`,
      `_trendChartInstances`, `_lastTrendsPayload`); new helpers
      `wireViewTabs`, `applyViewFromHash`, `populateTrendsRangeDefaults`,
      `wireTrendsControls`, `_trendsRange`, `refreshTrends`,
      `renderTrends`, `_renderTrendPanel`, `_destroyTrendCharts`,
      `_showTrendsError`, `_clearTrendsError`. Hash-routed:
      `#dashboard` (default) / `#trends`. Site-toggle and
      theme-toggle now refresh whichever view is active. Default
      trends range = last 12 months. Two charts on first cut:
      Total Tons and TPH, multi-line by department.

**Verification (programmatic):**

- [x] All backend files py_compile clean.
- [x] `node --check` clean on `app.js` (62 KB).
- [x] Tests added: total backend test count ~103 (95 prior + 8 new).
- [x] No orphan references; all new symbols wired through to
      bootstrap.

**Pending (Trey's host):**

- [ ] `pytest backend/` reports ~103 passing.
- [ ] `/api/__ping` shows `build_tag: "2026-04-27-phase10-trends"`.
- [ ] `/api/production-report/monthly-rollup?site_id=101&from_month=2025-05&to_month=2026-04`
      returns rollups against live SQL with sane numbers.
- [ ] Browser dashboard tab still works exactly as before.
- [ ] Browser hash-route to `#trends` shows the trends view.
- [ ] Default range is "last 12 months"; charts populate.
- [ ] Switching from-month / to-month auto-fetches and re-renders.
- [ ] Site change in the topbar refreshes both views.
- [ ] Theme toggle updates trends chart colors immediately.
- [ ] Hash refresh: reload page on `#trends` lands on trends view.
- [ ] Page-load with no hash defaults to dashboard view.

**Deliberate choices:**

- Export button hidden on the Trends tab (no XLSX-of-trends today;
  visible only on Dashboard).
- Polling continues (still 30s when applicable on the dashboard
  selection); trends data refreshes on user action only -- no
  polling overhead on the trends side.
- Auto-refresh on month-input change (no Apply button) -- matches
  the dashboard's day/month picker which also auto-applies.
- Default range = rolling last 12 months (vs. YTD). Decided from
  the design conversation -- the "trend over time" framing implies
  rolling history.
- One chart with multiple workcenter lines (vs. one chart per
  workcenter). Easier comparison; revisit if a site has >8
  workcenters and the legend gets crowded.

**Next steps when you're ready (Phase 10c):**

- Availability avg per workcenter per month (unweighted average
  across reports in that month).
- Performance avg per workcenter per month.
- Product-specific cuts (e.g. "#57 only") -- adds product filter
  to the rollup service plus new chart variants.
- Future migration to Flow-sourced monthly metrics, per the design
  conversation -- the wire contract stays stable; only the
  service's internal data path swaps.

## Lessons captured

See `tasks/lessons.md`:
- Verify the server is running your latest code (build-tag fingerprinting, zombie-socket recovery on Windows)
- Edit-tool truncation on the Windows mount — prefer bash heredoc rewrites (bit us again in Phase 4 on `tasks/todo.md`)
- Never paste real credentials into `.env.example` (rotate immediately if it happens)
- ODBC connection strings: single braces around Driver value; `Server=tcp:...,1433` prefix for Azure Managed SQL

## Deferred (non-goals still holding)

- Pydantic models of the payload internals (upstream shape still stabilizing)
- External REST / Ignition integrations (blocked on curated sample data)
- Authentication (Windows Integrated Auth on the roadmap)
- Redis / multi-worker concerns beyond the interface
- Retry / circuit-breaker logic
- React / bundlers / Node in the build chain
- Charts (Chart.js loaded but unused; obvious next step now that `/history` returns time-series-shaped data)
- Production deployment productionization — `docker-compose.override.yml`
  split (dev bind mounts separated from prod config), reverse-proxy
  choice (IIS most likely, given Windows Server env), image registry
  decision, `.env` provisioning runbook for prod hosts. Backlog as of
  2026-04-23 at Trey's call; revisit when a prod deploy target exists.
- Response caching via the `SnapshotStore` Protocol (flagged as a real load risk before wide rollout)

## Review

Phases 1 + 2 + 2.1 + 3 + 4 complete. 30/30 tests passing in the venv
path; container verified end-to-end against live Azure Managed SQL.
The Protocol-based source boundary made the CSV→SQL swap a pure config
change with zero route or service modifications; adding the Docker
path on top required zero app-code changes at all — the Dockerfile
just mirrored the repo layout at `/app/` so `core/config.py`'s path
logic resolved identically.

Next candidates (ordered by load-bearing first):
1. Response caching via the `SnapshotStore` Protocol — real load risk
   before wide rollout; infrastructure already shipped as a seam.
2. Multi-source spec draft — non-blocking prep work for the
   conveyor-tons / shiftly-metrics integration while Trey waits on
   curated sample data.
3. Charts — Chart.js already loaded but unused; `/history` returns
   time-series-shaped data ready to render.
4. Windows Integrated Auth / deployment hardening — needed before
   wider access 