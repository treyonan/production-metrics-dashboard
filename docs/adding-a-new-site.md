# Adding a new site to the dashboard

Authoritative checklist for commissioning a new plant site in the
production-metrics-dashboard. Use this end-to-end when a new quarry
(or similar) comes online; treat the section order as the order of
operations.

The dashboard reads from three data sources, each of which has to
know about the new site independently before it shows up on the UI:

1. **SQL Server** (`Flow_Curated`) — production-report rows tagged
   with the new `site_id`. Populated externally by the SCADA + Flow
   ETL pipeline; nothing for the dashboard to do here except
   verify the rows arrive.
2. **Flow REST API** — per-tag `history_url` rows in
   `[FLOW].[INTERVAL_METRIC_TAGS]`. Populated automatically by the
   Ignition trigger that subscribes to the new site's MQTT topics
   (`scada/ignition/upsert_interval_metric_tag.py`).
3. **Timebase i3X historian** — per-site catalog in
   `backend/app/integrations/timebase/catalog.yaml`. **This is the
   only one the dashboard owns directly.**

Plus three pieces of cross-cutting configuration that the dashboard
*does* own:

- The site's hostname → IP mapping in `docker-compose.yml`
  (`extra_hosts`).
- The site's human-readable display name in
  `backend/app/core/config.py` (`_DEFAULT_SITE_NAMES`).
