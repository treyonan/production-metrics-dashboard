# Production Report Payload Schema

Documents the structure of the `PAYLOAD` column in the production report
dataset. This is the curated KPI payload produced upstream (Flow or similar)
and stored as a JSON string in SQL Server.

## Overview

A single payload represents one production report row — typically one
workcenter, one shift or day. It contains:

- **Site-level metadata**: operators, shot numbers, manual loader counts
- **Workcenter-level rollup**: overall availability, performance, runtime, schedule context
- **Asset-level metrics**: per-conveyor KPIs (C1, C3–C8)
- **Circuit hierarchy**: circuit-level runtime with nested lines

Everything sits under a single top-level `Metrics` key.

## Raw example

See `payload-example.json` alongside this file for the canonical
single-row sample (always kept current). Abridged version below for
quick reference -- runtimes in **decimal hours** throughout.

```json
{
  "Metrics": {
    "Site": {
      "Loader_Operator_One": "Brandon Stephens",
      "Shot_Number_One": "None",
      "Loader_Operator_Two": "Connor Dakour",
      "Loads_15_Ton": "0",
      "Shot_Number_Two": "None"
    },
    "Workcenter": {
      "Availability": 100.0,
      "Production_Mode": "2",
      "Start_Time": "12:42:00",
      "Scheduled_Runtime": 5.0,
      "Runtime": 5.1,
      "Total": 3263.0,
      "Rate": 646.0,
      "Ideal_Rate": 1000.0,
      "Scheduled_Status": "Scheduled",
      "Performance": 64.6
    },
    "C1": {
      "Availability": 72.3,
      "Runtime": 3.7,
      "Rate": 750.5,
      "Total": 3790.8,
      "Belt_Scale_Availability": 80.1,
      "Produced_Item_Code": "_",
      "Produced_Item_Description": "_",
      "Performance": 108.6
    },
    "C3": { "...": "same shape as C1" },
    "C4": { "...": "same shape as C1" },
    "C5": { "...": "same shape as C1" },
    "C6": { "...": "same shape as C1" },
    "C7": { "...": "same shape as C1" },
    "C8": { "...": "same shape as C1" },
    "Circuit": {
      "A": {
        "Description": "Main Circuit",
        "Line": {
          "A": { "Description": "57-1", "Runtime": 3.6, "Total": 1080.4 },
          "B": { "Description": "57-2", "Runtime": 3.6, "Total": 1219.5 }
        },
        "Runtime": 7.2,
        "Total": 2299.9
      },
      "B": {
        "Description": "CR Circuit",
        "Runtime": 0.0,
        "Total": 0.0
      }
    }
  }
}
```

## Top-level structure

| Key | Type | Notes |
|---|---|---|
| `Metrics` | object | Only top-level key. Everything nests under here. |
| `Metrics.Site` | object | Operators, shot numbers, manual entries. Mostly strings. |
| `Metrics.Workcenter` | object | Overall rollup for the workcenter. |
| `Metrics.C1`, `C3`–`C8` | object | One per physical asset/conveyor. Uniform shape. |
| `Metrics.Circuit` | object | Circuit hierarchy: circuits → lines. Each level carries `Runtime`, `Total`, and a human-readable `Description`. |

Note: `C2` is not present in this topology. Asset keys represent physical
assets that exist at the site; assume keys may be absent, not null.

## Section: `Site`

Operator-entered and reference data. All values are **strings**, even
numeric-looking ones (`"0"`, `"None"`).

| Field | Type | Nullable | Notes |
|---|---|---|---|
| `Loader_Operator_One` | string | — | Free-text operator name |
| `Loader_Operator_Two` | string | — | Free-text operator name |
| `Shot_Number_One` | string | — | Blast shot reference. `"None"` (string) when absent. |
| `Shot_Number_Two` | string | — | Same as above |
| `Loads_15_Ton` | string | — | Count of 15-ton loads, stored as string |

**Quirks**:
- `"None"` appears as a literal string, not JSON `null`. Don't compare to `null`.
- `Loads_15_Ton` is a numeric count but typed as string. Parse with `int()` after
  checking for `""` or `"None"`.
- Additional operator-input fields may appear here in the future; treat the
  Site object as open-ended.

## Section: `Workcenter`

Rollup-level KPIs and schedule context.

