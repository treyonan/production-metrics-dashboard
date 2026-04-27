# Production-Report Payload Contract

**Status:** DRAFT — prepared for team review, 2026-04-23
**Scope:** Shape expectations for the `PAYLOAD` JSON column in
`IA_ENTERPRISE.[UNS].[SITE_PRODUCTION_RUN_REPORTS]`, and how the
production-metrics-dashboard frontend renders it.
**Applies to:** Production reports only. Interval metrics (shiftly
conveyor tons, hourly equipment runtime, etc.) are a separate domain
with a separate contract — see `tasks/specs/002-interval-metric-sources.md`.

## Purpose

Two plants cannot produce identical data — equipment configurations
differ, workcenter layouts differ, upstream reporting conventions
drift over time. But a single dashboard must work for all of them
without per-site frontend code branches. This contract names the
small set of fields that every site MUST emit identically
("canonical"), defines a shape-based rule for discovering equipment
that isn't named the same everywhere ("discovery-by-shape"), and
lists what the dashboard deliberately ignores ("excluded").

The goal: **standardize as much as possible, relax where beneficial or
needed.** Canonical fields are cheap to enforce upstream and give the
dashboard a stable KPI layer. Shape-based discovery absorbs the
natural variance between plants — a crusher at one site, a screen at
another — without either breaking.

## How to read this document

Each rule below has three parts:

- **Rule** — the one-line contract.
- **Why** — the reason it's phrased this way, so you can tell a real
  edge case from a style disagreement.
- **If violated** — what the dashboard does when a site's payload
  breaks the rule. In most cases the answer is "renders a dash and
  keeps going," never "crashes" — but silent failure has its own
  failure mode (invisible missing data), which is why the contract
  matters.

## The contract (v1)

### Rule 1 — Canonical Workcenter KPIs

**Rule:** Every production-report payload MUST carry a top-level
`Metrics.Workcenter` object containing at least these fields with
these exact names:

| Field | Type | Notes |
|---|---|---|
| `Availability` | number (percent, 0–100) | Required |
| `Performance` | number (percent) or null | Nullable — rendering shows a dash |
| `Total` | number (tons) or null | Nullable — rendering shows a dash |
| `Scheduled_Status` | string | One of `Scheduled`, `Unscheduled`, or site-specific |
| `Actual_Runtime_Hours` | number (hours) or null | Used when `Runtime` (minutes) isn't supplied |
| `Runtime` | number (minutes) or null | Preferred over `Actual_Runtime_Hours`; either satisfies the KPI |

**Why:** these four KPIs (Availability, Performance, Runtime, Total)
are the fixed card set on every workcenter panel. Different field
names at different sites would require per-site rendering logic —
defeating the point of a shared dashboard.

**If violated:** the KPI card for the missing field renders `—`
(em dash). The panel still draws. No crash. But operators looking
at that panel see a gap and may not realize it reflects a data issue
rather than downtime.

### Rule 2 — Asset discovery by shape

**Rule:** The dashboard discovers "assets" (conveyors, crushers,
screens, feeders, etc.) by scanning top-level keys under `Metrics`
and selecting any child that:

- is an object (not null, array, or primitive), AND
- contains **at least two** of these canonical field names:
  `Availability`, `Runtime`, `Performance`, `Total`.

Qualifying children are rendered as asset rows using whatever key
name they have in the payload (`C1`, `Crusher_1`, `Screen_2`, etc. —
the raw key is the display label).

**Why:** conveyors follow the `C<number>` naming convention
site-wide, and we want that preserved. But future sites will include
other equipment classes — crushers, screens, feeders — named
differently. A regex pinned to `C\d+` would silently drop those
rows. A shape probe accepts any equipment that emits the same
per-asset metric shape, regardless of how it's named.

The "at least two of four" threshold is deliberately loose. Require
all four and sites that don't compute `Performance` for some asset
classes (e.g. feeders) disappear. Require just one and we risk
false positives from metadata blocks that happen to have a
`Total` field in a different sense.

**If violated:** equipment that doesn't emit the canonical shape is
simply not rendered. Same silent-miss failure mode as Rule 1. If a
new equipment class appears that we DO want on the dashboard, the
fix is upstream (emit the shape) rather than frontend.

**Footnote (Phase 5 addition).** The conveyor-totals bar chart that
renders below each workcenter's asset table is a deliberate exception
to shape-based discovery. It uses strict `/^C\d+$/` matching, not
the ≥2-of-{Availability, Runtime, Performance, Total} probe from
this rule. The reason is semantic, not structural: only conveyors
carry belt scales, so only conveyors emit a `Total` value that
corresponds to weighed tonnage. A `Crusher_1.Total` or
`Screen_1.Total` would pass the shape probe but wouldn't be
belt-scaled tonnage — summing it into a tons chart would produce
garbage. The asset *table* keeps the relaxed rule (show any
equipment a site emits); the asset *tonnage chart* enforces the
stricter rule (show only belt-scaled sources).

