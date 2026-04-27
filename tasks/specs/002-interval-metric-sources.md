# SPEC-002 — Interval metric sources

**Status:** Draft — 2026-04-23
**Parent decision:** `tasks/decisions/001-stack-and-source-boundary.md`
(extends the Protocol-based-source pattern to a second, distinct domain)
**Prerequisites:** Phase 4 complete (Docker + SQL backend in production).
Spec resolves open questions as Trey's curated conveyor-shiftly sample
data arrives. Sections flagged "TBD-with-data" are intentionally
uncommitted until then.

## Context

The API surfaces one data domain today: the production-report payload
(curated, end-of-shift, business-computed — see
`context/sample-data/production-report/payload-schema.md`). The next
class of data the dashboard needs is fundamentally different:

- **Higher cadence.** Hourly / shiftly / eventually 15-minute buckets,
  not once-per-shift summary rows.
- **Simpler shape.** A subject + a metric + a bucket + a value. No
  opaque JSON payload, no operator names, no produced-item codes.
- **Raw(er).** Closer to the underlying tag data; aggregation-only,
  without the business-logic layer that shapes production reports.
- **Different subjects.** Conveyors first (shiftly tons is the motivating
  use case), then equipment, then likely alarms and feed rates.

Trey's direction (2026-04-23 conversation): **keep these separate from
production reports.** Production reports are a curated payload with
human input and derived OEE math; interval metrics are simpler,
typed, interval-bucketed observations. Forcing one abstraction over
both would compromise both.

This spec defines the pattern for a second domain sitting beside
production reports, not subordinated to them.

## Decisions

### D1. Separate Protocol, separate folder

New Protocol `IntervalMetricSource` lives at
`backend/app/integrations/metrics/base.py`. **Not** an extension of
`ProductionReportSource`. The two share nothing structural beyond a
reference to the shared `SourceStatus` dataclass (currently in
`integrations/production_report/base.py` — may migrate to
`integrations/common/base.py` if a second consumer appears; not moving
it preemptively).

Folder layout mirrors the production-report one, as a sibling:

```
backend/app/integrations/
├── production_report/     # existing — curated end-of-shift records
│   ├── base.py
│   ├── csv_source.py
│   ├── sql_source.py
│   └── queries/
└── metrics/               # new — interval-bucketed observations
    ├── base.py
    ├── csv_source.py       # reads the committed sample TSV for tests
    ├── sql_source.py       # production backend (table name TBD)
    └── queries/
```

### D2. One Protocol per subject type

Conveyors, equipment, alarms, etc. each get their own Protocol
(`ConveyorMetricSource`, `EquipmentMetricSource`, ...), not a single
generic `IntervalMetricSource` parametrized by `subject_type: str`.

Rationale: the expected number of subject types over the life of the
project is 3–5, not 30. At that scale, one-Protocol-per-subject gives
us per-subject type safety and clearer DI wiring; the boilerplate cost
(one new Protocol + one new DI provider + one new router per subject)
is small and linear.

`IntervalMetricSource` becomes a *base Protocol* that each subject's
Protocol inherits from (structurally, via duck typing — Python
Protocols compose cleanly). Shared fields: `name`, `ping()`.
Per-subject fields: whatever that subject needs.

Reassess if we ever get to 6+ subject types without clear per-subject
divergence.

### D3. Typed Pydantic schema, not opaque payload

Interval metrics do not carry a `PAYLOAD` dict. The response type is a
flat `IntervalMetricPoint` with typed fields — see "Data shape" below.
Schema stability over convenience: the dashboard's metric panels can
rely on specific field names without case-by-case unpacking.

If a particular subject type later grows metadata that doesn't fit the
flat shape, introduce a `context: dict[str, Any]` side-field before
reaching for per-subject Pydantic models.

### D4. URL namespace: `/api/metrics/<subject>/<interval>`

Not mounted under `/api/production-report/*`. Examples:

