# Adding a new site — checklist

Walk this top to bottom when commissioning a new plant. Every step has a
single-line explanation; everything else lives in the file being touched.

## 1. Identifiers + credentials to gather first

| Thing | Example | Where it comes from |
|---|---|---|
| `site_id` | `"100"` | SCADA pipeline (must match what's already in SQL) |
| `code` | `ARQ` | Short site code, 3 chars, MUST share letters with hostname |
| `hostname` | `dbp-arq` | Network team — corporate hostname for the plant box |
| Plant box IP | `10.40.135.12` | `ping <hostname>` from a Windows host |
| Flow bearer token | (opaque string) | Flow admin UI at the new site |
| Timebase dataset name | `IAP_ARQ_Controls` | `curl http://<hostname>:4511/v2/namespaces` |

**Naming rule:** hostname letters and `code` letters must match (`dbp-arq` ↔ `ARQ`).
Don't mix them.

## 2. Pre-flight (verify before editing files)

```bash
nc -zv <hostname> 4501             # Flow REST port reachable
nc -zv <hostname> 4511              # Timebase i3X port reachable
curl http://<hostname>:4511/v2/namespaces   # dataset name appears
```

```sql
SELECT TOP 5 * FROM <production_report_view> WHERE Site_ID = '<id>';
SELECT TOP 5 * FROM [FLOW].[INTERVAL_METRIC_TAGS] WHERE site_id = '<id>';
```

If any of these fail, fix the upstream first. The dashboard can't fabricate
data that isn't reaching SQL / Flow / the historian.

## 3. Files to update

### Committed (ships via `git pull`)

| File | What it controls | Add |
|---|---|---|
| `docker-compose.yml` | Container `/etc/hosts` mapping so `httpx` can reach the plant box | One line under `services.api.extra_hosts`: `- "<hostname>:<ip>"` |
| `backend/app/core/config.py` | Site display name + Flow API key field declaration | (a) `_DEFAULT_SITE_NAMES["<id>"] = "<Display Name>"` — controls the dropdown label and the no-deep-link default (insertion order matters). (b) New `flow_api_key_<id>: SecretStr` field with `AliasChoices("PMD_FLOW_API_KEY_<id>", "FLOW_API_KEY_<id>")` so the env var is picked up. |
| `backend/app/integrations/timebase/catalog.yaml` | Timebase historian config: base_url, dataset, department + asset placement | Top-level entry under `sites:` with hostname-form `base_url`, dataset name, and per-department asset map. **Bind-mounted at runtime — pure catalog edits restart-only after commissioning.** |
| `frontend/app.js` — `EXTERNAL_LINKS_CHARTS` | Charts ▾ dropdown entries (Flow dashboards) | For each chart entry that exists at the new site, add `"<id>": "<flow-url>"` to its `urls` dict. Omit per-entry if that chart doesn't exist at this site. |
| `frontend/app.js` — `EXTERNAL_LINKS_FORMS` | Forms ▾ dropdown entries (Flow operator forms) | Same pattern as Charts. Add per-site URLs only where the form exists at the new site. |

### Per-environment (NOT committed, lives in `backend/.env` on each deployment)

| Variable | Purpose | Required? |
|---|---|---|
| `PMD_FLOW_API_KEY_<id>=<token>` | Bearer token for the new Flow installation. Each Flow installation has its own. | Yes if you want `/api/metrics/*` for this site to work |

`PMD_FLOW_API_KEY` (no suffix) still works as a fallback default. Drop it
once every site has its own explicit key, for clarity.

### Auto-populated (no action — just verify in pre-flight)

| Source | What | How |
|---|---|---|
| `[UNS].[SITE_PRODUCTION_RUN_REPORTS]` | Per-shift production reports (JSON payloads). The dashboard reads this for every Production Dashboard / Production Charts panel. | SCADA → Flow → SQL pipeline. Each shift wraps a report and writes one row. Nothing for the dashboard to do; the pre-flight `SELECT TOP 5 ... WHERE Site_ID = '<id>'` verifies it. |
| `[FLOW].[INTERVAL_METRIC_TAGS]` | One row per (site, asset, metric, interval) tag. The dashboard reads this to discover which interval-metric tags exist for each site. | Ignition's `upsert_interval_metric_tag` script fires on every Flow MQTT message at the new site. First publish = first row. |

### Optional: per-site chart label overrides

Each chart panel has a **title** (the bold header, e.g. `TOTAL TONS
FED`) and a **formula expression** rendered just under it (e.g.
`C1+C8-C7`). Only the **title** is resolved per-site from
`[IA_ENTERPRISE].[MES].[RUN_REPORTS_CONFIG]`. The formula always
renders as the raw conveyor expression — it describes the
calculation, not the display name, so it's never relabeled.

Title resolution order:

1. `(site_id, department_id, class, asset, column_name)` — exact match → use that row's `CHART_LABEL`
2. `(0, 0, class, asset, column_name)` — global fallback row
3. Raw metric key (`Total`, `Rate`, ...) — safety net so the chart still renders

**Most new sites need NO chart-label work** — the global fallback row
(`SITE_ID = 0, DEPARTMENT_ID = 0`) covers the standard metric titles
already.

INSERT into `MES.RUN_REPORTS_CONFIG` ONLY when the new site needs a
*different* CHART_LABEL title than what the global fallback provides
for the same `(class, asset, column_name)` tuple. (Example: BCQ's
"Total" metric is titled `TOTAL TONS FED`; if Ardmore's `Total`
should read differently, INSERT an Ardmore-specific row.) INSERT-only
rollout — no API change, no rebuild. Picked up on the dashboard's
next 5-minute label-cache refresh, or immediately on
`docker compose restart api`.

The sibling dictionary tables are `[IA_ENTERPRISE].[MES].[REPORT_COLUMN_CONFIG]`
(metric keys: Total / Rate / Yield / ...) and
`[IA_ENTERPRISE].[MES].[REPORT_ASSET_CLASSES]` (scope enum: Workcenter
/ Circuit / Circuit_Line_A / ...). Only touch those when introducing
genuinely new metric keys or asset classes — rare, and a SCADA-side
schema decision, not a dashboard one.

The API's SQL login MUST hold SELECT on all three tables.

## 4. Deploy

```bash
git pull                           # dev: commit + push; prod: pull
# Edit backend/.env locally to add the per-env Flow key:
#   PMD_FLOW_API_KEY_<id>=<token>
docker compose down
docker compose up --build -d
```

`up --build -d` is required for commissioning because **all three** of these
landed: `extra_hosts` (only picked up on recreate), Python code change in
`config.py`, and `.env` change (read at container start).

Catalog-only edits *after* the site is live = `docker compose restart api`,
no rebuild. The catalog is bind-mounted.

## 5. Smoke tests (in order)

Each step verifies one layer. If N+1 fails after N passed, you know which
file is wrong.

```bash
# 1. Sites endpoint sees the new site
curl http://localhost:8001/api/sites | grep '<id>'

# 2. Health shows the Timebase historian for the new site is reachable
curl http://localhost:8001/api/health | grep '<id>'

# 3. Catalog endpoint shows the configured assets
curl http://localhost:8001/api/timebase/catalog/<id>

# 4. Container resolves the new hostname
docker compose exec api python -c "import socket; print(socket.gethostbyname('<hostname>'))"

# 5. Production-report data flows (or empty for new sites with no data yet)
curl "http://localhost:8001/api/production-report/latest?site_id=<id>"

# 6. Interval-metric tags are discoverable
curl "http://localhost:8001/api/metrics/conveyor/subjects?site_id=<id>"

# 7. Browser end-to-end
#    - Site appears in the topbar dropdown
#    - Deep-link works: /?site_id=<id>
#    - Time Series page Site dropdown lists the new site
#    - Chart titles render the friendly CHART_LABEL (e.g. "TOTAL TONS FED")
#      rather than raw metric keys ("Total") -- confirms MES.RUN_REPORTS_CONFIG
#      resolution is reaching the dashboard. The formula line ("C1+C8-C7")
#      stays as the raw expression by design.
```

## 6. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| `[Errno -2] Name or service not known` from any source | `extra_hosts` missing in compose, or you ran `restart` instead of `up -d` | Add the line; `docker compose down && up -d`. |
| `/api/timebase/catalog` returns `historian.example.invalid:4511` for the new site | catalog.yaml not edited / not picking up | Verify the file in the container: `docker compose exec api cat /app/backend/app/integrations/timebase/catalog.yaml` |
| `401 Unauthorized` from Flow | Wrong bearer token, or no `PMD_FLOW_API_KEY_<id>` in `.env` for this site | Add / fix the token in `.env`, `docker compose down && up -d`. Logs say `flow_client.created` with `per_site_key_sites=[...]`. |
| `404 Unknown Timebase site_id` | catalog.yaml has no `sites."<id>"` block | Add the block, restart. |
| `/api/sites` doesn't list the new site | `_DEFAULT_SITE_NAMES` missing the entry **and** no SQL data exists yet | Add the entry to `config.py`; rebuild. |
| Tag tree returns empty data | Department prefix or asset placement in catalog doesn't match the actual SCADA path | `curl http://<hostname>:4511/v2/elements?path=<dataset>:&maxDepth=4` and align catalog.yaml to what you see |
| Chart titles show raw metric keys (`Total`, `Rate`) instead of friendly names (`TOTAL TONS FED`, etc.) | New site has no matching row in `MES.RUN_REPORTS_CONFIG` and the global `(0, 0)` fallback row is also absent or has `ACTIVE = 0` / `RETIRED = 1` | Verify the global fallback row exists first (`SELECT * FROM ... WHERE SITE_ID = 0 AND DEPARTMENT_ID = 0 AND ACTIVE = 1 AND RETIRED = 0`); if you want a site-specific title, INSERT with the new SITE_ID. Wait up to 5 min for TTL or `docker compose restart api`. (Formula expressions like `C1+C8-C7` are NOT affected by this table — they always render raw.) |

## 7. Related references

- `docker-compose.yml` — extra_hosts block + bind-mount block + their comments
- `backend/app/integrations/timebase/catalog.yaml` — header documents the schema and editing patterns
- `backend/.env.example` — documents the per-site Flow key env var pattern
- `RUNBOOK.md` — operational reference (URLs, troubleshooting, etc.)
