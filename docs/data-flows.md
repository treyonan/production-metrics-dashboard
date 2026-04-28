# Data flows — production-metrics-dashboard

This document is a single-page explainer of how data moves through the
production-metrics-dashboard system. It walks each upstream domain
from *where the data lives* through *what our API does with it* to
*how a consumer asks for it*. The audience is a technical reader who
needs to understand the system end-to-end — a new engineer joining the
team, an Ignition developer integrating against the API, an analyst
writing an ad-hoc Excel report, or a DBA evaluating a schema change.

Two unrelated upstream domains feed the same FastAPI surface:

- **Production reports** -- end-of-shift OEE summaries per workcenter.
  Implemented and live (Phase 1-8).
- **Interval metrics** -- hourly / daily / shiftly time-series
  telemetry. Design locked, implementation pending sample data.

They share the source-Protocol pattern from `tasks/decisions/
001-stack-and-source-boundary.md` but otherwise have nothing in
common: different cadences, different upstream stores, different
caching strategies, different consumers. Routes for one never bleed
into routes for the other -- production-report endpoints sit under
`/api/production-report/*`, interval-metric endpoints under
`/api/metrics/*`. That separation is deliberate; consumers ask each
domain its own question and don't pay for overlap.

The dashboard is *one* consumer of this API. Other consumers are
anticipated -- Ignition Vision and Perspective windows for
ad-hoc charts and tables, scheduled Excel reports, future automation
on top of either domain. Endpoints are designed to be agnostic of the
consumer; the dashboard is not privileged over Ignition or any other
caller.

## Domain 1 — Production Reports

### What this is

Curated end-of-shift OEE records, one row per workcenter per
production run. Each row carries Availability / Performance / Total
tons / Runtime for the workcenter, plus a JSON `PAYLOAD` blob holding
per-asset (conveyor / crusher / screen) sub-metrics, plus enrichment
fields for shift, weather, and operator notes.

These are *summary* records, not real-time telemetry. They post once
a shift completes -- typically end-of-day or end-of-shift -- so any
"current" view is at most as fresh as the most-recent finished shift.
The dashboard's day picker defaults to the newest day with data via
`/api/production-report/latest-date` to sidestep the "Today is empty"
problem that follows from this cadence (see
`tasks/decisions/002-absolute-time-filter.md`).

### Where the data lives

Microsoft SQL Server (Azure Managed Instance). Database
`IA_ENTERPRISE`, schema `[UNS]`, three tables joined on `PROD_ID`:

| Table | Role | Join type |
|---|---|---|
| `[UNS].[SITE_PRODUCTION_RUN_REPORTS]` | Base. One row per production run; the `PAYLOAD` JSON column holds per-asset metrics. | Authoritative |
| `[UNS].[SITE_PRODUCTION_RUN_HISTORY]` | Per-shift envelope -- shift identifier and aggregated weather (`WEATHER_CONDITIONS`, `AVG_TEMP`, `AVG_HUMIDITY`, `MAX_WIND_SPEED`). | LEFT JOIN |
| `[UNS].[SITE_PRODUCTION_RUN_COMMENTS]` | Free-form notes per production run. | LEFT JOIN |

A canonical stored procedure `[UNS].[GET_PRODUCTION_RUN_REPORTS]`
joins the same three tables for other internal consumers. Our query
file `backend/app/integrations/production_report/queries/select_all.sql`
replicates that join shape rather than `EXEC`-ing the SP -- the SP
takes a mandatory `@WORKCENTER` parameter that would force N
round-trips per `/range` request, and its `SELECT` list is missing
columns we need (`ID`, `SITE_ID`, `DEPARTMENT_ID`, `DTM`).
`tasks/decisions/003-enrichment-joins.md` records the trade-off
in full. The top of `select_all.sql` names the SP as the canonical
reference so future maintainers know where to check for drift.