```
GET  /api/metrics/conveyor/shiftly?subject_id=<optional>&metric=<optional>&from=<ISO>&to=<ISO>
GET  /api/metrics/conveyor/hourly?...
GET  /api/metrics/conveyor/subjects      # list of conveyor IDs present
GET  /api/metrics/conveyor/metrics       # list of metric names available for this subject
GET  /api/metrics/equipment/shiftly?...  # future
```

`subject` and `interval` are path segments, not query params, because
they change the shape of the response (`conveyor` shiftly tons vs
`equipment` runtime are different metric catalogs). Swagger groups
them cleanly, and the URL reads as a resource path.

### D5. Working terminology — "interval metric"

Approved in conversation 2026-04-23. "Measure" is acceptable as a
synonym in UI copy; code and endpoints use "metric." SCADA vernacular
"tag history" is narrower (implies raw tag values before aggregation)
and is NOT used as the name of this domain.

Glossary for the spec and code:

| Term | Definition |
|---|---|
| **Subject type** | Class of thing being measured (`conveyor`, `equipment`). Singular, lowercase, URL-safe. |
| **Subject ID** | Identifier of a specific instance within a subject type (e.g., a conveyor ID). |
| **Metric** | Named quantity being measured (`tons`, `runtime`, `availability`). |
| **Interval** | Aggregation bucket size (`hourly`, `shiftly`, eventually `fifteen_min`). |
| **Bucket start / end** | The UTC timestamps bounding the interval. |
| **Value** | The numeric measurement for that bucket. |
| **Unit** | Unit of the value, when known (`short_tons`, `min`, `pct`, `_` for unitless). |

### D6. Source implementation pattern mirrors production-report

Same two-implementation pattern as `ProductionReportSource`:

- `CsvIntervalMetricSource` reads a committed sample TSV at
  `context/sample-data/interval-metrics/<subject>-<interval>.csv`.
  Permanent test fixture; default backend during local dev when SQL
  isn't configured.
- `SqlIntervalMetricSource` reads from SQL Server via the same aioodbc
  pool created in `main.py`'s lifespan. Query files under
  `backend/app/integrations/metrics/queries/`.

Config key: `PMD_METRICS_BACKEND=csv|sql` (default `csv`), parallel to
the existing `PMD_PRODUCTION_REPORT_BACKEND`. The two can point at
different backends — e.g. production reports on SQL, metrics on CSV
during conveyor-data bring-up — without either affecting the other.

### D7. Pool reuse

The existing `app.state.sql_pool` created for production reports is
reused for the metrics SQL source. A single ODBC pool against the
same `IA_ENTERPRISE` database covers both domains. No new config for
a second connection string.

If metrics ever point at a *different* database (separate server,
separate credentials), promote `app.state.sql_pool` to a dict keyed
by pool name and resolve per-source. Not doing that preemptively.

### D8. Dashboard placement — below workcenter panels

New frontend section rendered below the existing workcenter cards,
titled "Interval Metrics" (or TBD at render time). Each subject type
gets its own sub-panel. Initial rendering: tabular with subject_id,
metric, latest-bucket value + unit, interval label.

Charting (sparkline of value over bucket time) is a Phase 6 item, not
in scope for the first interval-metrics integration. Chart.js is
already loaded and idle, waiting.

### D9. Caching: metrics are more cache-friendly than production reports

Shiftly data updates every 8–12 hours; hourly updates every hour.
Either way it's append-only once a bucket closes — the value never
retroactively changes. That makes interval metrics a clean first
candidate for the `SnapshotStore` seam already shipped in
`core/snapshot.py`. TTL proposal (subject to sample-data confirmation):

- `hourly` — cache 5 min (catches any late-arriving rows while still
  refreshing faster than the bucket cadence)
- `shiftly` — cache 15 min

Wire caching *during* the metrics integration rather than as a
retrofit — the new source path is the cheapest place to introduce it.
Production-report caching can follow the same pattern once we've
confirmed it works here.

