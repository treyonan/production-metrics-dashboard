# SPEC-003 — Timebase i3X wrapper (history pass-through + catalog)

**Status:** Draft — 2026-05-21
**Parent decision:** N/A (third source, already anticipated in
`CLAUDE.md` open question #4 and architecture diagram).
**Prerequisites:** None at the API layer. Phase 1 ships without a
frontend; verified through `/docs` and pytest. A separate Phase 2 spec
will cover the trend-chart page.

## Context

Timebase Historian is the third planned data source for the dashboard —
raw, sub-minute, tag-level samples — sitting beside SQL Server (curated
production reports) and Flow (curated interval metrics). Reference
material:

- `examples/timebase-i3x-api/reference/timebase-i3x-api-docs.md` —
  vendor API docs (i3X v0.0.1, OAS 3.1, RFC 001 compliant).
- `examples/timebase-i3x-api/api.py` — the SCADA-side Ignition/Jython
  client. **Not** the FastAPI client; we'll write our own with
  `httpx.AsyncClient`.
- `examples/timebase-i3x-api/reference/example-query-history-request-body.json`
  — sample request body.
- `examples/timebase-i3x-api/reference/example-query-history-response.json`
  — sample response (truncated). Real responses for multi-day windows
  can be megabytes.

The Timebase elementId for a single tag looks like:

```
IAP_BCQ_Controls:Big_Canyon/Secondary/Conveyor/C1/Process_Data/Belt_Scale/TPH
└──── dataset ────┘ └────── per-site prefix ──────┘└── stable suffix ──┘
```

Per Trey's confirmation: the stable suffix
(`Conveyor/Cn/Process_Data/Belt_Scale/TPH` for TPH;
`Conveyor/Cn/Process_Data/Belt_Scale/Odometer` for odometer/Total) is
**identical across every site**. What varies is the prefix
`<dataset>:<site_root>/<department>/`. This makes a convention-based
catalog tractable.

## Goals

Phase 1 delivers a backend-only Timebase integration that the dashboard
will consume in Phase 2:

1. A thin pass-through over the i3X `/objects/history` endpoint, taking
   the same request shape and returning the same response shape, so the
   FastAPI service is a *wrapper*, not an opinionated translator.
2. A site-scoped tag catalog endpoint so the eventual UI can populate
   asset/metric dropdowns without hard-coding elementIds in the
   frontend.
3. Per-source 503 graceful degradation matching the existing pattern
   (Flow, SQL).

Non-goals for Phase 1:

- No frontend page or chart. Verification is via `/docs` Swagger UI
  against the real Timebase server, plus pytest with mocked httpx.
- No write endpoints (i3X `update_value` / `update_history`). Read-only,
  per project policy.
- No subscriptions / SSE streaming. Polling-only fits the dashboard
  cadence and avoids long-lived connection state in the API.
- No `/objects/value` (last-known-value) endpoint. We *may* add it later;
  Phase 2 won't need it.
- Browsing endpoints (`/objects`, `/objects/list`, `/objects/related`).
  The catalog covers the dashboard's needs. We can add them later if a
  freeform tag picker becomes a requirement.

## Decisions

### D1. Add to existing API, do not create a new service

`CLAUDE.md` already names Timebase as the third source feeding **this**
FastAPI service. Adding a `backend/app/integrations/timebase/` module
fits the existing pattern (sibling to `production_report/`, `metrics/`,
`external/`), uses the same auth/log/config posture, and ships in the
same Docker image. A standalone service would only earn its keep if
non-dashboard consumers existed; none do today.

### D2. Wrapper preserves i3X request/response shapes

The history endpoint's request body is **exactly** the i3X shape:

```json
{
  "elementIds": ["<full elementId>", "..."],
  "startTime": "2026-05-01T06:06:00Z",
  "endTime":   "2026-05-02T07:06:00Z",
  "maxDepth":  1
}
```

The response is the i3X dict-keyed-by-elementId shape, returned
unmodified:

```json
{
  "<elementId>": {
    "data": [
      {"value": 3, "quality": "GOOD", "timestamp": "..."},
      ...
    ]
  }
}
```

Pydantic models exist for input validation and OpenAPI documentation,
not for re-shaping. If i3X adds optional fields later, we surface them
without re-pydantic-ing the world.

### D3. Catalog lives in a YAML file, not SQL

`backend/app/integrations/timebase/catalog.yaml` is the source of
truth. Reasons:

- The data is small (a few sites × ~8 conveyors × a few metrics) and
  rarely changes. SQL overkill.
- Source control gives diff visibility for "we added a new tag" — the
  same property that makes a YAML site list better than a SQL table for
  small/stable config.
- No DB dependency for Timebase to work, which matters during partial
  outages (SQL down ≠ Timebase down).

If the catalog ever needs editing by non-engineers without a redeploy,
migrate to SQL using the existing `MES.RUN_REPORTS_CONFIG` pattern with
`(0, 0)` global-fallback rows. Not preemptive.

### D4. Catalog shape

Two layers: per-site prefix config + a shared asset-class metric
catalog. The full elementId for `(site_id, asset, metric_key)` is
resolved as:

```
<dataset>:<site_prefix>/<asset_class>/<asset>/<metric_suffix>
```

Sketch:

```yaml
# backend/app/integrations/timebase/catalog.yaml

# Per-site prefix config. Each site declares its dataset and the
# prefix path to each department's asset folder.
sites:
  101:                                # site_id (matches Flow's site_id)
    code: BCQ
    display_name: Big Canyon Quarry
    dataset: IAP_BCQ_Controls
    departments:
      Secondary: Big_Canyon/Secondary
      # future: Wash_Plant: Big_Canyon/Wash_Plant
  # future sites added here

# Shared catalog: which assets exist per asset_class, and the stable
# tag suffix for each metric_key. Same across every site by definition.
asset_classes:
  Conveyor:
    assets: [C1, C2, C3, C4, C5, C6, C7, C8]
    metrics:
      belt_scale_tph:
        display_name: Belt Scale TPH
        unit: tph
        suffix: Process_Data/Belt_Scale/TPH
        # future: aggregation hints (rate vs cumulative), units, etc.
```

Phase 1 scope: `Conveyor` only, `belt_scale_tph` only, sites Trey
populates. Adding `belt_scale_odometer` (the Total metric) is one new
entry under `metrics:` — no code change.

### D5. Endpoint surface

```
POST /api/timebase/history          # i3X pass-through
GET  /api/timebase/catalog          # entire catalog
GET  /api/timebase/catalog/{site_id} # one site's catalog (convenience)
```

`POST /api/timebase/history` request body matches D2.

`GET /api/timebase/catalog` returns the resolved catalog for **all
configured sites**, with full elementIds pre-computed:

```json
{
  "sites": [
    {
      "site_id": 101,
      "code": "BCQ",
      "display_name": "Big Canyon Quarry",
      "dataset": "IAP_BCQ_Controls",
      "departments": [
        {
          "name": "Secondary",
          "asset_classes": [
            {
              "class": "Conveyor",
              "assets": [
                {
                  "asset": "C1",
                  "metrics": [
                    {
                      "metric_key": "belt_scale_tph",
                      "display_name": "Belt Scale TPH",
                      "unit": "tph",
                      "element_id": "IAP_BCQ_Controls:Big_Canyon/Secondary/Conveyor/C1/Process_Data/Belt_Scale/TPH"
                    }
                  ]
                }
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

`GET /api/timebase/catalog/{site_id}` returns just one site's entry.
Frontend will typically call the single-site variant once per page
load.

### D6. Configuration

New env vars in `.env.example`:

```
TIMEBASE_BASE_URL=http://10.44.135.12:8080
TIMEBASE_TIMEOUT_SECONDS=15
TIMEBASE_CACHE_TTL_SECONDS=45
TIMEBASE_CACHE_MAX_ENTRIES=128
```

`TIMEBASE_BASE_URL` unset → integration stays down, `/api/timebase/*`
returns 503 from the DI provider (same pattern as Flow/SQL).
Timeout/cache values default to the listed numbers if env vars are
unset.

No auth (per Trey's confirmation). When auth lands later, it goes here
without changing the route shape.

### D7. Caching: TTL + LRU size cap, normalize endTime

History responses can be MB-scale for multi-day windows. Cache is
in-memory inside the worker (consistent with existing
`InMemorySnapshotStore` pattern), keyed on:

```
(elementIds_sorted_tuple, normalized_start, normalized_end, max_depth)
```

`normalized_*` rounds the requested timestamps to the nearest **10
seconds** (toward zero — drop sub-10s precision). The normalized
window is what we forward to Timebase. The frontend's polling
"endTime=now" requests will produce stable cache keys for ~10 seconds
of polling regardless of when within the second the request lands.
Documented in the OpenAPI description so the Phase 2 frontend can rely
on it.

Cache eviction: LRU on entry count (`TIMEBASE_CACHE_MAX_ENTRIES`, default
128). TTL eviction on read (`TIMEBASE_CACHE_TTL_SECONDS`, default 45s).
No size-in-bytes cap initially — entry-count cap is a sufficient
backstop for now. Revisit if we see memory pressure.

### D8. Graceful degradation

- Timebase unreachable at startup → log error, `app.state.timebase_client
  = None`, `/api/timebase/*` routes return 503 from DI provider.
- Timebase 4xx/5xx → bubble status through as 502 (upstream error) with
  the upstream body in `detail` for engineers to see.
- Timeout → 504 with `{ "source": "timebase", "error": "timeout" }`.
- Catalog YAML missing/malformed at startup → log error, catalog routes
  return 503. History route still works for callers who already know
  elementIds (this matters: the catalog is a *convenience*, not a
  gatekeeper).
- `/api/health` adds a `timebase` source entry alongside `flow` and
  `sql`, pinging Timebase with a cheap `GET /i3x/namespaces` call.

### D9. Folder layout

```
backend/app/integrations/timebase/
├── __init__.py
├── client.py          # httpx.AsyncClient wrapper, methods:
│                      #   - aopen() / aclose() lifecycle
│                      #   - get_history(elementIds, start, end, max_depth)
│                      #   - get_namespaces()  # for health ping
├── catalog.py         # YAML loader + resolver
├── catalog.yaml       # source of truth (in-repo)
└── cache.py           # TTL + LRU cache wrapper (or inline in client.py
                       # if it stays small — TBD during implementation)

backend/app/api/routes/
└── timebase.py        # /history, /catalog, /catalog/{site_id}

backend/app/schemas/
└── timebase.py        # HistoryRequest, HistoryResponse, CatalogResponse,
                       # CatalogSite, CatalogMetric, ...
```

`main.py` lifespan adds: load catalog (once at startup, no TTL refresh
— it's source-controlled), construct `TimebaseClient`, register both
on `app.state`. On shutdown, close the client.

### D10. Pydantic shapes (sketch)

```python
# backend/app/schemas/timebase.py

class HistoryRequest(BaseModel):
    element_ids: list[str] = Field(alias="elementIds", min_length=1)
    start_time: datetime    = Field(alias="startTime")
    end_time: datetime      = Field(alias="endTime")
    max_depth: int          = Field(alias="maxDepth", default=1, ge=0)

    model_config = ConfigDict(populate_by_name=True)

class VQT(BaseModel):
    value: float | int | str | bool | None
    quality: str
    timestamp: datetime

class ElementHistory(BaseModel):
    data: list[VQT]

# Response is a dict[str, ElementHistory] keyed by elementId — modeled
# with RootModel so OpenAPI documents the shape without losing the
# pass-through property.
class HistoryResponse(RootModel[dict[str, ElementHistory]]):
    pass

class CatalogMetric(BaseModel):
    metric_key: str
    display_name: str
    unit: str
    element_id: str

class CatalogAsset(BaseModel):
    asset: str
    metrics: list[CatalogMetric]

# ... CatalogAssetClass, CatalogDepartment, CatalogSite, CatalogResponse
```

Aliases (`elementIds`, `startTime`, etc.) ensure the JSON-over-wire
matches i3X exactly while Python code uses snake_case.

### D11. Time normalization details

`endTime` arrives as ISO-8601 with timezone. Normalize:

```python
def _normalize_iso(ts: datetime) -> datetime:
    # Round down to nearest 10s boundary, force UTC.
    ts_utc = ts.astimezone(timezone.utc)
    floored = ts_utc.replace(microsecond=0)
    floored = floored.replace(second=(floored.second // 10) * 10)
    return floored
```

Both `startTime` and `endTime` are normalized for cache keying *and*
for the upstream call. The response carries Timebase's own timestamps
unmodified.

## Phase 1 → Phase 2 handoff

Phase 2 (separate spec) will build a `timebase-trends.html` page —
the same shape as `flow-interval-metrics.html` — with:
- Site dropdown (sourced from `GET /api/timebase/catalog`)
- Department / Asset Class / Asset / Metric cascading selects
- Time-range picker (relative: last hour / shift / 24h / 7d, or absolute)
- Chart.js line chart fed by `POST /api/timebase/history`
- Loading + error states, "no data" state
- Topbar `Trends` (or sub-link off `Metrics`) — placement TBD with Trey
  when we get to Phase 2

Nothing in the Phase 1 design closes the door on a freeform tag picker
later (Phase 3?) — the pass-through endpoint already accepts any
elementId.

## Acceptance criteria (Phase 1)

1. `pytest backend/tests/integrations/timebase/` passes:
   - Catalog YAML loads and resolves correct elementIds for sample
     configs.
   - Client `get_history` posts the expected body and parses the
     example response.
   - Cache hits on identical normalized requests, misses on different
     ones, evicts on TTL expiry and on LRU overflow.
   - Time normalization rounds correctly across timezone inputs.
2. `pytest backend/tests/api/test_timebase_routes.py` passes:
   - `/history` returns 200 with mocked Timebase response.
   - `/history` returns 503 when client unconfigured.
   - `/history` returns 502 on upstream 5xx, 504 on timeout.
   - `/catalog` and `/catalog/{site_id}` return the resolved shape.
3. `/api/health` includes a `timebase` source entry with `ok` /
   `degraded` / `unreachable` status.
4. With `TIMEBASE_BASE_URL` pointed at the real server, Swagger `/docs`
   can interactively call `POST /api/timebase/history` with the example
   elementId and return real samples for a small window.
5. `ruff check backend/app/integrations/timebase/` and routes are clean.

## Implementation sequence

1. `schemas/timebase.py` — Pydantic models.
2. `integrations/timebase/catalog.py` + `catalog.yaml` — loader,
   resolver, unit tests.
3. `integrations/timebase/client.py` — httpx client, `get_history`,
   `get_namespaces`, unit tests with httpx mock transport.
4. Cache layer — TTL + LRU wrapper, unit tests for eviction.
5. `api/routes/timebase.py` — routes, DI providers, route tests.
6. Wire into `main.py` lifespan + add to `/api/health`.
7. Env vars added to `.env.example` and documented in `RUNBOOK.md`.

Each step lands in its own commit. No frontend changes in Phase 1.

## Open questions

1. **Catalog refresh.** YAML is loaded once at startup. If Trey adds a
   new conveyor in catalog.yaml, restart picks it up. Is that
   acceptable, or do we want a SIGHUP / endpoint to reload without
   restart? Lean toward "restart is fine" — same posture as `.env`.
2. **Quality filtering.** Timebase returns VQTs with `quality: "GOOD"`
   (and presumably other values like `"BAD"`, `"UNCERTAIN"`). Phase 1
   passes them through unmodified. Phase 2 will need to decide whether
   to drop non-GOOD points before charting; that's a UI decision.
3. **Empty response shape.** If the upstream returns `{}` for a known
   tag with no samples in the window, what does the frontend show?
   Phase 2 decision. Phase 1 just forwards.

## Revision history

- 2026-05-21 — Initial draft. Discussion captured in
  Cowork session (TPH-first scope, no auth, no charts in Phase 1,
  caching with normalization).


## Revision 2 -- multi-site refactor (2026-05-21)

Trey flagged that each site has its own Timebase historian on its own
plant network, not a single global instance. The original spec assumed
one ``PMD_TIMEBASE_BASE_URL`` env var; that was wrong.

### Changes from Revision 1

**D5 (endpoint surface):**
``POST /api/timebase/history`` now takes a required query parameter
``?site_id=<id>``, matching the existing ``/api/metrics`` and
``/api/production-report`` convention. The request body stays exactly
i3X-shaped. ``site_id`` is a string (consistent with the rest of the
codebase, where site IDs are categorical identifiers that happen to
look numeric).

**D3 (catalog shape):** Each site block in ``catalog.yaml`` now
declares ``base_url`` alongside ``dataset``, ``code``, ``display_name``,
and ``departments``. Example::

    sites:
      "101":
        code: BCQ
        display_name: Big Canyon Quarry
        base_url: http://10.44.135.12:8080
        dataset: IAP_BCQ_Controls
        departments:
          Secondary: Big_Canyon/Secondary

``base_url`` is loaded into ``SiteDef`` but is **NOT** surfaced in
the ``/catalog`` response (defense in depth: internal historian IPs
shouldn't leak through the public API).

**D6 (configuration):** Removed ``PMD_TIMEBASE_BASE_URL`` env var.
Historian URLs come from the YAML catalog. The three numeric
tuning knobs (``PMD_TIMEBASE_TIMEOUT_SECONDS``,
``PMD_TIMEBASE_CACHE_TTL_SECONDS``,
``PMD_TIMEBASE_CACHE_MAX_ENTRIES``) remain global.

**D9 (folder layout) addendum:** ``client.py`` now exports both
``TimebaseClient`` and ``TimebaseClientRegistry``. The lifespan
iterates the loaded catalog at startup, builds one client per site
from its declared ``base_url``, opens each, and registers it. Close
on shutdown is ``registry.aclose_all()``.

**D8 (graceful degradation):**
* Each site fails independently. One site's historian being down
  does not impact the others.
* ``POST /history?site_id=X`` returns **404** when ``site_id`` isn't
  configured at all (unknown site, typo).
* Returns **503** when the site is configured but its client failed
  to open at startup (network unreachable, bad URL).
* ``/api/health`` emits one ``SourceHealth`` row per configured site
  (e.g. ``timebase:i3x:101``, ``timebase:i3x:100``). Deployments
  with no Timebase sites configured do not contribute any rows.

**Site ID type:** All Timebase code uses ``site_id: str`` for
consistency with ``/api/metrics`` and ``/api/production-report``,
where ``site_id`` is already a string query param. The catalog
loader coerces unquoted YAML integer keys to strings on load.

**Cache key:** Already includes the dataset prefix via ``element_ids``
(``IAP_BCQ_Controls:...`` is unique per site). No code change to the
cache; a single global cache is correct.

### Catalog endpoint response shape

Unchanged on the wire except ``site_id`` is now a string. ``base_url``
is intentionally absent.


## Revision 3 -- standalone endpoint + URL safety (2026-05-21)

Two follow-ups from Trey's review of Phase 26.1:

### Standalone use: ``POST /api/timebase/history-by-tag``

Some callers (Ignition scripts, ad-hoc tools, future integrations)
want to use the wrapper as a generic i3X proxy without preconfiguring
a site in ``catalog.yaml``. New endpoint:

```
POST /api/timebase/history-by-tag
{
  "base_url":  "http://10.44.135.12:8080",
  "dataset":   "IAP_BCQ_Controls",
  "tagPaths":  [
    "Big_Canyon/Secondary/Conveyor/C1/Process_Data/Belt_Scale/TPH",
    "Big_Canyon/Secondary/Conveyor/C2/Process_Data/Belt_Scale/TPH"
  ],
  "startTime": "2026-05-01T06:06:00Z",
  "endTime":   "2026-05-02T07:06:00Z",
  "maxDepth":  1
}
```

The server composes ``<dataset>:<tag_path>`` for each entry, builds
an ephemeral ``TimebaseClient`` targeting ``base_url``, calls the
upstream ``POST /i3x/objects/history``, and returns the i3X response
unmodified. Cache is shared with ``/history`` (cache key uses the
composed elementIds, which carry the dataset prefix).

**No catalog or registry dependency** -- the endpoint works even when
``catalog.yaml`` failed to load and the registry is empty. Useful for
fresh checkouts and one-off queries.

**SSRF guardrail:** ``base_url`` is restricted to ``http://`` /
``https://`` schemes (422 otherwise). No host whitelist in Phase 1 --
deploy only behind a trusted network boundary. If untrusted ingress
becomes a concern, add ``PMD_TIMEBASE_ALLOWED_HOSTS`` (CIDR list)
later without a route shape change.

### URL safety: gitignored catalog + committed example

Per Trey's call (2026-05-21), real historian URLs should not be in
the public repo. Split:

* ``backend/app/integrations/timebase/catalog.example.yaml`` -- committed
  template with placeholder URLs (``http://historian.example.invalid:8080``).
  Ships the full structure for the dashboard + tests.
* ``backend/app/integrations/timebase/catalog.yaml`` -- gitignored, real
  ``base_url`` values per site. Production must provide this.

Loader behavior (``load_catalog``):
1. If caller passes an explicit path, use it.
2. Else if ``catalog.yaml`` exists, use it.
3. Else fall back to ``catalog.example.yaml`` (tests + fresh checkouts work).
4. Else raise ``CatalogError("No catalog file found...")``.

Deployment workflow:

```bash
cp backend/app/integrations/timebase/catalog.example.yaml \
   backend/app/integrations/timebase/catalog.yaml
$EDITOR backend/app/integrations/timebase/catalog.yaml  # set real base_urls
```

Same posture as ``.env.example`` -> ``.env``.

### Endpoint surface after Revision 3

```
POST /api/timebase/history?site_id=<id>           # catalog-driven
POST /api/timebase/history-by-tag                 # standalone (NEW)
GET  /api/timebase/catalog                        # all sites
GET  /api/timebase/catalog/{site_id}              # one site
```

The catalog response still does NOT include ``base_url`` (defense in
depth, even if catalog.yaml is gitignored at the file level).


## Revision 4 -- single unified history endpoint (2026-05-21)

Trey's call after seeing the two-endpoint split in Revision 3:
**one endpoint** for tag history; URL+dataset lookup happens
**server-side** from the YAML catalog, **regardless of caller**.
The dashboard, Ignition scripts, and ad-hoc tools all hit the same
endpoint the same way.

### Final endpoint surface

```
POST /api/timebase/history?site_id=<id>           # the only history endpoint
GET  /api/timebase/catalog                        # all sites
GET  /api/timebase/catalog/{site_id}              # one site
```

### Final /history shape

Request:

```json
POST /api/timebase/history?site_id=101
{
  "tag_paths": [
    "Big_Canyon/Secondary/Conveyor/C1/Process_Data/Belt_Scale/TPH",
    "Big_Canyon/Secondary/Conveyor/C2/Process_Data/Belt_Scale/TPH"
  ],
  "start_time": "2026-05-01T06:06:00Z",
  "end_time":   "2026-05-02T07:06:00Z",
  "max_depth":  1
}
```

Response (dict keyed by **the caller's tag_path** -- the dataset
prefix is stripped server-side so consumers never see it):

```json
{
  "Big_Canyon/Secondary/Conveyor/C1/Process_Data/Belt_Scale/TPH": {
    "data": [
      {"value": 3,  "quality": "GOOD", "timestamp": "2026-04-30T22:36:06.110Z"},
      {"value": 44, "quality": "GOOD", "timestamp": "2026-05-01T13:29:57.952Z"}
    ]
  }
}
```

Wire shape is **snake_case** (matches `/api/metrics` and
`/api/production-report`). No i3X aliases on this request body.

### Server-side resolution

1. `site_id` query param -> look up the site's `TimebaseClient` in
   the registry (404 if unknown, 503 if it didn't open at startup).
2. Read `client.dataset` (populated from catalog at startup; live in
   the YAML, never on the wire).
3. Compose `<dataset>:<tag_path>` for each input. Strip stray slashes.
4. Build a cache key from the composed elementIds + normalized window.
5. On cache miss, POST to the historian's `/i3x/objects/history`.
6. Re-key the upstream response (which is keyed by composed
   elementId) back to **tag_path** before returning.

### Why YAML, not SQL

The Flow comparison was asymmetric. Flow stores URLs in SQL because
each **tag** has its own URL template (potentially hundreds of rows
with frequent updates). Timebase URLs are per-**site** -- handful of
rows total, changing once a quarter at most. YAML wins on:

* No SQL dependency for Timebase to start.
* Diff visibility on URL changes (source control).
* No extra schema/migration overhead for 2-5 rows.
* `catalog.yaml` is gitignored, so URLs don't leak to the public repo
  (Revision 3).

Lookup is still **server-side and uniform**: every caller (dashboard,
Ignition, etc.) passes `site_id`; the API reads the YAML once at
startup and routes accordingly. No caller passes URLs.

### Changes from Revision 3

* Dropped `POST /api/timebase/history-by-tag` (deleted).
* Dropped `HistoryByTagRequest` schema.
* `HistoryRequest` simplified: snake_case, no i3X aliases, only fields
  are `tag_paths`, `start_time`, `end_time`, `max_depth`.
* `TimebaseClient` gained a `dataset` field, populated by the lifespan
  from `SiteDef.dataset`. The route reads `client.dataset` for
  composition.
* `/history` response keys are now the caller's `tag_path` strings
  (the dataset prefix is stripped server-side via `_rekey_to_tag_paths`).
* No `base_url` accepted from clients anywhere -- all routing goes
  through the catalog.

### SSRF posture

No code path takes a URL from a client. Every historian URL is loaded
from `catalog.yaml` at startup, vetted by code review when added.
The "untrusted base_url" concern from Revision 3 disappears entirely.


## Revision 5 -- per-site asset placement (catalog schema v2, 2026-05-21)

Trey flagged that conveyor placement varies by site: C1 lives in
Secondary at BCQ but might live in Primary at another site. The
schema-v1 catalog put `assets` under `asset_classes.<class>` globally,
which meant `build_response()` duplicated every conveyor under every
department at every site whether it physically existed there or not.

### Schema v2 shape

Per-site asset placement moves the assets list **out** of the shared
asset_classes block and **into** each site's per-department block.
`asset_classes` keeps only metric definitions.

```yaml
sites:
  "101":
    code: BCQ
    base_url: http://10.44.135.12:4511
    dataset: IAP_BCQ_Controls
    departments:
      Secondary:
        prefix: Big_Canyon/Secondary
        assets:
          Conveyor: [C1, C2, C3, C4, C5, C6, C7, C8]

  "100":                                 # future
    code: ARQ
    ...
    departments:
      Primary:
        prefix: Ardmore/Primary
        assets:
          Conveyor: [C1, C2]             # only these at ARQ/Primary
      Secondary:
        prefix: Ardmore/Secondary
        assets:
          Conveyor: [C3, C4, C5, C6, C7, C8]

asset_classes:
  Conveyor:
    metrics:                             # shared; no global assets list
      belt_scale_tph: { ... }
      belt_scale_total: { ... }
```

### Changes from Revision 4

- New `DepartmentDef` dataclass: `name`, `prefix`, `assets: dict[str, tuple[str, ...]]`.
- `SiteDef.departments` changes type from `dict[str, str]` to `dict[str, DepartmentDef]`.
- `AssetClassDef` loses its `assets` field. Becomes a metric registry only.
- `resolve_element_id` validates `asset` against the *department's*
  asset list for the class, not a global per-class list. C1 at ARQ
  in Primary resolves; C1 at ARQ in Secondary correctly errors.
- `build_response._build_department` walks the department's own
  asset map (`dept.assets`), only emitting classes the department
  actually contains. No more phantom Conveyor blocks under empty
  departments.
- Loader cross-validates: every dept-referenced asset_class must exist
  in the global `asset_classes` registry (catches typos at load time).
- Loader rejects the legacy v1 `assets:` key under `asset_classes.<class>`
  with a clear migration message.

### Wire format unchanged

`CatalogResponse` and its nested models (`CatalogSite`, `CatalogDepartment`,
`CatalogAssetClass`, `CatalogAsset`, `CatalogMetric`) stay the same.
The schema bump only changes internal dataclasses and YAML shape;
external API consumers see no difference, just more-honest content.

### Compatibility

Anyone with a schema-v1 `catalog.yaml` gets a `CatalogError` at load
time pointing at the migration:
"asset_classes.<class>.assets is no longer supported (schema v2).
Move per-class asset lists into sites.<id>.departments.<dept>.assets.<class>."
Since the only live catalog is Trey's BCQ-only one and it was already
restructured as part of this change, no migration step needed.