The `PAYLOAD` column is opaque from a SQL perspective -- the dashboard
treats it as data, not structure -- but its inner shape is documented
in `PAYLOAD-CONTRACT.md` (the canonical-fields-plus-shape-probe
contract) and `context/sample-data/production-report/payload-schema.md`
(field-by-field walk).

### How our API gets it

The source-Protocol layer (`integrations/production_report/base.py`)
defines a `ProductionReportSource` Protocol with one production
implementation:

- `SqlProductionReportSource` -- reads via `aioodbc` against a
  connection pool created at lifespan startup. The pool is shared
  with the interval-metrics tag registry on the same database.

A test-only fixture-backed implementation (`tests/_fixtures/csv_source.py`)
also satisfies the Protocol so the API test suite can run without a
SQL Server connection. Production never sees the test fixture.

The implementation emits a `ProductionReportRow` frozen dataclass
(14 fields as of Phase 12). Routes and services call the Protocol;
they never know which implementation produced the rows. Swapping in
a future source (a different vendor's REST API, etc.) is a
configuration change at the DI provider, not a consumer-side change.

The service layer (`services/production_report.py`) wraps the source:

- `get_range(source, from_date, to_date, site_id)` -- filters rows
  by site + an inclusive calendar-date window, sorts newest-first.
  Pure Python predicate -- works on whatever `fetch_rows()` returned,
  indifferent to which Protocol implementation produced the rows.
- `get_latest_per_workcenter(source, site_id)` -- reduces to one
  row per `(site_id, department_id)`, latest `prod_date` wins.
- `get_latest_date(source, site_id)` -- returns the newest
  `prod_date.date()` for a site, or `None` if the site has no
  reports.
- `compute_conveyor_totals(rows)` -- aggregates belt-scaled
  conveyor tonnage per workcenter (Phase 5).

Routes (`api/routes/production_report.py`) are thin: validate query
parameters via Pydantic, call exactly one service function, wrap
the result in a Pydantic response model. No SQL, no business logic,
no aggregation in the route layer.

Caching: not yet wired. The `SnapshotStore` Protocol is shipped as a
seam in `core/snapshot.py` for future use; today, every request hits
the source. At the dashboard's polling rate (30s) and current data
volume (~125 rows total in the sample), this is fine.

### How consumers ask for it

Three endpoints under `/api/production-report/*`:

- **`GET /api/production-report/latest?site_id=<optional>`** --
  one row per `(site_id, department_id)`, the newest by
  `(prod_date, dtm)`. Used by integrations that want "what's the
  current state of every workcenter, regardless of date."
- **`GET /api/production-report/range?from_date=YYYY-MM-DD&to_date=YYYY-MM-DD&site_id=<optional>`**
  -- every row whose `prod_date.date()` falls in the inclusive
  window. Bounds required; max window 400 days. This is what the
  dashboard hits for both day and month views.
- **`GET /api/production-report/latest-date?site_id=<required>`** --
  one calendar date or null. Single-purpose: lets the frontend
  default the day picker to the newest day that actually has data.

Each response is a Pydantic envelope (see `backend/ARCHITECTURE.md`
§6 for the field tables). Two envelope features worth knowing:

- `entries[]` is a flat list, sorted newest-first. Multiple entries
  per `(site_id, department_id)` are expected on `/range` when the
  window covers multiple shifts; consumer groups client-side.
- `conveyor_totals` (object keyed by `"<site_id>:<department_id>"`)
  is the per-workcenter belt-scaled tonnage aggregate. Always
  computed from the same rows that populated `entries`, so the
  numbers track whatever window the consumer requested.

### Things to know

- **Date handling is naive UTC.** `prod_date` is a naive
  `datetime`; we treat it as UTC for filtering. A future
  multi-timezone deployment would need explicit handling.
- **Multiple comments per `PROD_ID` would duplicate rows.** The
  comments LEFT JOIN assumes one row per report. If your operations
  ever permit multiple comment rows per production run, the dashboard
  will show inflated counts and tonnage; the fix is a `STRING_AGG`
  or `OUTER APPLY (TOP 1)` pattern in `select_all.sql`.
- **`/history?days=N` was removed in Phase 7.** Callers that used to
  fetch a rolling N-day window now build `from_date = today - (N-1)`,
  `to_date = today` and call `/range`.
- **Unknown weather phrasings degrade to text-only.** The dashboard's
  severity-ranked icon picker handles known OpenWeatherMap-style
  conditions ("clear sky", "broken clouds", "light rain", etc.). New
  phrasings log a `console.warn` once per unique string and fall
  back to no icon. Maintainers extend `WEATHER_SEVERITY` in
  `app.js` when they see one.

## Domain 2 — Interval Metrics

**Status:** design locked, implementation pending sample data.
Section reads forward-looking. Once shipped, this becomes
descriptive (the "Planned" tag below comes off).

### What this is

Time-series telemetry from process tags -- hourly / daily / shiftly
buckets of values like belt tonnage, equipment runtime, motor amps,
ambient temperature. Distinct from production reports in every
operational dimension:

| Aspect | Production reports | Interval metrics |
|---|---|---|
| Cadence | Once per shift | Continuous; bucket size varies |
| Shape | Curated summary + opaque payload | Flat: subject + metric + bucket + value |
| Producer | Operator + plant logic | Process tags via SCADA / Flow |
| Use cases | OEE, shift comparison, weather correlation | Trending, equipment health, alarms, environmental |
| Polling cadence consumers want | 1-5 min (cheap; data updates rarely) | 5-30 min (cheaper; append-only buckets) |

### Where the data lives

The architecture is a three-stop relay:

1. **Vendor remote SQL server (write side, source of truth).** The
   process historian software stores time-series buckets in its own
   database on a remote server. We don't query this directly --
   doing so couples us to a vendor's internal schema, takes read
   load against a production write database, and may violate
   vendor support agreements.

2. **Vendor REST API (read side, our access point).** The same
   software exposes a REST endpoint per metric for retrieving
   historical buckets. Each metric has a stable URL created when
   the metric is provisioned in our data ops platform (Flow). Given
   a URL, we get a JSON response of `{bucket_start, bucket_end,
   value}` rows for a date range.

3. **Enterprise MQTT broker → Ignition tag change script →
   `[FLOW].[INTERVAL_METRIC_TAGS]` table on enterprise SQL.** The
   discovery / lookup step. Flow publishes each metric's value to
   the enterprise MQTT broker on every change; the payload includes
   the metric's static history URL. An Ignition tag change script
   subscribes to those publishes and `MERGE`s into a tag table on
   our enterprise SQL server. The table is the API's source of
   truth for "what tags exist + where to fetch their history."

```
       ┌──────────────────────────────────────────────┐
       │ Flow (Data Ops platform)                     │
       │   provisions metric    → static history URL  │
       └──────────────┬───────────────────────────────┘
                      │ publishes value + URL on change
                      ▼
       ┌──────────────────────────────────────────────┐
       │ Enterprise MQTT broker                       │
       └──────────────┬───────────────────────────────┘
                      │ subscribed by Ignition
                      ▼
       ┌──────────────────────────────────────────────┐
       │ Ignition tag change script                   │
       │   MERGEs (asset, metric, interval, url)      │
       │   into [FLOW].[INTERVAL_METRIC_TAGS]          │
       └──────────────┬───────────────────────────────┘
                      │ SELECT
                      ▼
       ┌──────────────────────────────────────────────┐
       │ Our FastAPI -- reads tag table               │
       │   then httpx-fetches per-tag URL             │
       │   from the vendor REST API                   │
       └──────────────────────────────────────────────┘
```

The API never holds an MQTT subscription. Discovery happens in the
SCADA layer, where it operationally belongs; our code just reads a
stable SQL table.

### `[FLOW].[INTERVAL_METRIC_TAGS]` schema

```sql
-- Idempotent setup. Safe to run multiple times -- creates the FLOW
-- schema if it doesn't already exist, then the table.

-- CREATE SCHEMA must be alone in a batch in SQL Server; EXEC keeps
-- the IF NOT EXISTS guard intact.
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'FLOW')
    EXEC('CREATE SCHEMA [FLOW]');
GO

IF OBJECT_ID('[FLOW].[INTERVAL_METRIC_TAGS]', 'U') IS NULL
BEGIN
    CREATE TABLE [FLOW].[INTERVAL_METRIC_TAGS] (
        site_id        INT          NOT NULL,
        asset          VARCHAR(64)  NOT NULL,    -- 'C4', 'CR1', 'WC_127'
        metric_name    VARCHAR(64)  NOT NULL,    -- 'tons', 'runtime', 'amps'
        interval       VARCHAR(16)  NOT NULL,    -- 'hourly', 'daily', 'shiftly'
        history_url    NVARCHAR(512) NOT NULL,
        department_id  INT          NULL,        -- nullable for site-level tags
        subject_type   VARCHAR(32)  NOT NULL DEFAULT 'conveyor',
        enabled        BIT          NOT NULL DEFAULT 1,
        DTM            DATETIME2    NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_INTERVAL_METRIC_TAGS
          PRIMARY KEY (site_id, asset, metric_name, interval)
    );
END;
GO
```

Notes:

- **Primary key** is `(site_id, asset, metric_name, interval)`. A
  single asset publishes multiple metrics, and a metric may be
  bucketed at multiple intervals (e.g. hourly tons *and* daily tons
  for the same conveyor); each combination gets its own row.
- **`DTM`** doubles as a freshness signal -- it gets bumped on
  every `MERGE`, which (since the trigger fires on every value
  publish) means it tracks "when this tag last reported." A `DTM`
  several hours stale on an hourly tag tells the dashboard the tag
  has gone quiet.
- **`enabled = 0`** soft-deletes a tag. The API filters
  `WHERE enabled = 1` so a decommissioned tag stops appearing
  without losing history of "this tag once existed."
- **`subject_type`** lets future endpoints under
  `/api/metrics/equipment/...` or `/api/metrics/site/...` filter
  to their domain without parsing asset names.

### Two payload profiles, one mapping rule

Flow publishes the *same physical measure* in two different MQTT
payload profiles depending on whether the metric is being aggregated
over an event window or reported on calendar-aligned buckets. Knowing
which is which is critical for writing the right `interval` value
into `[FLOW].[INTERVAL_METRIC_TAGS]`.

**`measure.intervalType` is misleading.** It describes the underlying
source tag's cadence, not the published aggregation regime. A metric
whose source tag is sampled hourly but is SUM-aggregated over a shift
event still reports `intervalType="Hourly"` -- writing that to our
table would lie to consumers (they'd ask for hourly data and get
shift-level aggregates).

**The truthful signal is the structural shape of the payload.** Two
profiles, distinguishable by which envelope object is present:

| Profile | Top-level identifier | Window field | What "value" means |
|---|---|---|---|
| Event-aggregated | `eventPeriod` + `eventScheme` | `eventPeriod` (start/end define the event window) | One value summarising the whole event window |
| Calendar-aligned | `timePeriod` (no `eventPeriod`) | `timePeriod` (start/end define a calendar bucket) | One value for that bucket |

Decision rule used by the Ignition trigger
(`scada/ignition/upsert_interval_metric_tag.py::_determine_interval`):

1. If `payload["eventPeriod"]` exists -> `interval = "shiftly"`.
2. If `payload["timePeriod"]` exists -> `interval = "hourly"`.
3. Neither -> raise. Logged in the gateway; nothing is written to
   the table.

**Site policy assumption.** The only calendar interval Flow publishes
at this site is hourly; anything finer-grained or coarser is
expressed as an event-aggregated metric instead. The simplified rule
above relies on that policy. If you ever see Flow publishing a
non-hourly `timePeriod` payload (a daily calendar bucket, a
fifteen-minute calendar bucket, etc.), the rule needs to grow a
duration check via `values[0]["duration"]` (ms): 3600000 = hourly,
60000 = every_minute, 86400000 = daily, etc. Today there's no need
for that branch.

Sample payloads of each profile live alongside the script:

- `context/sample-data/interval-metrics/mqtt-payload-example-shiftly.json`
  -- event-aggregated; the C4 belt-scale total summed over a 9h 43m
  shift event (single value of 136.625 tons).
- `context/sample-data/interval-metrics/mqtt-payload-example-hourly.json`
  -- calendar-aligned; the same C4 measure but reported as a 1h
  bucket (`duration = 3600000 ms`) of the Production calendar's
  Morning shift on 2026-04-27.

Same `measure.id = 1644` in both files; the published shapes differ.
The `measureDataApiEndpoint` URL also differs:
`eventPeriods=true&eventid=139` for the shift profile,
`eventPeriods=false&calendarid=1` for the calendar profile. Both
URLs hit the same Flow REST endpoint but request different bucket
regimes. The table stores them as two distinct rows because the
natural key includes `interval` -- consumers asking for shiftly
data hit the shift URL, consumers asking for hourly hit the
calendar URL.

### How our API will get it

A `IntervalMetricSource` Protocol with one initial implementation
`SqlIntervalMetricSource` that internally orchestrates a SQL lookup
plus an HTTP fan-out:

1. **Tag lookup.** `SELECT history_url, asset, metric_name, interval
   FROM [FLOW].[INTERVAL_METRIC_TAGS] WHERE enabled = 1` plus the
   consumer's filter combination (site_id required, others
   optional).
