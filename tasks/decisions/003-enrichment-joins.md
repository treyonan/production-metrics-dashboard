# ADR 003 -- Weather / notes enrichment: joins, icon layer, rendering

**Status:** Accepted, 2026-04-24
**Context:** Phase 8. See `tasks/todo.md` for the implementation plan.

## Context

Operators and plant engineers need more context next to each
production-report row than OEE numbers alone provide. Two pieces are
available in adjacent SQL tables:

- `[UNS].[SITE_PRODUCTION_RUN_HISTORY]` -- per-shift metadata
  (SHIFT identifier) plus weather aggregates (WEATHER_CONDITIONS,
  AVG_TEMP, AVG_HUMIDITY, MAX_WIND_SPEED). `WEATHER_CONDITIONS` is a
  STUFF-concatenated list of distinct conditions that occurred during
  the shift, e.g. `"broken clouds, clear sky, light rain"`.
- `[UNS].[SITE_PRODUCTION_RUN_COMMENTS]` -- free-form `NOTES` per
  production run.

A third-party stored procedure
`[UNS].[GET_PRODUCTION_RUN_REPORTS](@WORKCENTER, @STARTDATE, @ENDDATE)`
already joins these tables for another internal consumer. A fourth
table `[IA].[WEATHER_DATA]` carries per-observation weather readings
(including an `icon_code`) used as the upstream for the HISTORY
aggregates; our dashboard does not read it directly.

## Decisions

### D1. Replicate the SP's joins in our own query

Option B in the design conversation. `select_all.sql` now selects 13
columns with two LEFT JOINs (HISTORY, COMMENTS) instead of the prior
7-column base-table SELECT. Reasons:

- Phase 3 pattern: our query files under `integrations/production_report/
  queries/` read base tables directly. A second query file with joins
  fits that pattern.
- One round-trip per `/range`. The SP requires a single `@WORKCENTER`
  parameter, which would force N round-trips per request (one per
  department present in the window) -- 4-11 round-trips per /range
  call at current site cardinality.
- The SP's SELECT is missing four columns we need (ID, SITE_ID,
  DEPARTMENT_ID, DTM) because it was written for a per-workcenter
  consumer. Using it would require either DBA modification or a
  merge-on-PROD_ID step; both add complexity.

**Duplication risk:** the JOIN logic now lives in two places (the SP
and our query file). The comment at the top of `select_all.sql` names
the SP as the canonical reference so a future maintainer knows where
to check for drift. The tables involved don't change often; drift
surface is small. If we ever want to collapse the duplication fully,
the cleanest path is asking the DBA to add ID/SITE_ID/DEPARTMENT_ID/DTM
to the SP's SELECT, then EXEC'ing it from our source -- captured as a
follow-up rather than blocking this phase.

**Divergence from the SP:** the SP uses INNER JOIN against HISTORY,
which silently drops reports without a history row. Our query uses
LEFT JOIN on both HISTORY and COMMENTS so every report is returned;
missing joins report NULL weather / NULL notes. Matches the existing
"fetch every row" semantics of Phase 3's `select_all.sql`.

### D2. Enrichment fields are optional on the dataclass + wire

`ProductionReportRow` gains six optional fields, all defaulted to
`None`: `shift`, `weather_conditions`, `avg_temp`, `avg_humidity`,
`max_wind_speed`, `notes`. `ProductionReportEntry` mirrors them.
Reason: the CSV source has no weather data (sample file only has base
table columns), and SQL LEFT JOIN misses produce NULL. Defaulting to
`None` keeps the two source implementations compatible with no
per-row branching in services.

### D3. Single shared details modal for both panel types

One Details modal component serves both single-report panels (a
button next to the status pill) and multi-report panels (a button in
a dedicated Details column of the history table). Reasons:

- One interaction model for users -- same click, same content.
- One component to implement, style, and maintain.
- ESC-to-close, click-outside-to-close, and focus restoration all
  specified in one place.
- Scales cleanly when a future field (link, attachment, reference)
  lands -- add it to the modal rather than wrangle a new column or
  header slot.

### D4. Weather icon: severity-ranked pick from WEATHER_CONDITIONS

STUFF'd conditions like `"broken clouds, clear sky, light rain"` make
a single-icon summary non-trivial. We pick the **worst** (most
operationally impactful) condition in a fixed severity ranking and
show that icon in the history table cell and in the panel header
chip row. Rationale:

- Operators care about adverse weather. A shift that had rain at any
  point is operationally a "rain shift," not a "clear day" even if
  most of the shift was clear.
- The full condition list is preserved in the Details modal under
  "All conditions: …" so nothing is hidden, just prioritized.