| Field | Type | Nullable | Notes |
|---|---|---|---|
| `Availability` | number | no | Percentage (0–100). Workcenter runtime ÷ scheduled runtime × 100, capped at 100. |
| `Performance` | number \| null | **yes** | `null` when not calculable (e.g. no production). |
| `Total` | number \| null | **yes** | Workcenter-level total (tons fed). |
| `Runtime` | number | no | Workcenter runtime so far this shift/day, in **decimal hours**. |
| `Scheduled_Runtime` | number | no | Scheduled runtime for this shift/day, in **decimal hours**. |
| `Rate` | number \| null | **yes** | Workcenter throughput rate (tons/hour). |
| `Ideal_Rate` | number \| null | **yes** | Reference rate the workcenter is benchmarked against (tons/hour). |
| `Start_Time` | string | no | `HH:MM:SS` 24-hour format |
| `Production_Mode` | string | no | Placeholder for future use. Currently `"2"` for all runs. Reserved for when the workcenter operates in additional modes; human-readable mode descriptions will be defined later. |
| `Scheduled_Status` | string | no | Enum-like. Observed: `"Scheduled"`. |

**Quirks**:
- `Production_Mode` looks numeric but is a string. Currently a placeholder
  (`"2"` everywhere); additional modes with human-readable descriptions
  will be added later. Treat as an opaque string for now — don't hard-code
  behavior based on its value.
- Pre-2026-04-28 payloads had `Actual_Runtime_Hours` and `Scheduled_Hours`
  (the latter as a string `"0"`) instead of `Runtime` and
  `Scheduled_Runtime`. Those names are gone. Do not introduce backward-
  compatibility fallbacks for them.

## Section: Asset metrics (`C1`, `C3`–`C8`)

Uniform shape per asset. Asset key is the conveyor identifier.

| Field | Type | Nullable | Notes |
|---|---|---|---|
| `Availability` | number | no | Percentage (0–100). Asset runtime ÷ workcenter runtime × 100. |
| `Runtime` | number | no | Asset runtime in **decimal hours**. |
| `Rate` | number \| null | **yes** | Asset throughput rate (tons/hour) over the runtime. |
| `Performance` | number \| null | **yes** | `null` when not calculable; `0.0` when calculated and zero. |
| `Total` | number | no | Tons through the asset's belt scale for the period. `0.0` when no flow. |
| `Belt_Scale_Availability` | number | no | Percent (0–100). Percentage of the production run during which the PLC reported the belt scale as connected. Measures PLC/scale connectivity, not material flow. |
| `Produced_Item_Code` | string | no | SKU/item code. `"_"` is a placeholder meaning "no item assigned". |
| `Produced_Item_Description` | string | no | Human-readable item description. `"_"` as placeholder. Free-text. |

**Quirks**:
- `Belt_Scale_Availability` measures **PLC connectivity to the belt scale**
  over the production run — the percentage of time the PLC reported the
  scale as connected. `100.0` means the scale was reachable the entire run;
  independent of whether material was actually flowing. Low values point
  to PLC/network issues, not production problems.
- `"_"` is the placeholder for empty item fields — not null, not empty string.
  Check for this explicitly.
- `Performance: null` vs `Performance: 0.0` carry different meaning: null =
  "can't compute" (no basis); 0.0 = "computed and there was zero output".

## Section: `Circuit`

Circuit-level runtime rollups. Shape is **variable depth** — some circuits
have nested `Line` objects, others do not.

| Field | Type | Nullable | Notes |
|---|---|---|---|
| `Circuit.<id>.Runtime` | number | no | Circuit runtime in **decimal hours** |
| `Circuit.<id>.Total` | number \| null | **yes** | Tons through circuit |
| `Circuit.<id>.Description` | string | no | Human-readable circuit name (e.g. `"Main Circuit"`, `"CR Circuit"`) |
| `Circuit.<id>.Line.<id>.Runtime` | number | no | Line runtime in **decimal hours** (when Line is present) |
| `Circuit.<id>.Line.<id>.Total` | number \| null | **yes** | Line tons |
| `Circuit.<id>.Line.<id>.Description` | string | no | Human-readable line name (e.g. `"57-1"`, `"57-2"`) |

Observed circuits: `A` ("Main Circuit", with `Line.A` "57-1" and
`Line.B` "57-2"), `B` ("CR Circuit", no lines). Structure may differ
by topology — don't assume every circuit has lines.

Relates to plant topology documented in `context/domain.md`:
Circuit A ≈ Main A / Main B lines; Circuit B ≈ CR (crusher return).

