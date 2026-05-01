# Production_Metrics -- Ignition Perspective view

A small demo view that exercises the rich API client at
`scada/ignition/api.py`. Renders the latest end-of-shift production
reports for one site as a Perspective Table, with a site_id input
that updates the data live.

## What it shows

- Title bar.
- A `site_id` numeric entry field bound to `view.custom.siteId` (defaults to 101).
- A status line showing the count of workcenters reporting and the
  envelope's `generated_at` timestamp.
- A filterable Table bound to
  `MES.Integrations.Production_Metrics.API.production_report_latest_dataset(site_id)`.
- Auto-refreshes every 30 seconds via the `runScript` binding's
  polling rate.

## Prerequisites

1. The rich client at `scada/ignition/api.py` is installed in the
   Ignition Project Library at
   `MES.Integrations.Production_Metrics.API`.
2. The Ignition gateway can reach the FastAPI host
   (default `https://productionmetrics.dolese.rocks`).

## Install -- file system path (recommended)

1. Locate your Ignition project folder on the gateway:
       <ignition-install>/data/projects/<your-project>/
2. Create the directory:
       com.inductiveautomation.perspective/views/Production_Metrics/
3. Copy `view.json` and `resource.json` from this folder into it.
4. In Designer, **Project -> Update Project** (or just close and
   reopen the project). The new view appears under
   Perspective -> Views -> Production_Metrics.

## Install -- Designer paste path

1. In Designer, Project Browser -> Perspective -> Views -> right
   click -> New View. Name it `Production_Metrics`. Pick any
   layout; we'll overwrite it.
2. Open the new view, switch to JSON view (View menu -> JSON, or
   Ctrl-Shift-J in some builds).
3. Paste the contents of `view.json` over what's there. Save.
4. Switch back to designer view -- the components should render.

## Adjusting

- **Site default**: `custom.siteId` at the top of `view.json` is
  the initial site_id. Change to your default site or remove and
  pre-populate the input.
- **Refresh rate**: the `30` argument inside each `runScript(...)`
  call is the polling interval in seconds. Set to `0` to disable
  auto-refresh and use a manual button binding instead.
- **API path**: if you installed the client under a different
  Project Library path (e.g. `PMD.api` instead of
  `MES.Integrations.Production_Metrics.API`), search-replace that
  string in `view.json`.

## Extending

- Add a second Table bound to
  `MES.Integrations.Production_Metrics.API.metric_subjects_dataset("workcenter", siteId)`
  to show the interval-metric tag inventory side by side.
- Bind a Power Chart's data series to
  `metric_history_dataset("workcenter", "shiftly", siteId, fromDate, toDate, subject_id, metric)`
  with date-picker components writing to view.custom.fromDate and
  view.custom.toDate.