### D10. CSV sample data format

Tab-delimited, `.csv` extension (matches the production-report
convention). Flat columns:

```
SUBJECT_TYPE  SUBJECT_ID  METRIC  INTERVAL  BUCKET_START  BUCKET_END  VALUE  UNIT
```

Committed under `context/sample-data/interval-metrics/`. README in the
same folder documents real vs synthetic per the production-report
convention. Bucket timestamps in ISO-8601 UTC with `Z` suffix.

Parser tolerates empty `UNIT` (treat as `None`). All other columns
required and non-null.

## Data shape

```python
# backend/app/integrations/metrics/base.py

@dataclass(frozen=True)
class IntervalMetricPoint:
    subject_type: str        # "conveyor", "equipment"
    subject_id: str          # instance id within that subject
    metric: str              # "tons", "runtime", ...
    interval: str            # "hourly", "shiftly"
    bucket_start: datetime   # UTC, inclusive
    bucket_end: datetime     # UTC, exclusive
    value: float
    unit: str | None         # "short_tons", "min", "pct", None = unitless
```

```python
# backend/app/schemas/metrics.py (new)

class IntervalMetricEntry(BaseModel):
    subject_type: str
    subject_id: str
    metric: str
    interval: str
    bucket_start: datetime
    bucket_end: datetime
    value: float
    unit: str | None

class IntervalMetricsResponse(BaseModel):
    count: int
    subject_type: str
    interval: str
    subject_id: str | None       # echo of optional filter
    metric: str | None           # echo of optional filter
    from_utc: datetime           # echo of query window
    to_utc: datetime
    generated_at: datetime
    entries: list[IntervalMetricEntry]
```

## Protocol sketch

```python
# backend/app/integrations/metrics/base.py

@runtime_checkable
class IntervalMetricSource(Protocol):
    """Base Protocol — each subject-type Protocol specializes this."""
    name: str
    subject_type: str               # e.g. "conveyor"
    async def ping(self) -> SourceStatus: ...

@runtime_checkable
class ConveyorMetricSource(IntervalMetricSource, Protocol):
    async def fetch_points(
        self,
        *,
        interval: str,
        from_utc: datetime,
        to_utc: datetime,
        subject_id: str | None = None,
        metric: str | None = None,
    ) -> list[IntervalMetricPoint]: ...
    async def list_subjects(self) -> list[str]: ...
    async def list_metrics(self) -> list[str]: ...
```

Keyword-only arguments after `*` force named-arg call sites, so future
additions (e.g. `limit`, `aggregate`) don't need positional compat.

## Endpoint design

| URL | Purpose |
|---|---|
| `GET /api/metrics/conveyor/{interval}` | Points within window, with filters |
| `GET /api/metrics/conveyor/subjects` | List of conveyor IDs present |
| `GET /api/metrics/conveyor/metrics` | List of metric names available |
| `GET /api/metrics/equipment/{interval}` | (future) same shape for equipment |

`{interval}` is `hourly` or `shiftly`; validated as `Literal[...]` at
the route layer so unknown values get 422 before the handler runs.

Query params on `/{interval}`:

| Param | Type | Required | Notes |
|---|---|---|---|
| `from` | ISO datetime (UTC) | **yes** | Bucket-start lower bound, inclusive |
| `to` | ISO datetime (UTC) | **yes** | Bucket-start upper bound, exclusive |
| `subject_id` | str | no | Filter to one conveyor |
| `metric` | str | no | Filter to one metric (e.g. `tons`) |

Window is required to prevent accidental full-table scans. Max window
enforced at the route layer (default 31 days for shiftly, 7 days for
hourly — revisit with data).

## Implementation sequence

Once Trey's sample data arrives and this spec is approved:

1. Commit the sample TSV under
   `context/sample-data/interval-metrics/conveyor-shiftly.csv` and
   write its `README.md`.