- The Timebase catalog entry (see #3 above).

## Before you touch any files

Confirm these are true *before* doing any work. If any of them
isn't, fix that first — editing the dashboard's config to point at
a site that isn't actually reachable just buries the failure later
in the chain.

| Check | How to verify | What to do if it fails |
|---|---|---|
| **Network reachability** from the prod server to the new plant box on **port 4501** (Flow REST) | `nc -zv <sitehost> 4501` or `curl -m 5 http://<sitehost>:4501/` from the prod shell | Corporate firewall / VLAN routing. Open the path before continuing. |
| **Network reachability** on **port 4511** (Timebase i3X) | `nc -zv <sitehost> 4511` or `curl -m 5 http://<sitehost>:4511/v2/namespaces` | Same — firewall / routing. |
| **Hostname pattern** — confirm the new plant box follows the `dbp-<sitecode>` convention | Ask the network team or grep an existing site's host record | If the convention is broken, you have two choices: use a non-`dbp-` hostname (works but breaks the pattern) or get the hostname renamed. Stick with the convention if at all possible. |
| **SQL production-report rows** are arriving with the new `site_id` | `SELECT TOP 5 * FROM <production_report_view> WHERE Site_ID = '<new_id>' ORDER BY ProductionDate DESC` | Talk to whoever owns the SCADA → Flow → SQL pipeline; the dashboard is purely a consumer here. |
| **Flow interval-metric tags** are populated for the new site | `SELECT TOP 5 * FROM [FLOW].[INTERVAL_METRIC_TAGS] WHERE site_id = '<new_id>'` | Make sure the Ignition project at the new site subscribes to the MQTT topics and runs the upsert script. See `scada/ignition/`. |
| **SCADA tag tree** at the new site follows the convention | Browse the new site's tags in Ignition Designer or `curl http://<sitehost>:4511/v2/elements?path=<DataSet>:&maxDepth=4` | Tag suffixes (e.g. `Process_Data/Belt_Scale/TPH`) MUST match the existing sites' convention. If they don't, you'll need to extend `catalog.yaml`'s `asset_classes` registry — see "Tag-tree divergence" in Troubleshooting below. |
| **Dataset name** at the new site follows `IAP_<sitecode>_Controls` | Browse the i3X namespace list: `curl http://<sitehost>:4511/v2/namespaces` | If it's named differently, fine — just record the actual name in `catalog.yaml`'s `dataset:` field. The dataset name doesn't have to follow the convention; it just has to be accurate. |

## Files to update

The dashboard needs three changes for a new site. All three are
committed and ship via `git`. There is no per-environment config
to keep in sync any more.

| File | What changes | Committed? | Rebuild required? |
|---|---|---|---|
| `docker-compose.yml` | Add a line under `services.api.extra_hosts` mapping the new hostname → IP. | Yes | Yes — `docker compose up -d` recreates the container; `restart` does NOT pick up `extra_hosts` changes. |
| `backend/app/integrations/timebase/catalog.yaml` | Add a top-level entry under `sites:` for the new site. | Yes | **No** for pure catalog edits — file is bind-mounted by `docker-compose.yml`, so `docker compose restart api` picks up the change. For new-site commissioning specifically, you're also touching `extra_hosts` + `config.py`, so a rebuild is unavoidable for that combined deploy. See "Catalog hot-swap" below. |
| `backend/app/core/config.py` | Add the new `<site_id>: "<Display Name>"` entry to `_DEFAULT_SITE_NAMES`. This is what the site dropdown shows. | Yes | Yes (Python code change). |

### Catalog hot-swap

`catalog.yaml` is bind-mounted into the container by `docker-compose.yml`:

```yaml
volumes:
  - ./backend/app/integrations/timebase/catalog.yaml:/app/backend/app/integrations/timebase/catalog.yaml:ro
```

That means a catalog edit on the host takes effect on:

```
docker compose restart api
```

No image rebuild, no other downtime. The restart re-runs the
lifespan, which re-reads `catalog.yaml` and rebuilds the per-site
Timebase client registry. The full route + frontend stack keeps
its bytecode warm — restart-to-serving is typically a few seconds.

**Must-exist constraint:** `catalog.yaml` is committed, so a normal
`git clone` / `git pull` brings the live file with it. If anyone
manually deletes it on the host while the container is down,
`docker compose up` would silently create an empty *directory* at
the bind-mount target and the loader would crash. Treat
`catalog.yaml` like any other tracked source file -- don't delete
it locally.

Other paths that **still** require a rebuild:

| Change | Why |
|---|---|
| `docker-compose.yml` `extra_hosts` | `restart` does not re-read compose's `extra_hosts`; only `up -d` recreates the container with new `/etc/hosts`. |
| Python source (`config.py`, route handlers, etc.) | Python code is baked into the image; uvicorn doesn't run with `--reload` in the container. |
| `requirements.txt` | New dependencies aren't installed at runtime. |

`frontend/`, `context/`, and `catalog.yaml` are the three paths
that hot-swap.

## Step-by-step procedure

Walk these in order. Each step is small enough that you can roll back
just that step if it doesn't go cleanly.

### 1. Pick the site identifiers

You'll need three values that stay consistent across all the files
below:

- **`site_id`** — the string that flows through SQL and the API. Three
  digits, matches whatever the SCADA pipeline already uses (e.g. `"100"`,
  `"101"`). Talk to whoever runs the SCADA side; the dashboard is the
  follower here, not the leader.
- **`code`** — short site code (3–4 chars), e.g. `BCQ`, `ARP`. Used in
  the site dropdown chip and in the Time Series export filename.
- **`hostname`** — the corporate hostname of the plant box, ideally
  following the `dbp-<lowercased-code>` convention (e.g. `dbp-arp`).

### 2. Update `docker-compose.yml`

Add one line under `services.api.extra_hosts`:

```yaml
extra_hosts:
  - "dbp-bcq:10.44.135.12"         # site 101 (Big Canyon Quarry)
  - "dbp-arp:10.44.x.x"            # site 100 (Ardmore Quarry)   <-- new
```

Commit this. Same line works for both dev and prod — `extra_hosts` is
checked into git.

### 3. Update `backend/app/core/config.py`

Add the new site to `_DEFAULT_SITE_NAMES`:

```python
_DEFAULT_SITE_NAMES: dict[str, str] = {
    "100": "Ardmore Quarry",        # <-- new
    "101": "Big Canyon Quarry",
}
```

Commit this. Order within the dict doesn't matter; alphabetize by
display name for tidiness.

### 4. Update `catalog.yaml`

`catalog.yaml` is committed. Edit it on dev, commit alongside the
other site-commissioning changes, and `git pull` brings it to prod.
No per-environment copy to maintain.

Add a top-level entry under `sites:`:

```yaml
sites:
  "101":
    code: BCQ
    display_name: Big Canyon Quarry
    base_url: http://dbp-bcq:4511
    dataset: IAP_BCQ_Controls
    departments:
      Secondary:
        prefix: Big_Canyon/Secondary
        assets:
          Conveyor: [C1, C2, C3, C4, C5, C6, C7, C8]

  "100":                              # <-- new
    code: ARP
    display_name: Ardmore Quarry
    base_url: http://dbp-arp:4511     # hostname, NOT IP
    dataset: IAP_ARP_Controls
    departments:
      Primary:
        prefix: Ardmore/Primary
        assets:
          Conveyor: [C1, C2]
      Secondary:
        prefix: Ardmore/Secondary
        assets:
          Conveyor: [C3, C4, C5, C6, C7, C8]
```

Conveyor placement (which department each conveyor lives in) is
per-site — figure it out from the SCADA tag tree. The example above
shows what to do when the same conveyor number sits in different
departments at different sites; the full `elementId` is
dataset+prefix-scoped so the numbers don't collide.

`base_url` MUST use the hostname form, not the raw IP. The container
resolves the hostname via the `extra_hosts` line you added in step 2;
using the IP directly works but breaks the pattern Flow already uses
and gives you two places to update if the IP ever changes.

### 5. Rebuild + restart

From the repo root:

```
docker compose down
docker compose up --build -d
```

`up --build` is required because:
- `extra_hosts` changes only land on a container *recreate*, not a
  `restart`.
- `config.py` is a Python code change, which always requires a rebuild
  (no Python hot-reload in the container).

`catalog.yaml` is bind-mounted, so it would normally only need a
`docker compose restart api`. But for *new-site commissioning* you're
also editing `extra_hosts` and `config.py`, so a full rebuild is
unavoidable. Once the site is live and you're tweaking only the
catalog (renaming an asset, moving a conveyor between departments,
adding a metric), `docker compose restart api` is enough.

### 6. Smoke tests

In this order — each step verifies one layer of the chain. If layer N
passes but N+1 fails, you know exactly which file is wrong.

**Layer 1: Sites endpoint sees the new site**
```
curl http://localhost:8001/api/sites
```
Look for `"site_id": "<new_id>"` with the right `display_name`. If
missing, the `_DEFAULT_SITE_NAMES` change didn't deploy.

**Layer 2: Health endpoint says the new site's historian is up**
```
curl http://localhost:8001/api/health
```
Look for a `timebase:i3x:<new_id>` source with `ok: true`. If `ok: false`
with a DNS error → `extra_hosts` is wrong. If `ok: false` with a connection
error → `base_url` port is wrong or the firewall is blocking 4511.

**Layer 3: Timebase catalog endpoint returns the new site's tags**
```
curl http://localhost:8001/api/timebase/catalog/<new_id>
```
Look for the departments and assets you declared in `catalog.yaml`.
If absent or wrong, your `catalog.yaml` edit didn't make it into the
container — confirm with `docker compose exec api cat /app/backend/app/integrations/timebase/catalog.yaml`.

**Layer 4: Production-report endpoint returns data for the new site**
```
curl "http://localhost:8001/api/production-report/latest?site_id=<new_id>"
```
If empty, SQL doesn't have rows yet for the new `site_id` — that's a
SCADA pipeline issue, not a dashboard issue.

**Layer 5: Interval-metrics endpoint sees the new site's tags**
```
curl "http://localhost:8001/api/metrics/conveyor/subjects?site_id=<new_id>"
```
If empty, `[FLOW].[INTERVAL_METRIC_TAGS]` doesn't have rows — the
Ignition upsert script isn't running at the new site, or the new
site's MQTT topics aren't being subscribed.

**Layer 6: Browser smoke test**
Open the dashboard. The new site should appear in the topbar's site
toggle. Click it; the dashboard should render production-report data
(if SQL has it), and the Time Series page should let you pick the new
site and see Belt Scale TPH / Total tags.

## Troubleshooting

### `Cannot reach Timebase site <id>: ConnectError: [Errno -2] Name or service not known`

The container can't resolve the hostname. Walk this list:

1. Does `catalog.yaml`'s `base_url` actually use the hostname (not
   the IP)?
   ```
   docker compose exec api cat /app/backend/app/integrations/timebase/catalog.yaml | grep base_url
   ```