2. **History fan-out.** For each matched tag, an async
   `httpx.AsyncClient.get(url, params={from, to})`. Calls run in
   parallel via `asyncio.gather`. The vendor REST API authenticates
   via a token / API key from `backend/.env` (mechanism per the
   vendor; mirrors how `db_conn_string` is configured today).
3. **Parse and aggregate.** Each response shape (bucket_start,
   bucket_end, value, unit) is parsed into a flat
   `IntervalMetricPoint` dataclass. Per-tag results are concatenated
   into one envelope.
4. **Cache.** `SnapshotStore` (the Protocol seam in
   `core/snapshot.py`) holds the assembled envelope keyed by the
   filter combination. TTL is generous because interval metrics are
   append-only after a bucket closes -- the value never changes
   retroactively. Proposed defaults: 5 minutes for hourly,
   15 minutes for shiftly, 30 minutes for daily. Tunable via env.
5. **Return.** Single envelope back to the consumer.

The pool used for the SQL lookup is the same `app.state.sql_pool`
that production reports use -- one ODBC pool against the same
`IA_ENTERPRISE` database covers both domains. No new connection
string; no additional lifespan plumbing.

The HTTP client is a separate integration in
`backend/app/integrations/external/historian.py` (per
`backend/CLAUDE.md` folder-roles convention). It's shared with any
other endpoint that needs the historian -- not coupled to
`SqlIntervalMetricSource`.

