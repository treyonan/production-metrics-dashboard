# `scada/ignition/` — SCADA-side companion scripts (Ignition)

This folder holds Jython 2.7 scripts that run inside Ignition (Designer
or Gateway scope), not inside our FastAPI. They're versioned here for
review + diff history alongside the API code; the actual deployment
copy lives inside an Ignition project's Library Script package.

## Why this folder exists

The interval-metrics architecture (see `docs/data-flows.md` Domain 2)
deliberately keeps MQTT subscription out of the FastAPI. The discovery
side -- "which tags exist, what URL serves their history" -- lives in
Ignition because Ignition is already subscribing to Flow's MQTT topics
for other plant purposes. A trigger on each value-change message
upserts a row into `[FLOW].[INTERVAL_METRIC_TAGS]` on the enterprise
SQL server; our FastAPI then reads that table to drive interval-metric
queries.

This folder is the source of truth for the trigger's logic. Copy the
function bodies into Ignition Designer's project library; commit
changes here when you change the deployed copy.

## Files

| File | Purpose |
|---|---|
| `upsert_interval_metric_tag.py` | The MERGE function. Called on every Flow value-change MQTT message; idempotent. |

## Deployment workflow

1. Open Ignition Designer for the gateway that subscribes to Flow.
2. Project Library → create / open a script package `IntervalMetrics`
   (the package name in the docstring's Usage example).
3. Paste the function from `upsert_interval_metric_tag.py` into the
   package. Save.
4. Wire the trigger: a tag change script on the Cirrus Link MQTT
   Engine tag holding the Flow payload, or an MQTT message handler,
   or a transaction group -- whichever your shop standardizes on.
5. The trigger calls
   `IntervalMetrics.upsert_interval_metric_tag(payload, site_id, department_id, ...)`
   per message.

## Required prerequisites

- Ignition database connection named `IA_ENTERPRISE` (or pass a
  different `database=` argument).
- `[FLOW].[INTERVAL_METRIC_TAGS]` table created. DDL is at the top of
  `upsert_interval_metric_tag.py` and in `docs/data-flows.md`.
- A site/department lookup mechanism on the SCADA side (the trigger
  has to translate `modelAttributes.Site` text → numeric site_id, and
  `modelAttributes.Conveyor_Number` → department_id, before calling
  the upsert).

## Why this lives here, not in `backend/`

The script runs in Ignition's Jython runtime, not in our FastAPI's
Python 3.12 venv. They share nothing at runtime -- different process,
different language version, different database access pattern. The
two sides communicate via the SQL table, which is the contract.

Putting the script under `scada/ignition/` makes the boundary
explicit: anything in `backend/` runs in our FastAPI, anything in
`frontend/` runs in the browser, anything in `scada/` runs in the
SCADA stack.