2. Does `/etc/hosts` inside the container have the mapping?
   ```
   docker compose exec api cat /etc/hosts | grep dbp-
   ```
   If the entry is missing, you ran `docker compose restart` instead of
   `docker compose up -d`. `restart` does NOT pick up `extra_hosts`
   changes — the container has to be recreated.
3. Does Python's resolver agree?
   ```
   docker compose exec api python -c "import socket; print(socket.gethostbyname('dbp-<sitecode>'))"
   ```

### `/api/health` shows Timebase as down and the lifespan log says `timebase.catalog_load_failed`

`catalog.yaml` either isn't reaching the container or is malformed.
Check both:

```
docker compose exec api ls -la /app/backend/app/integrations/timebase/catalog.yaml
docker compose exec api cat /app/backend/app/integrations/timebase/catalog.yaml | head -20
docker compose logs api 2>&1 | grep timebase.catalog_load_failed
```

If `ls` shows the file as a *directory* (0-byte, weird), the host
file was missing when `docker compose up` ran and Docker created an
empty directory at the bind-mount target. Fix: restore
`catalog.yaml` from git (`git checkout backend/app/integrations/timebase/catalog.yaml`),
then `docker compose down && docker compose up -d` to remount.

If the file content looks wrong (corrupted, empty, or missing
required fields), the lifespan log will say which key failed
validation. Fix in the host file and `docker compose restart api`.