### How consumers will ask for it

Endpoint shape, mirroring spec 002:

```
GET /api/metrics/<subject_type>/<interval>
        ?site_id=101                  [required]
        &department_id=127            [optional -- one workcenter]
        &subject_id=C4                [optional -- one asset]
        &metric=tons                  [optional -- one metric]
        &from_date=2026-04-01         [required]
        &to_date=2026-04-24           [required]
```

Filters compose. Same endpoint serves multiple consumer patterns:

| Consumer scenario | Filter combination |
|---|---|
| Ignition fetches one tag for a chart | `subject_id=C4&metric=tons` |
| Ignition populates a table of all conveyors at a workcenter | `department_id=127&metric=tons` |
| Dashboard shows hourly tons for the workcenter being viewed | `department_id=127&metric=tons` |
| Excel report pulls everything for a site for a month | `site_id=101` (no other filter) |

Plus a discovery endpoint for use cases that need to enumerate tags
without fetching their data:

```
GET /api/metrics/<subject_type>/subjects?site_id=101&department_id=127
  → [{subject_id, metric_names: [...], last_seen, unit}, ...]
```

Cheap (one `SELECT` against `INTERVAL_METRIC_TAGS`, no HTTP fan-out).
Useful for Ignition dropdowns, dashboard inventory pages,
health-check surfaces ("3 conveyors at site 101 are silent").