## Cross-cutting conventions

### Units (2026-04-28)
**Every `Runtime` value in the payload is decimal hours.** Workcenter,
asset, circuit, line — all hours. The legacy minutes/hours unit-mismatch
quirk (assets in minutes, workcenter in hours) is gone. If you find code
that multiplies a `Runtime` by 60 or divides by 60, it predates this
change and is a bug.

### Availability semantics
`Availability` on an asset is expressed as a percent of workcenter runtime:

```
asset.Availability ≈ (asset.Runtime / Workcenter.Runtime) * 100
```

`Availability` on a workcenter is expressed as a percent of scheduled runtime
(capped at 100):

```
Workcenter.Availability ≈ min(100, (Workcenter.Runtime / Workcenter.Scheduled_Runtime) * 100)
```

### Null vs. zero vs. placeholder
Three distinct "empty" representations in this payload, each with meaning:

| Value | Meaning |
|---|---|
| `null` | Not calculable / not applicable. Common for `Performance` and `Total` before production. |
| `0.0` | Computed value that happened to be zero. Production did run, output was zero. |
| `"_"` | Placeholder for unset string fields (item codes/descriptions). |
| `"None"` | Placeholder string for optional Site fields (shot numbers). |

Frontend display logic has to distinguish these: show `—` for null, `0.0` for
zero, and something sensible (or `—`) for placeholders.

### Mixed string/number typing
Some numeric-looking fields are strings in this payload:
- `Site.Loads_15_Ton`, `Workcenter.Production_Mode`

This is upstream behavior; don't try to "fix" it in SQL. Parse defensively
in Python.

## Parsing strategy

### Recommended: Python-side Pydantic models
Keep SQL storage dumb (raw JSON string column). Parse in Python using
Pydantic v2 models that live in `backend/app/schemas/production_report.py`.
Those models are the single source of truth for what a valid payload
looks like.

Benefits:
- Structured validation errors at ingestion time
- Refactoring the schema is a Python change, not a SQL change
- Tests can construct payloads as dicts and validate

Draft model sketch:

```python
from typing import Optional
from pydantic import BaseModel, Field

class AssetMetrics(BaseModel):
    availability: float = Field(alias="Availability")
    runtime: float = Field(alias="Runtime")  # decimal hours
    rate: Optional[float] = Field(alias="Rate", default=None)
    performance: Optional[float] = Field(alias="Performance", default=None)
    total: float = Field(alias="Total")
    belt_scale_availability: float = Field(alias="Belt_Scale_Availability")
    produced_item_code: str = Field(alias="Produced_Item_Code")
    produced_item_description: str = Field(alias="Produced_Item_Description")

class Workcenter(BaseModel):
    availability: float = Field(alias="Availability")
    performance: Optional[float] = Field(alias="Performance", default=None)
    total: Optional[float] = Field(alias="Total", default=None)
    runtime: float = Field(alias="Runtime")                      # decimal hours
    scheduled_runtime: float = Field(alias="Scheduled_Runtime")  # decimal hours
    rate: Optional[float] = Field(alias="Rate", default=None)
    ideal_rate: Optional[float] = Field(alias="Ideal_Rate", default=None)
    start_time: str = Field(alias="Start_Time")
    production_mode: str = Field(alias="Production_Mode")
    scheduled_status: str = Field(alias="Scheduled_Status")

# ... plus Site, Circuit, Line models, and a top-level Metrics wrapper
```

### Alternative: OPENJSON in SQL
Only consider if downstream consumers need flat rows for filtering or BI
tools. Otherwise adds a second place the schema has to be maintained.

## Open questions for confirmation

Document answers in `tasks/decisions/` or inline in this file as they're resolved:

1. **Scheduled_Status values.** Full enum? (`"Scheduled"`, `"Unscheduled"`, others?)
2. **C2 absence.** Confirm C2 doesn't exist at this site, and that missing
   keys are expected (not a data error).
3. **Availability formula.** Confirmed 2026-04-28: asset Availability =
   asset.Runtime / Workcenter.Runtime × 100 (both in hours);
   Workcenter Availability = min(100, Runtime / Scheduled_Runtime × 100).
4. **Performance formula.** OEE = A × P × Q — where does Q (quality) come
   from? Not apparent in this payload.
5. **Circuit/Line topology.** Confirm circuit-to-physical-asset mapping
   (Circuit A → Main A/B, Circuit B → CR).