### Rule 3 — Excluded keys

**Rule:** These top-level `Metrics` children are NEVER rendered as
asset rows, even if they pass the Rule 2 shape probe:

| Key | Reason |
|---|---|
| `Workcenter` | Surfaced as the KPI cards at the top of the panel, not as an asset row. |
| `Site` | Operator / shot-number metadata; not an equipment metric. Not currently displayed at all. |
| `Circuit` | Sub-circuit (Line A / Line B) rollup intermediates. Already reflected in `Workcenter.*` via upstream aggregation. Not meaningful to display standalone. |

**Why:** these three keys are structurally distinct from
per-equipment metrics and each has its own handling (or deliberate
non-handling). Treating them as assets would confuse the display.

**If violated:** impossible to violate — the exclusion list is a
frontend-side filter. If a site adds a new structurally-distinct
top-level key, we extend the exclusion list rather than teaching the
contract to exclude it automatically.

### Rule 4 — Asset ordering

**Rule:** Asset rows are sorted in two groups:

1. Conveyors (keys matching `C\d+`), in **numeric** order: C1, C3,
   C4, ..., C10 (not lexical, which would give C1, C10, C3, ...).
2. All other assets, **alphabetically** by key.

Group 1 always appears before group 2.

**Why:** engineers and operators at Big Canyon Quarry are already
used to reading the conveyor table top-to-bottom in circuit order.
Other equipment (crushers, screens) is less position-sensitive and
alphabetical is a defensible default.

**If violated:** does not apply — this is a rendering-side rule.

### Rule 5 — Per-asset field surface

**Rule:** Each asset row currently surfaces these seven columns:

| Column | Payload key | Notes |
|---|---|---|
| Asset | (the key name) | Display label is the raw payload key |
| Availability % | `Availability` | |
| Runtime (min) | `Runtime` | |
| Performance % | `Performance` | |
| Total (tons) | `Total` | |
| Product | `Produced_Item_Code` + `Produced_Item_Description` | Combined display |
| Belt Scale % | `Belt_Scale_Availability` | |

Fields present on an asset that are NOT in this list (e.g. a
crusher's `Closed_Side_Setting` or a screen's `Deck_Angle`) are
silently dropped in v1.

**Why:** fixed column count keeps the table uniform and scannable.
Heterogeneous columns per asset would need either an "Other" column
that varies row-to-row (ugly) or a per-equipment-class rendering
(schema creep).

**If violated:** missing canonical fields render `—`. Extra fields
are dropped without warning.

**v2 stretch:** expandable "Details" row per asset showing any
fields present in the payload but not surfaced by the fixed columns,
so extra data is visible without breaking the table's uniform shape.

## Worked examples

### Example 1 — Big Canyon Quarry today (canonical)

Payload excerpt (abbreviated):

```json
{
  "Metrics": {
    "Site":       { "Loader_Operator_One": "Brandon Stephens", "..." },
    "Workcenter": { "Availability": 83.4, "Performance": null, "Total": null, "Runtime": 552.0, "Scheduled_Status": "Scheduled" },
    "Circuit":    { "A": { "Line": { "A": {...}, "B": {...} } }, "B": {...} },
    "C1":         { "Availability": 92.9, "Runtime": 510.9, "Performance": 99.3, "Total": 8072.0, "..." },
    "C3":         { "Availability": 0.0,  "Runtime": 0.0,   "Performance": null, "Total": 2.2,    "..." },
    "C4":         { "Availability": 91.5, "Runtime": 503.1, "Performance": 128.1,"Total": 3543.3, "..." }
  }
}
```

Rendering:
- **KPI cards:** Availability 83.4%, Performance —, Runtime 552.0, Total —.
- **Asset rows:** `C1`, `C3`, `C4` — in numeric order. `Site` and `Circuit` excluded by Rule 3. `Workcenter` excluded by Rule 3 (handled as KPIs).

### Example 2 — Hypothetical multi-equipment site

Payload excerpt:

```json
{
  "Metrics": {
    "Workcenter": { "Availability": 76.2, "Performance": 84.0, "Total": 2100, "Runtime": 430 },
    "C1":         { "Availability": 88.0, "Runtime": 395, "Performance": 92.0, "Total": 2100 },
    "C2":         { "Availability": 91.2, "Runtime": 410, "Performance": 88.0, "Total": 2100 },
    "Crusher_1":  { "Availability": 74.5, "Runtime": 380, "Performance": 81.0, "Total": 2100 },
    "Screen_1":   { "Availability": 98.1, "Runtime": 420, "Performance": null, "Total": 2050 }
  }
}
```