Response envelope shape (`IntervalMetricsResponse`, mirroring spec
002 D6):

```json
{
  "count": 168,
  "subject_type": "conveyor",
  "interval": "hourly",
  "site_id": "101",
  "department_id": "127",
  "subject_id": null,
  "metric": "tons",
  "from_utc": "2026-04-01T00:00:00Z",
  "to_utc": "2026-04-24T00:00:00Z",
  "generated_at": "2026-04-24T15:30:00Z",
  "entries": [
    {
      "subject_type": "conveyor",
      "subject_id": "C1",
      "metric": "tons",
      "interval": "hourly",
      "bucket_start": "2026-04-23T07:00:00Z",
      "bucket_end": "2026-04-23T08:00:00Z",
      "value": 412.7,
      "unit": "short_tons"
    },
    ...
  ]
}
```

Defensive limits at the route layer:

- **Window required.** No "all of history" default. Consumer must
  pass `from_date` + `to_date`.
- **Max window** of 400 days for shiftly / daily, 31 days for
  hourly (TBD with sample data; the goal is to prevent accidental
  full-table-scan-shaped requests).
- **Max points cap** of 50,000 entries per response. If the filter
  combination would return more, return 422 with a message naming
  which filter would help (e.g. "narrow the window or add a metric
  filter").

### Things to know

- **API never touches MQTT.** The architecture deliberately routes
  MQTT traffic through Ignition into the tag table; our FastAPI
  reads the table. If you find yourself writing MQTT-subscribe
  code in the API, reconsider -- the long-lived process belongs in
  the SCADA layer.
- **Tag table is read-only from our API's perspective.** We never
  `INSERT` / `UPDATE` / `DELETE`. The SQL grant for our service
  account stays narrow (`SELECT` only). All writes happen via the
  Ignition tag change script.
- **URL stability.** Flow generates the URL once at metric
  creation. Our cache TTL on the *tag lookup* (separate from the
  history-data cache) can be aggressive -- minutes to an hour --
  because URLs only change when a metric is reconfigured in Flow.
- **Backfill is automatic.** When a new tag is provisioned in Flow,
  it starts publishing on its normal cadence; the tag change
  script picks it up on the first publish; the API sees it on the
  next cache refresh. No bootstrap script needed.
- **Multi-database future.** If a future deployment routes interval
  metrics through a different database than production reports,
  promote `app.state.sql_pool` to a dict keyed by pool name and
  resolve per-source. Not preemptively designed.

## Side-by-side comparison

| Aspect | Production reports | Interval metrics |
|---|---|---|
| Status | Implemented (Phase 1-8) | Design locked, pending sample data |
| Data location | Internal SQL on enterprise server | Vendor remote SQL + REST API |
| Discovery | None needed -- SELECT all rows in window | SQL table populated by Ignition trigger |
| Our role | Read SQL → Pydantic → JSON | Read tag table → fan out HTTP → aggregate → cache |
| URL namespace | `/api/production-report/*` | `/api/metrics/<subject>/<interval>` |
| Endpoint inputs | site_id (opt), date window | site_id, department_id, subject_id, metric, date window |
| Consumers | Dashboard primarily | Dashboard + Ignition + Excel reports + future |
| Caching | None today (seam shipped) | SnapshotStore from day one |
| Cadence consumers see | 30s polling | 5-30 min polling |
| Failure mode | Source down → 503 from DI provider | Source down → 503; cache may serve stale data briefly |
| Source-Protocol pattern | Yes (`ProductionReportSource`) | Yes (`IntervalMetricSource`) |

The shared spine is the source-Protocol pattern. The two domains
plug into separate Protocols, separate routes, separate response
envelopes, separate caches. They share an aioodbc pool and the
project's general request-lifecycle infrastructure
(`CorrelationIdMiddleware`, structured logging, lifespan, etc.).

## How to extend

### Adding a new endpoint to an existing domain

Follow the layered pattern -- schema, service, route -- and never
short-circuit.

1. Define the response model in `schemas/<domain>.py`.
2. If new business logic is needed, add a service function in
   `services/<domain>.py` that takes the Protocol.
3. Add a route handler in `api/routes/<domain>.py` that validates
   query params via Pydantic, calls exactly one service function,
   and returns the response model.
4. Tests under `tests/api/` for the route, plus
   `tests/services/` for any new service logic.

No new files outside the existing folder structure unless the
addition truly is a new layer (e.g. a brand-new integration).

### Adding a new domain

Each domain is a folder:

- `integrations/<domain>/base.py` -- Protocol + dataclass row type +
  any shared dataclasses.
- `integrations/<domain>/<source>.py` -- one file per concrete
  source implementation (SQL, REST, etc.).
- `services/<domain>.py` -- service functions.
- `api/routes/<domain>.py` -- route handlers.
- `schemas/<domain>.py` -- Pydantic response models.

Wire the route into `main.py`'s router list under a unique
`/api/<domain>/...` prefix. If the domain needs its own connection
pool (separate database, different driver), add it to
`app.state` in the lifespan. Otherwise reuse the existing pool.

### Adding a new consumer

The API doesn't care who calls it. Document the consumer's expected
patterns in this file, but no API changes are needed unless the
consumer reveals a gap (e.g. needs a filter combination that
doesn't exist yet).

## Cross-references

For deep-dives on specific layers:

- **Backend internals (FastAPI request lifecycle, source Protocol,
  middleware, lifespan).** `backend/ARCHITECTURE.md`. Production-
  report flavored throughout but applies to both domains.
- **Production-report payload shape.** `PAYLOAD-CONTRACT.md` --
  the canonical-fields-plus-shape-probe contract.
- **Interval metrics design (current spec).**
  `tasks/specs/002-interval-metric-sources.md`. Marked DRAFT
  until sample data lands.
- **SQL integration spec (Phase 3).**
  `tasks/specs/001-sql-integration-layer.md`. Background on the
  source-Protocol pattern, query-file convention, ODBC plumbing.
- **Operational instructions.** `RUNBOOK.md` -- run, deploy,
  troubleshoot.

For the *why* behind specific decisions:

- `tasks/decisions/001-stack-and-source-boundary.md` -- why we
  chose the Protocol-based source pattern (sources interchangeable
  behind a single contract) and where the source boundary lives.
  The doc was authored when CSV and SQL were both production
  options; Phase 13 (2026-04-28) consolidated to SQL-only, but the
  Protocol-pattern rationale still stands.
- `tasks/decisions/002-absolute-time-filter.md` -- why the
  dashboard uses absolute date windows (day picker / month picker)
  instead of rolling Today/Week/Month buttons.
- `tasks/decisions/003-enrichment-joins.md` -- why we replicate
  the SP's joins in `select_all.sql` rather than `EXEC`-ing it,
  and why weather icons are picked from `WEATHER_CONDITIONS` text
  rather than from a separate `icon_code` column.

For domain glossary and SQL schema details:

- `context/domain.md` -- SCADA terminology, OEE definitions,
  plant vocabulary.
- `context/sql-schema.md` -- Flow_Curated table structure, joins,
  gotchas.
- `context/external-apis.md` -- third-party API shapes and auth
  patterns.

## Revision history

- **2026-04-24 (initial)** -- Production-report section reflects
  Phase 8 state (enriched joins, weather/notes/shift). Interval
  metrics section reflects design locked in conversation
  2026-04-24: Flow → MQTT → Ignition → `INTERVAL_METRIC_TAGS`
  → REST → SnapshotStore.
