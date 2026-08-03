# ADR 005 -- Department name from payload Workcenter.Description

**Status:** Accepted, 2026-08-03
**Context:** Phase 33. Supersedes the department-name portion of ADR 003
(the Phase 12 cross-database Departments join).

## Context

The human-readable department label ("Primary", "Secondary",
"Portable 2") shown on the Production Dashboard header, the Production
Charts (`#trends`) left-nav and chart panels, the per-department
rollups, and the XLSX run-report export is carried on
`ProductionReportRow.department_name`. Every one of those surfaces reads
that single field, which is populated once per row in
`SqlProductionReportSource._row_to_dataclass`.

Through Phase 12 the label came from a cross-database LEFT JOIN in
`select_all.sql`:

```sql
LEFT JOIN [DailyProductionEntry].[dbo].[Departments] d
    ON d.[Id] = rr.DEPARTMENT_ID
-- REPLACE(d.[Name], '_', ' ') AS DEPT_NAME
```

The same report payload already carries the department label at
`Metrics.Workcenter.Description` (verified against the canonical
examples: `payload-example-arq.json` -> `"Primary"`,
`payload-example-bcq.json` -> `"Secondary"`). Circuits and lines already
source their labels from their own `Description` fields, so reading the
workcenter label the same way is consistent with existing practice.

## Decision

Resolve `department_name` in Python from
`payload.Metrics.Workcenter.Description` and remove the cross-database
Departments LEFT JOIN entirely.

- New shared resolver
  `app.integrations.production_report.base.workcenter_description(payload)`
  returns the normalized description or `None`. Both the SQL source and
  the CSV test fixture delegate to it, so they resolve identically.
- **Normalization:** underscores -> spaces, then strip. `"_"`, `"None"`,
  and blank are treated as placeholders (return `None`). Mirrors the
  retired SQL `REPLACE('_', ' ')` and the frontend `placeholderize`
  convention.
- **Fallback:** when the resolver returns `None`, the source synthesizes
  `f"Dept {department_id}"`. The dataclass field stays non-null, so no
  downstream surface needs a null check. Current production payloads
  always carry the field, so the fallback is a contract guard, not an
  expected path.
- **Fallback logging (recent-only).** `fetch_rows()` is a parameterless
  full-table scan, so a naive per-row warning re-fires for every legacy
  report on every poll (1-5 min) -- a confirmed log flood, since reports
  predating this change genuinely lack the field. The source therefore
  logs `department_name.workcenter_description_missing` at **WARNING only
  for recent reports** (`prod_date` within `_RECENT_MISSING_WARN_DAYS`,
  default 7 -- a real upstream regression) and at **DEBUG for older
  reports** (expected legacy gap, silent at default level). Decided with
  Trey 2026-08-03 after the flood was observed in the container logs.
  `_is_recent_report()` is a pure, `now`-injectable helper so the window
  is unit-tested deterministically.
- `select_all.sql` drops the `[DailyProductionEntry].[dbo].[Departments]`
  join and the `DEPT_NAME` column. `DEPT_NAME` was the last column, so no
  positional index in `_row_to_dataclass` shifts.

## Consequences

- **No downstream changes.** The field name and type are unchanged, so
  services, routes, Pydantic response schemas, and the frontend are
  untouched. All four label surfaces move together.
- **Cross-database coupling removed.** The API's read-only account no
  longer needs `SELECT` on `[DailyProductionEntry].[dbo].[Departments]`;
  the query is now single-database. (Removing that grant is optional
  cleanup, not required for correctness.)
- **Freshness.** A relabel in the source system now propagates via the
  payload on the next poll, with no join or restart.
- **Label is now per-report free-text.** Rollups lift the name off the
  newest row in each department group (first-seen wins, same as circuit
  descriptions). If `Workcenter.Description` ever drifts across a date
  window, the displayed label could change with the range. Accepted;
  matches the existing circuit/line convention.
- The committed `sample.csv` predates the field, so its fixture rows hit
  the `Dept <id>` fallback. The happy path is covered by unit tests that
  load the canonical `payload-example-{arq,bcq}.json` files and by
  parameterized resolver tests in
  `tests/integrations/test_sql_source.py`.

## Alternatives considered

- **Keep the Departments join as a fallback.** Rejected: the field is
  always present in production, and keeping the join retains the
  cross-database coupling this change is meant to remove.
- **Correct the `Departments` table instead.** Rejected: the payload is
  already the authoritative, per-report source the plant maintains; the
  Departments table was a secondary lookup.