Severity order, worst to best:
`thunderstorm / tornado / squall` > `heavy rain / extreme rain` >
`rain / moderate rain / shower rain` > `light rain / drizzle` >
`snow / sleet` > `mist / fog / haze / smoke / dust / sand` >
`overcast` > `broken clouds` > `scattered clouds` > `few clouds` >
`clear sky`.

11 buckets; each has an inline SVG at 14x14 (stroke-only with
currentColor so icons track the light/dark theme). Unknown phrasing
logs a `console.warn` once per unique string and falls back to no
icon (text-only summary).

### D5. Icon source: WEATHER_CONDITIONS text, not icon_code from WEATHER_DATA

`[IA].[WEATHER_DATA]` carries `icon_code` per observation, but since
`WEATHER_CONDITIONS` in HISTORY already contains the condition
phrases we need to match against, we don't need to join the
per-observation table. Joining it would (a) couple our query to a
second schema and (b) force a "which observation represents this
shift" decision in SQL that really belongs wherever the HISTORY
aggregation runs. If `WEATHER_CONDITIONS` phrasing ever changes or
loses fidelity, the fallback is to ask the DBA to add an
`ICON_CODE` aggregate column to HISTORY -- cheaper than rerouting
through WEATHER_DATA.

### D6. Export: same sheet, six tail-appended columns

The XLSX asset-row sheet grows from 13 to 19 columns: `Shift`,
`Weather Conditions`, `Avg Temp`, `Avg Humidity`, `Max Wind`,
`Notes` tail-appended. Asset rows from the same report share the
same enrichment values, so weather/notes repeat across a workcenter's
assets -- accepted as the cost of keeping a single flat sheet. Pivot
in Excel to collapse if needed.

Export reads from the `_lastPayload` envelope, not the DOM, so the
icon rendering choice is independent of the exported data: users
get the raw condition text in the xlsx regardless of how it's
rendered on screen.

## Consequences

Positive:
- Operators see weather + shift in the same scan as OEE, at a glance
  via the icon, full detail on demand via the modal.
- No DBA coordination required to ship.
- The frontend icon layer is swappable: if we later switch to
  `ICON_CODE` from HISTORY or WEATHER_DATA, we just change which
  field populates `entry.weather_icon` (or swap the picker logic);
  the rendering API stays the same.
- The modal pattern is reusable for any future per-report detail.

Negative:
- Duplicated JOIN logic between our query file and the SP -- flagged
  in `select_all.sql`'s top comment; drift is a real possibility.
- Export grows wider (19 columns vs 13). Users who only want OEE
  will have to ignore the right-hand columns.
- Severity ranking is opinionated. A site that prioritizes humidity
  over temperature (aggregates, stockpile moisture) or wind (crusher
  dust regimes) might want a different weighting -- we'd make the
  ranking configurable then.
- Unknown `WEATHER_CONDITIONS` phrasing reaches the `console.warn`
  path but doesn't surface in the UI; maintainers have to check the
  console. Acceptable today given tight condition vocabulary.

## Alternatives considered

- **EXEC the SP directly** -- rejected because of the missing-columns
  problem (ID / SITE_ID / DEPARTMENT_ID / DTM) and the N-round-trip
  shape. Would be revisited if the DBA adds those columns to the SP's
  SELECT.
- **Table-valued function in place of the SP** -- cleanest DRY
  solution but a larger DBA refactor than we can schedule inline with
  this phase.
- **`CROSS APPLY` `[IA].[WEATHER_DATA]` for icon_code** -- rejected
  because it couples our query to a second schema and forces a
  business-logic decision ("which observation represents this shift?")
  in SQL. Frontend severity-picking from `WEATHER_CONDITIONS` gives
  equivalent UX with no SQL coupling.
- **Unicode weather emoji instead of inline SVG** -- rejected because
  emoji rendering varies by OS/browser and tends to look cartoonish
  on enterprise Windows desktops. Inline SVG matches the project's
  no-build / vendored-asset pattern.
- **Row-click-to-modal instead of a dedicated Details button** --
  considered; rejected because the dashboard is otherwise free of
  row-click semantics and adding them adds interaction state
  (what survives a poll? what about keyboard navigation?) that
  doesn't match the read-only polling model.

## Related

- `tasks/todo.md` Phase 8 -- full implementation plan + progress log
- `tasks/decisions/001-stack-and-source-boundary.md` -- Protocol
  pattern that made adding six optional fields a pure additive change
- `tasks/decisions/002-absolute-time-filter.md` -- the previous phase
- `backend/ARCHITECTURE.md` -- updated §6 for the new envelope fields
- `RUNBOOK.md` -- updated Dashboard features and Exporting sections