Rendering:
- **KPI cards:** all four populated (canonical KPIs present).
- **Asset rows:** `C1`, `C2` first (numeric), then `Crusher_1`, `Screen_1` (alphabetical). All four pass the shape probe.

### Example 3 — Edge case (metadata-shaped object)

Payload excerpt:

```json
{
  "Metrics": {
    "Workcenter": { "Availability": 90.0, "Performance": 95.0, "Total": 1800, "Runtime": 440 },
    "C1":         { "Availability": 90.0, "Runtime": 440, "Performance": 95.0, "Total": 1800 },
    "Shift_Info": { "Total": "Day", "Scheduled_Hours": "8" }
  }
}
```

Rendering:
- `C1` renders as an asset (four canonical fields present).
- `Shift_Info` has only `Total`, and it's a string; the Rule 2
  threshold of "at least two of four" is not met. Not rendered.
- If `Shift_Info` grew additional fields matching the threshold,
  Rule 3 exclusion would need to be extended explicitly.

## Non-goals (out of scope for this contract)

- **Unit declarations.** The contract does not declare units for each
  field. Today the frontend assumes `Availability` is a percent 0–100,
  `Runtime` is minutes, `Total` is tons. Codifying units is a v2 item
  once we confirm consistency across sites.
- **Per-site metadata.** Site-specific display preferences (e.g. "site
  101 hides its Belt Scale column") are not expressible in this
  contract. Per-site customization should be rare; if it becomes
  common, we move to a schema-driven rendering model separately.
- **Real-time / push updates.** Dashboard is poll-based (1–5 min cadence).
- **Write endpoints.** Read-only API.
- **Historical payload shapes.** If a legacy row's `PAYLOAD` lacks
  modern canonical fields, the dashboard renders dashes for the
  missing KPIs. We do not maintain a migration layer for old shapes.

## Open questions for team review

1. **Shape-probe threshold.** Rule 2 uses "at least two of four"
   ({Availability, Runtime, Performance, Total}). Is that the right
   threshold? Alternatives: require `Availability` specifically,
   require three of four, etc.
2. **Circuit visibility.** Rule 3 excludes `Circuit`. Is this right
   for all sites, or are there sites where sub-circuit detail is
   actually meaningful standalone on the dashboard?
3. **Site block display.** Rule 3 also excludes `Site` (operator
   names, shot numbers). Should the dashboard surface any of this
   (e.g., a small "Operator: Brandon Stephens" label in the panel
   header)? Currently not displayed at all.
4. **Asset naming conventions beyond conveyors.** Rule 4 groups
   `C\d+` first. Do other equipment classes have similar ordering
   conventions (e.g. crushers before screens)? Or is alphabetical
   fine for everything non-conveyor?
5. **Asset field surface.** Rule 5 is a fixed 7-column table.
   Are there site-or-equipment-specific fields that engineers WILL
   need to see at a glance (not just in the v2 "Details" expansion)?
6. **Error visibility.** The contract's "silent miss" failure mode
   means data gaps look indistinguishable from downtime. Should we
   add a surfacing mechanism — e.g., a small indicator when an
   expected canonical field is missing, distinguishing "Workcenter
   wasn't scheduled" from "the upstream didn't emit Availability"?
7. **Evolution policy.** Who owns this contract? When a new
   equipment class appears at a plant, who writes the upstream
   change — plant IT, control-system engineers, SCADA? What's the
   communication path so the dashboard team knows a new shape is
   coming?

## Change management

Updates to this contract follow the project's ADR pattern —
significant changes get a decision record in `tasks/decisions/`
linked from this file. Small clarifications (wording, new examples,
new excluded keys) go directly into this file with an entry in the
revision history below.

Contract changes that break existing sites require:

1. A draft update to this doc circulated to the team.
2. An implementation plan specifying which sites need upstream
   changes and by when.
3. A dashboard-side compatibility period during which the frontend
   accepts both old and new shapes.

## Revision history

- **2026-04-23** — Initial draft. Derived from the site 101
  payload shape and a design conversation about future multi-site
  variance. Pending team review.

## Reference: related documents

- `context/sample-data/production-report/payload-schema.md` —
  worked-out field-by-field documentation of the site 101 payload
  (the source of the canonical field names used here).
- `backend/ARCHITECTURE.md` §4.5 — how the backend deserialises
  the payload into a Python dict. The backend performs no shape
  enforcement; it passes the parsed JSON through unchanged. All
  contract enforcement is frontend-side (today).
- `frontend/app.js` — specifically the `renderTodayPanel`,
  `discoverAssets` (pending implementation), and `kpiGridFromWorkcenter`
  functions. These are the code that embodies this contract.
- `tasks/specs/002-interval-metric-sources.md` — the adjacent
  contract for interval metrics (shiftly / hourly data), kept
  separate from this one by design.
