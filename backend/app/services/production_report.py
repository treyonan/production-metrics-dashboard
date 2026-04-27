"""Business logic for production-report endpoints.

Services depend on the ``ProductionReportSource`` Protocol, never on a
concrete implementation. Routes stay thin and call these functions.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from app.integrations.production_report.base import (
    ProductionReportRow,
    ProductionReportSource,
)

# Sentinel for rows with a null ``dtm``. ``datetime.min`` is older than
# any plausible production record, so null-dtm rows sort as oldest.
_MIN_DTM = datetime.min


def _sort_key(r: ProductionReportRow) -> tuple[datetime, datetime]:
    """Return a tuple key for ordering rows newest-first via ``sorted(..., reverse=True)``.

    Treats ``r.dtm is None`` as the oldest possible timestamp so rows
    with missing write-times sort behind rows that have them.
    """
    return (r.prod_date, r.dtm if r.dtm is not None else _MIN_DTM)


async def get_latest_per_workcenter(
    source: ProductionReportSource,
    site_id: str | None = None,
) -> list[ProductionReportRow]:
    """Return the most recent row per (site_id, department_id).

    If ``site_id`` is provided, only rows for that site are considered.

    Ordering: latest ``prod_date`` wins; ties broken by the later
    ``dtm`` (upstream write timestamp), with null ``dtm`` treated as
    oldest. Result is sorted by ``(prod_date, dtm)`` descending so the
    newest workcenter data is first.
    """
    rows = await source.fetch_rows()
    if site_id is not None:
        rows = [r for r in rows if r.site_id == site_id]

    latest: dict[tuple[str, str], ProductionReportRow] = {}
    for row in rows:
        key = (row.site_id, row.department_id)
        current = latest.get(key)
        if current is None or _sort_key(row) > _sort_key(current):
            latest[key] = row

    return sorted(latest.values(), key=_sort_key, reverse=True)


async def get_range(
    source: ProductionReportSource,
    *,
    from_date: date,
    to_date: date,
    site_id: str | None = None,
) -> list[ProductionReportRow]:
    """Return all rows within ``[from_date, to_date]`` inclusive.

    Comparison is done on ``prod_date.date()`` so time-of-day doesn't
    affect inclusion. Bounds are inclusive on both ends. If ``site_id``
    is provided, only rows for that site are considered.

    Result is sorted by ``(prod_date, dtm)`` descending so callers can
    iterate from newest to oldest without an additional sort. Callers
    that want per-workcenter grouping should do so client-side.

    This replaces the Phase 2.1 ``get_history(days=N)`` rolling window.
    Callers wanting "last N days" compute
    ``from_date = today - (N - 1)``, ``to_date = today`` themselves and
    pass them in explicitly -- keeps the service semantic narrow
    (absolute window) and unambiguous.
    """
    if from_date > to_date:
        raise ValueError(
            f"from_date ({from_date.isoformat()}) must be <= "
            f"to_date ({to_date.isoformat()})."
        )

    rows = await source.fetch_rows()
    if site_id is not None:
        rows = [r for r in rows if r.site_id == site_id]
    rows = [r for r in rows if from_date <= r.prod_date.date() <= to_date]

    return sorted(rows, key=_sort_key, reverse=True)


async def get_latest_date(
    source: ProductionReportSource,
    *,
    site_id: str,
) -> date | None:
    """Return the newest ``prod_date.date()`` for the given site, or None.

    Used by the frontend bootstrap to seed the day picker with the
    most-recent day that actually has data for the selected site --
    sidesteps the "Today is often empty" surprise.

    Derives from ``source.fetch_rows()`` today. If/when the SQL source
    grows large enough that a full table scan on every page load is
    costly, override the Protocol with a ``SELECT MAX(PRODDATE) WHERE
    SITE_ID = ?`` query. Not optimising preemptively -- the current
    table is small and ``/range`` already makes the same scan.

    Returns ``None`` when the site has no reports at all, rather than
    raising -- callers (the bootstrap) can fall back to "today" in
    that case without exception handling.
    """
    rows = await source.fetch_rows()
    rows = [r for r in rows if r.site_id == site_id]
    if not rows:
        return None
    return max(r.prod_date.date() for r in rows)


# --- Conveyor totals --------------------------------------------------------
#
# Belt-scaled conveyor tonnage summed per (site_id, department_id) across
# whatever window the caller passes in. The strict /^C\d+$/ match is a
# deliberate deviation from the shape-based asset discovery used for the
# dashboard's asset table: only conveyors carry belt scales, so only
# conveyors emit meaningful Total values. See PAYLOAD-CONTRACT.md for
# the full rationale.

_CX_RE = re.compile(r"^C\d+$")

# Produced_Item_Description values treated as "no product" (conveyor idle
# / unset) and excluded from the per-conveyor mode calculation. Anything
# NOT in this set is treated as a real product name.
_PLACEHOLDER_DESCRIPTIONS: frozenset[str] = frozenset({"_", "None", ""})


@dataclass(frozen=True)
class ConveyorAggregate:
    """Per-workcenter conveyor aggregate (internal service type).

    Route handlers map this to the ``ConveyorTotals`` Pydantic response
    schema. Staying in a frozen dataclass at the service layer keeps
    business logic independent of the wire format -- same pattern as
    ``ProductionReportRow``.

    ``product_mode`` carries the most *frequent* ``Produced_Item_Description``
    per conveyor across the window. Placeholder values ("_", "None",
    empty string) are excluded from the count, so a conveyor that spent
    most of the window idle but ran "#57" a few times will report "#57"
    rather than "_". Ties are broken toward the newest report -- caller
    must pass entries pre-sorted newest-first, which exploits Python's
    stable insertion order inside ``Counter``. Value is ``None`` when
    every observation is a placeholder, absent, or non-string (nothing
    meaningful to report).
    """

    per_conveyor: dict[str, float]
    product_mode: dict[str, str | None]
    grand_total: float
    conveyors_counted: int
    reports_counted: int


def _coerce_total(value: Any) -> float:
    """Normalize a CX.Total value to a float. ``None``/non-numeric/non-finite => 0.0.

    SQL can deliver numerics as ``Decimal``; CSV gives us ``int``/``float``
    already via ``json.loads``. All three round-trip through ``float(...)``.
    Anything that raises (a stray string, etc.) is treated as missing
    rather than propagating -- defensive because the payload isn't schema-
    enforced upstream.

    Non-finite floats are also treated as zero: ``float("NaN")`` succeeds
    and returns IEEE NaN, which would then silently poison any sum it
    touched. ``+inf`` / ``-inf`` fall into the same bucket. ``math.isfinite``
    catches all three.
    """
    if value is None:
        return 0.0
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(result):
        return 0.0
    return result


def _numeric_cx_key(name: str) -> int:
    """Sort helper: 'C10' > 'C3' > 'C1' numerically, not lexically."""
    return int(name[1:])


def compute_conveyor_totals(
    entries: list[ProductionReportRow],
) -> dict[tuple[str, str], ConveyorAggregate]:
    """Aggregate belt-scaled conveyor tonnage per ``(site_id, department_id)``.

    For each input row, walks ``payload.Metrics`` looking for keys that
    match ``/^C\\d+$/`` and adds the value's ``Total`` field (coerced via
    ``_coerce_total``) into a running sum for that workcenter's conveyor.

    Returns a dict keyed by ``(site_id, department_id)``. Workcenters with
    **no** CX keys in any of their entries are omitted entirely -- the
    dashboard reads an absent key as "nothing to chart." Workcenters
    whose conveyors all summed to exactly zero ARE included (the zeros
    may be meaningful as downtime).

    Within each aggregate, ``per_conveyor`` is insertion-ordered by
    numeric conveyor number (C1, C3, C4, ..., C10) so downstream
    JSON serialization preserves a stable, human-readable order.
    """
    raw_sums: dict[tuple[str, str], dict[str, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    # Per-workcenter, per-conveyor list of non-placeholder product
    # descriptions in the order they appear in the input. Caller must
    # pass entries pre-sorted newest-first (all current call sites do,
    # via get_latest_per_workcenter / get_range). That ordering matters:
    # Counter.most_common(1) breaks ties by first-seen, so a newest-first
    # insertion order means ties go to the most recent value --
    # "mode, tied to newest."
    product_observations: dict[tuple[str, str], dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    report_counts: dict[tuple[str, str], int] = defaultdict(int)

    for row in entries:
        key = (row.site_id, row.department_id)
        report_counts[key] += 1

        metrics = row.payload.get("Metrics") if isinstance(row.payload, dict) else None
        if not isinstance(metrics, dict):
            continue

        for asset_key, asset_data in metrics.items():
            if not _CX_RE.match(asset_key):
                continue
            if not isinstance(asset_data, dict):
                continue
            raw_sums[key][asset_key] += _coerce_total(asset_data.get("Total"))

            raw_desc = asset_data.get("Produced_Item_Description")
            if isinstance(raw_desc, str) and raw_desc not in _PLACEHOLDER_DESCRIPTIONS:
                product_observations[key][asset_key].append(raw_desc)

    out: dict[tuple[str, str], ConveyorAggregate] = {}
    for key, conveyors in raw_sums.items():
        ordered = dict(sorted(conveyors.items(), key=lambda kv: _numeric_cx_key(kv[0])))
        # Compute per-conveyor mode in the same C1-C3-C10 numeric order
        # so the dict iterates alongside per_conveyor in the response.
        modes: dict[str, str | None] = {}
        for cx in ordered.keys():
            observations = product_observations[key].get(cx, [])
            if observations:
                # Counter.most_common(1) returns the first-seen among
                # ties (heapq.nlargest(1, ...) reduces to max(), which
                # returns first maximum). Newest-first input => tie
                # breaks toward the newest observation.
                modes[cx] = Counter(observations).most_common(1)[0][0]
            else:
                # No non-placeholder observations in the window. The
                # frontend surfaces this as em-dash via placeholderize.
                modes[cx] = None
        out[key] = ConveyorAggregate(
            per_conveyor=ordered,
            product_mode=modes,
            grand_total=sum(ordered.values()),
            conveyors_counted=len(ordered),
            reports_counted=report_counts[key],
        )
    return out



# ---------------------------------------------------------------------
# Phase 10a: Monthly rollup service
# ---------------------------------------------------------------------
#
# Aggregate per-shift production reports into one row per
# (department, year-month). Used by the trends view; also serves
# any future consumer that wants pre-computed monthly numbers
# (Ignition reports, Excel exports, etc.).
#
# Future migration: when Flow publishes monthly aggregate measures
# for the same metrics, the data path inside ``get_monthly_rollup``
# swaps from ``source.fetch_rows()`` to
# ``metric_source.fetch_points(interval='monthly')``. The Pydantic
# response shape doesn't change; consumers don't notice.


@dataclass(frozen=True)
class MonthlyRollup:
    """Internal dataclass mirror of the Pydantic ``MonthlyRollupEntry``.

    Routes convert these to the Pydantic model at the boundary.
    """

    department_id: str
    month: str  # YYYY-MM
    total_tons: float
    total_runtime_minutes: float
    tph: float | None
    report_count: int


def _runtime_minutes_from_workcenter(wc: Any) -> float:
    """Extract a workcenter's runtime in minutes, with the same fallback
    rule used by the dashboard:

      - Use ``Workcenter.Runtime`` (already in minutes) if present + finite.
      - Otherwise fall back to ``Workcenter.Actual_Runtime_Hours * 60``
        when present + finite.
      - Else 0.0.
    """
    if not isinstance(wc, dict):
        return 0.0
    raw = wc.get("Runtime")
    if raw is not None:
        try:
            v = float(raw)
            if math.isfinite(v):
                return v
        except (TypeError, ValueError):
            pass
    raw_hours = wc.get("Actual_Runtime_Hours")
    if raw_hours is not None:
        try:
            v = float(raw_hours) * 60.0
            if math.isfinite(v):
                return v
        except (TypeError, ValueError):
            pass
    return 0.0


async def get_monthly_rollup(
    source: ProductionReportSource,
    *,
    site_id: str,
    from_month: date,
    to_month: date,
    department_id: str | None = None,
) -> list[MonthlyRollup]:
    """Compute per-(department, month) rollups across the window.

    ``from_month`` is the first day of the earliest month to include;
    ``to_month`` is the last day of the latest month to include. The
    route layer does the YYYY-MM parsing.

    Aggregation rules:
      - ``total_tons`` is the sum of belt-scaled CX conveyor totals
        (strict /^C\d+$/) across every report in the
        (department, month) bucket. Reuses Phase 5's
        ``compute_conveyor_totals``.
      - ``total_runtime_minutes`` sums ``Workcenter.Runtime`` per
        report (falling back to ``Actual_Runtime_Hours * 60``).
      - ``tph`` divides total_tons by total_runtime_hours; returns
        None when runtime is zero (avoids /0).
      - ``report_count`` is the number of production reports that
        contributed.

    Workcenters with no reports in a given month are simply absent
    from the result -- consumers render gaps in the trend line as
    they see fit. Reports whose payload contains no CX keys still
    contribute a 0 to ``total_tons`` for that month and increment
    ``report_count``.

    Raises:
        ValueError -- if from_month > to_month.
    """
    if from_month > to_month:
        raise ValueError(
            f"from_month ({from_month.strftime('%Y-%m')}) must be <= "
            f"to_month ({to_month.strftime('%Y-%m')})."
        )

    rows = await source.fetch_rows()
    rows = [r for r in rows if r.site_id == site_id]
    if department_id is not None:
        rows = [r for r in rows if r.department_id == department_id]

    # Window filter -- inclusive on both ends.
    rows = [
        r for r in rows
        if from_month <= r.prod_date.date() <= to_month
    ]

    # Group by (department_id, year-month).
    grouped: dict[tuple[str, str], list[ProductionReportRow]] = defaultdict(list)
    for r in rows:
        ym = f"{r.prod_date.year:04d}-{r.prod_date.month:02d}"
        grouped[(r.department_id, ym)].append(r)

    out: list[MonthlyRollup] = []
    for (dept_id, ym), group in sorted(grouped.items()):
        # Reuse the Phase 5 aggregator for tonnage. Returns a dict
        # keyed by (site_id, dept_id) -- this group's rows all share
        # one (site_id, dept_id), so there's at most one entry.
        totals = compute_conveyor_totals(group)
        agg = next(iter(totals.values()), None)
        total_tons = agg.grand_total if agg is not None else 0.0

        total_runtime_min = sum(
            _runtime_minutes_from_workcenter(
                (r.payload or {}).get("Metrics", {}).get("Workcenter")
            )
            for r in group
        )

        tph: float | None
        if total_runtime_min > 0:
            tph = total_tons / (total_runtime_min / 60.0)
        else:
            tph = None

        out.append(
            MonthlyRollup(
                department_id=dept_id,
                month=ym,
                total_tons=total_tons,
                total_runtime_minutes=total_runtime_min,
                tph=tph,
                report_count=len(group),
            )
        )

    return out