### Tag-tree divergence — the new site's tag suffixes don't match

The `asset_classes.<class>.metrics.<key>.suffix` field is currently
shared across every site (e.g. all conveyors expose
`Process_Data/Belt_Scale/TPH`). If the new site has a different layout —
say, Belt Scale lives at `Sensors/Belt/TPH` instead of
`Process_Data/Belt_Scale/TPH` — you have two options:

1. **Best**: get the new site's SCADA team to bring the tag tree into
   convention. This is a one-time pain that pays back forever — the
   shared registry stays clean.
2. **Compromise**: add a per-site suffix override capability to the
   catalog (not implemented today; would be a schema v3 change). Don't
   do this for one site; do it only if multiple sites need it.

### `/api/health` shows the new site as `ok: false` but the IP IS reachable from the host

The container's network is different from the host's. The container
reaches the plant box via the Docker bridge network, not the host's
network stack directly. If `ping <sitehost>` works from the host but
not from `docker compose exec api ping <sitehost>`, the issue is
either:

1. `extra_hosts` isn't set (see DNS troubleshooting above), or
2. The Docker bridge network can't route to the plant subnet. This is
   a Linux networking concern, usually solved by enabling
   `network_mode: host` in compose (last resort — breaks port
   isolation) or by configuring the host's iptables to NAT the
   container's outbound traffic. Talk to whoever owns the prod server.

## Related references

- `docker-compose.yml` — `extra_hosts` block (and its comment).
- `backend/app/integrations/timebase/catalog.yaml` — header documents
  the schema (sites + departments + asset placement), the URL
  convention, and editing patterns for the three common cases (add
  metric, add asset, move asset between depts).
- `RUNBOOK.md` § "Adding a new site" — short pointer back to this doc.
- `CLAUDE.md` § "Where new content goes" — conventions for where new
  config and code live in the repo.