2. `IntervalMetricPoint` dataclass + `IntervalMetricSource` /
   `ConveyorMetricSource` Protocols.
3. `CsvIntervalMetricSource` reading the committed sample (mirrors
   `CsvProductionReportSource`).
4. Pydantic response schemas in `backend/app/schemas/metrics.py`.
5. Service functions in `backend/app/services/metrics.py` (window
   filtering, optional subject/metric filtering, sort).
6. Route handlers in `backend/app/api/routes/metrics.py`.
7. DI wiring + `PMD_METRICS_BACKEND` config.
8. Tests — CSV source unit tests, route integration tests against the
   sample data.
9. `SqlConveyorMetricSource` once we've confirmed the query shape from
   the real table. `ping.sql` + `select_by_window.sql` at minimum.
10. Wire `SnapshotStore` at the DI layer for both metrics endpoints.
11. Frontend panel: new section below workcenter cards, one sub-panel
    per subject type, table rendering.
12. Docs: `RUNBOOK.md` gets new endpoint URLs, `ARCHITECTURE.md` gets a
    mention in the request-lifecycle + extension-points sections,
    `backend/ARCHITECTURE.md` gets a "Second domain" note.

## Open questions (resolve with Trey's sample data)

| # | Question | Blocks |
|---|---|---|
| Q1 | Is the SQL table one-row-per-(subject, metric, bucket), or wide (one row with many metric columns)? | D10 CSV format; query shape |
| Q2 | Shift boundary: what time-of-day, what timezone, which calendar day does a shift "belong to"? | Bucket-start semantics |
| Q3 | Do conveyor IDs share namespace with `DEPARTMENT_ID` from production reports, or separate? If separate, is there a mapping? | Whether dashboard cross-links |
| Q4 | Exact metric names available per subject. Which carry a natural unit (tons, min, %), which are unitless ratios? | Unit column defaults |
| Q5 | Table name(s) and database. Same `IA_ENTERPRISE` as production reports? | Pool reuse (D7 assumption) |
| Q6 | Retention window. Can we support `/history?days=365`, or does the source purge sooner? | Route-layer max-window validation |
| Q7 | Is the `interval` column an enum in SQL, or derived from bucket duration? Impacts whether `interval` is a closed `Literal` in Python or open string. | Schema types |
| Q8 | Update semantics: is a bucket row ever *retroactively* modified after first write? (Affects cache invalidation.) | D9 TTL tuning |
| Q9 | What other subject types are near-term — alarms, feed rates, equipment runtime? Order of introduction informs whether the base Protocol should expose any additional shared methods. | D2 sizing |

## Non-goals (scope-preventers, not forever-nos)

- Live streaming / websocket push — dashboard stays poll-based.
- Roll-up arithmetic at the API layer. If the source has only shiftly
  data, the API does not synthesize hourly from it. Upstream produces
  each granularity explicitly, or that granularity isn't served.
- A query-language surface (`$filter=...`, etc.). Fixed named params
  only.
- Cross-subject joins at the API. "Give me this conveyor's tons next
  to that workcenter's OEE" is a frontend-side concern for now.
- Authentication. Same deferral as the rest of the API.
- Writing interval metric data. Read-only, same as the rest of the API.
- Per-subject Pydantic response models. One flat `IntervalMetricEntry`
  covers all subjects until it demonstrably doesn't.
- Backfilling the sample TSV with synthetic multi-site data the way we
  did for production reports. One subject, one site, real data only
  until we have it working end-to-end.

## Dependencies on other work

- **Phase 3 SQL pool** — reused for the SQL metrics source (D7). No
  change required to `main.py`'s lifespan.
- **`SnapshotStore` Protocol** — wired during implementation (D9). No
  new dependency; the Protocol is already shipped in
  `core/snapshot.py`.
- **No new Python packages.** The runtime dependencies already cover
  everything this spec needs.

## Revision history

- 2026-04-23: Initial draft. Awaiting sample data to resolve Q1–Q9.
