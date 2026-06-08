# ADR 004 -- Configured run report: EXEC the stored procedure directly

**Status:** Accepted, 2026-06-08
**Context:** Phase 31. See `tasks/todo.md` for the implementation plan.

## Context

Trey wants a button on the Production Charts (trends) page that exports
the same "configured run report" Ignition renders, to a multi-sheet
Excel file (one worksheet per department in the active site, using the
trends page's selected start/end dates).

That report is produced by an existing stored procedure,
`UNS.GET_CONFIGURED_RUN_REPORT(@siteID, @departmentID, @startDate,
@endDate)`. The SP:

- reads `MES.RUN_REPORTS_CONFIG` for the given site + department and
  **dynamically builds its column list** -- which payload JSON paths to
  surface (`CLASS` -> `Site.* / Workcenter.* / <asset>.* / Circuit...`),
  the display name (`DISPLAY_NAME`), and the order (`DISPLAY_ORDER`);
- emits one row per report/shift with fixed pre-columns (Date, Year,
  Month, PROD_ID, Shift, Start/End time), the dynamic payload columns,
  and fixed post-columns (Weather, Avg Temp/Humidity, Wind, Modified By,
  Notes) via joins to `SITE_PRODUCTION_RUN_HISTORY` and
  `SITE_PRODUCTION_RUN_COMMENTS`.

Most of the raw data already flows through the dashboard's existing
payloads (the same `PAYLOAD` JSON), so the question was whether to (a)
reuse an existing route + transform in Python, or (b) call the SP.

## Decision

**EXEC the SP directly** behind a dedicated, isolated vertical slice
(`configured_run_report.sql` -> `ConfiguredRunReportSource` ->
`get_configured_run_report` service -> `/api/production-report/run-report-export`).
Do **not** rebuild it from existing payloads, and do **not** replicate
it as a static query file.

### Why this does not contradict ADR 003

ADR 003 deliberately did the opposite: it replaced an EXEC of
`UNS.GET_PRODUCTION_RUN_REPORTS` with replicated joins in
`select_all.sql`, because that report has a **fixed** shape and sits on
the **hot polling path** (1-5 min), where one EXEC-per-department would
mean N round-trips per `/range`.

This report is the inverse on both axes:

- **Dynamic columns.** The column set is resolved at run time from
  `RUN_REPORTS_CONFIG` per site+department. It *cannot* be expressed as
  a static `SELECT` the way `select_all.sql` was -- replicating it would
  mean reimplementing the SP's config-driven column assembly
  (CLASS->JSON-path mapping, DISPLAY_ORDER, DISPLAY_NAME) in Python.
  That duplicates business logic that lives authoritatively in the DB
  and drifts the moment the config or SP changes. We already have a
  lessons entry about inferring `RUN_REPORTS_CONFIG` (CHART_LABEL)
  semantics wrong -- this is the same footgun, larger.
- **On-demand, not hot path.** This runs on a button click, not the
  poll loop. One EXEC per department (looped server-side) is acceptable
  latency for an export; it is not repeated every 1-5 minutes.

So the principle behind ADR 003 -- "don't pay per-department round-trips
on the hot path, and prefer base-table query files where practical" --
actively points *toward* EXEC here: the hot-path concern doesn't apply,
and a base-table query file isn't even possible for a dynamic column set.

## Consequences

- New isolated path; the polling routes and their caching are untouched.
- The API's read-only SQL account needs `EXECUTE` on
  `UNS.GET_CONFIGURED_RUN_REPORT` (confirmed provisioned). The SP only
  SELECTs, so the read-only posture holds.
- The source is generic: it reads `cursor.description` for the dynamic
  columns rather than mapping a fixed schema. Response carries ordered
  `columns` + parallel `rows` per department.
- No caching (on-demand). Per-call timeout; SP/SQL failure -> 503 so the
  button surfaces an error rather than a blank file.
- A 366-day window cap bounds a year-view pull across all departments.
- If the SP's contract changes (new params, result-set shape), only this
  slice needs updating; nothing else depends on it.
