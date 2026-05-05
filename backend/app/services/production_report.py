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

    SQL can deliver numerics as ``Decimal``; the test fixture gives us ``int``/``float``
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
# for the same metrics, the data path inside ``get_rollup``
# swaps from ``source.fetch_rows()`` to
# ``metric_source.fetch_points(interval='monthly')``. The Pydantic
# response shape doesn't change; consumers don't notice.


@dataclass(frozen=True)
class Rollup:
    """Internal dataclass mirror of the Pydantic ``RollupEntry``.

    Routes convert these to the Pydantic model at the boundary.
    """

    department_id: str
    department_name: str
    bucket_label: str  # YYYY-MM for monthly, YYYY for yearly
    total_tons: float
    total_runtime_hours: float
    report_count: int
    # Phase 22: latest report's Workcenter.Calcs in this bucket
    # (verbatim pass-through). None when absent.
    calcs: dict[str, str] | None
    # Phase 14a: simple-average per-report metrics for the
    # manager-style bar charts (Total TPH Fed, Runtime %). None when
    # no report in the bucket contributed a non-null value (after
    # the per-report fallback chain in _avg_tph_fed_for_report /
    # _avg_runtime_pct_for_report).
    avg_tph_fed: float | None
    avg_runtime_pct: float | None
    avg_performance_pct: float | None


def _runtime_hours_from_workcenter(wc: Any) -> float:
    """Extract a workcenter's runtime in decimal hours.

    All payload runtime values are decimal hours as of 2026-04-28 (the
    legacy minutes/hours unit-mismatch quirk is gone). Read
    ``Workcenter.Runtime`` directly; defensive 0.0 fallback covers a
    malformed payload without crashing the rollup.
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
    return 0.0


def _coerce_finite_float(v: Any) -> float | None:
    """Float-coerce + finite-check helper. Returns None on failure or
    on NaN/Inf so callers can treat 'no usable value' uniformly."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _avg_tph_fed_for_report(wc: Any) -> float | None:
    """Phase 14a: per-report Total TPH Fed.

    Prefer ``Workcenter.Rate`` (the upstream-computed value).
    Fall back to ``Workcenter.Total / Workcenter.Runtime`` when Rate
    is null but both Total and Runtime > 0 are present. Returns None
    when neither path yields a usable value (e.g. workcenter didn't
    run that day, or the payload is malformed). Monthly aggregation
    averages across non-None reports; a bucket of all-None reports
    rolls up to None and the chart shows a gap.
    """
    if not isinstance(wc, dict):
        return None
    rate = _coerce_finite_float(wc.get("Rate"))
    if rate is not None:
        return rate
    total = _coerce_finite_float(wc.get("Total"))
    runtime = _coerce_finite_float(wc.get("Runtime"))
    if total is not None and runtime is not None and runtime > 0:
        return total / runtime
    return None


def _avg_runtime_pct_for_report(wc: Any) -> float | None:
    """Phase 14a: per-report Runtime %.

    Prefer ``Workcenter.Availability`` (the upstream-computed
    Runtime / Scheduled_Runtime ratio, expressed 0-100). Fall back
    to ``Runtime / Scheduled_Runtime * 100`` capped at 100. Returns
    None when neither path yields a usable value.
    """
    if not isinstance(wc, dict):
        return None
    avail = _coerce_finite_float(wc.get("Availability"))
    if avail is not None:
        return avail
    runtime = _coerce_finite_float(wc.get("Runtime"))
    sched = _coerce_finite_float(wc.get("Scheduled_Runtime"))
    if runtime is not None and sched is not None and sched > 0:
        return min(100.0, (runtime / sched) * 100.0)
    return None


def _avg_performance_for_report(wc: Any) -> float | None:
    """Phase 14a: per-report Performance %.

    Reads ``Workcenter.Performance`` directly. In the current
    payload schema this equals ``Rate / Ideal_Rate * 100`` (the
    OEE Performance Efficiency component / throughput utilization
    against nameplate capacity). Returns None when Performance
    is null (upstream couldn't compute -- e.g., Ideal_Rate not
    configured, or Rate was null). Monthly aggregation drops
    None reports the same way ``avg_tph_fed`` does.
    """
    if not isinstance(wc, dict):
        return None
    return _coerce_finite_float(wc.get("Performance"))


def _mean_or_none(values: list[float | None]) -> float | None:
    """Simple arithmetic mean over non-None values. None when empty."""
    usable = [v for v in values if v is not None]
    if not usable:
        return None
    return sum(usable) / len(usable)


async def get_rollup(
    source: ProductionReportSource,
    *,
    site_id: str,
    bucket: str,
    from_date: date,
    to_date: date,
    department_id: str | None = None,
) -> list[Rollup]:
    """Compute per-(department, month) rollups across the window.

    ``from_month`` is the first day of the earliest month to include;
    ``to_month`` is the last day of the latest month to include. The
    route layer does the YYYY-MM parsing.

    Aggregation rules:
      - ``total_tons`` is the sum of per-report ``Workcenter.Total``
        across every report in the (department, bucket) bucket
        (Phase 21). Belt-scaled C{n}.Total summing is reserved for
        the dashboard's per-conveyor bar chart and lives on the
        ``payload.conveyor_totals`` envelope, not on rollup entries.
      - ``total_runtime_hours`` sums ``Workcenter.Runtime`` (decimal
        hours) across every report in the bucket.
      - ``avg_tph_fed`` (Phase 14a) is the simple mean of per-report
        ``Workcenter.Rate`` (with fallback to Total / Runtime when
        Rate is null but the denominators are present). None if
        every report in the bucket lacks a usable Rate.
      - ``avg_runtime_pct`` (Phase 14a) is the simple mean of
        per-report ``Workcenter.Availability`` (with fallback to
        Runtime / Scheduled_Runtime * 100). None if every report
        lacks a usable value.
      - ``avg_performance_pct`` (Phase 14a) is the simple mean of
        per-report ``Workcenter.Performance`` (which equals
        Rate / Ideal_Rate * 100 in the current payload schema).
        None if every report has a null Performance.
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
    if bucket not in ("monthly", "yearly"):
        raise ValueError(
            f"bucket must be 'monthly' or 'yearly'; got {bucket!r}."
        )
    if from_date > to_date:
        raise ValueError(
            f"from_date ({from_date.isoformat()}) must be <= "
            f"to_date ({to_date.isoformat()})."
        )

    rows = await source.fetch_rows()
    rows = [r for r in rows if r.site_id == site_id]
    if department_id is not None:
        rows = [r for r in rows if r.department_id == department_id]

    # Window filter -- inclusive on both ends.
    rows = [
        r for r in rows
        if from_date <= r.prod_date.date() <= to_date
    ]

    # Group by (department_id, bucket-label). Bucket label is YYYY-MM
    # for monthly, YYYY for yearly.
    grouped: dict[tuple[str, str], list[ProductionReportRow]] = defaultdict(list)
    for r in rows:
        if bucket == "yearly":
            label = f"{r.prod_date.year:04d}"
        else:
            label = f"{r.prod_date.year:04d}-{r.prod_date.month:02d}"
        grouped[(r.department_id, label)].append(r)

    out: list[Rollup] = []
    for (dept_id, label), group in sorted(grouped.items()):
        # Phase 21: total_tons sums per-report Workcenter.Total
        # (Flow's authoritative workcenter-level tonnage). Belt-scaled
        # C{n}.Total summing is reserved for the dashboard's per-conveyor
        # bar chart via payload.conveyor_totals; we don't surface it on
        # the rollup wire shape any more. Missing / null Workcenter.Total
        # contributes 0 (defensive default; matches the per-report
        # helpers' coerce-or-None pattern).
        wcs = [
            (r.payload or {}).get("Metrics", {}).get("Workcenter")
            for r in group
        ]
        total_tons = 0.0
        for wc in wcs:
            if not isinstance(wc, dict):
                continue
            v = _coerce_finite_float(wc.get("Total"))
            if v is not None:
                total_tons += v

        total_runtime_hours = sum(_runtime_hours_from_workcenter(wc) for wc in wcs)

        # Phase 14a: simple-average per-report metrics. Each helper
        # returns None when the per-report value is unusable; the
        # mean drops Nones and falls back to None when every entry
        # in the bucket is None.
        avg_tph_fed = _mean_or_none([_avg_tph_fed_for_report(wc) for wc in wcs])
        avg_runtime_pct = _mean_or_none([_avg_runtime_pct_for_report(wc) for wc in wcs])
        avg_performance_pct = _mean_or_none([_avg_performance_for_report(wc) for wc in wcs])

        # Phase 12: lift department_name off any row in the group. All
        # rows in a (dept_id, month) bucket share the same dept_id and
        # therefore the same Departments row. Group is guaranteed
        # non-empty (we only build groups when at least one row lands
        # in the bucket) so direct index is safe.
        # Phase 22: latest report's Workcenter.Calcs (max prod_date in group).
        latest_report = max(group, key=lambda r: r.prod_date)
        latest_wc = (latest_report.payload or {}).get("Metrics", {}).get("Workcenter")
        latest_calcs: dict[str, str] | None = None
        if isinstance(latest_wc, dict):
            c = latest_wc.get("Calcs")
            if isinstance(c, dict) and c:
                latest_calcs = {str(k): str(v) for k, v in c.items()}

        out.append(
            Rollup(
                department_id=dept_id,
                department_name=group[0].department_name,
                bucket_label=label,
                total_tons=total_tons,
                total_runtime_hours=total_runtime_hours,
                report_count=len(group),
                avg_tph_fed=avg_tph_fed,
                avg_runtime_pct=avg_runtime_pct,
                avg_performance_pct=avg_performance_pct,
                calcs=latest_calcs,
            )
        )

    return out


# --- Phase 14b: per-circuit / per-line monthly rollup --------------------
#
# Walks payload.Metrics.Circuit on each row and emits a hierarchical
# response shaped as (department -> circuits -> [optional] lines ->
# monthly aggregates). The dashboard reads node.description as the
# label for each level so the rendering is universal across sites.
# Yield is read directly from the pre-computed `Yield` field on each
# circuit/line node -- no math here.


@dataclass(frozen=True)
class CircuitBucketEntry:
    """One per-(circuit-or-line, bucket) aggregate."""
    bucket_label: str  # YYYY-MM for monthly, YYYY for yearly
    total_tons: float
    runtime_hours: float
    avg_tph: float | None
    avg_yield: float | None
    report_count: int
    # Phase 22: latest report's node.Calcs in this bucket. None if absent.
    calcs: dict[str, str] | None


@dataclass(frozen=True)
class LineRollup:
    """A line under a circuit. ``description`` is the operator-facing label
    (e.g. "57-1"); ``line_id`` is the slot key in the payload (e.g. "A")."""
    line_id: str
    description: str
    buckets: list[CircuitBucketEntry]


@dataclass(frozen=True)
class CircuitRollup:
    """A top-level circuit. ``lines`` is empty when the circuit has no
    sub-line structure in the payload (e.g. "CR Circuit")."""
    circuit_id: str
    description: str
    buckets: list[CircuitBucketEntry]
    lines: list[LineRollup]


@dataclass(frozen=True)
class DepartmentCircuitRollup:
    """All circuits / lines for one department."""
    department_id: str
    department_name: str
    circuits: list[CircuitRollup]


def _per_node_tph(node: dict[str, Any]) -> float | None:
    """Per-report TPH for a Circuit or Line node.

    Prefers ``node.Rate`` (pre-computed upstream, the authoritative
    value Flow publishes for that node). Falls back to
    ``node.Total / node.Runtime`` for payloads written before Rate
    was added at the circuit / line level (rollout window) and as
    a defensive guard against malformed nodes that drop the Rate
    field. Returns None when neither path yields a usable value.
    Same precedence pattern as ``_avg_tph_fed_for_report`` for
    Workcenter -- consistency across the codebase.
    """
    rate = _coerce_finite_float(node.get("Rate"))
    if rate is not None:
        return rate
    total = _coerce_finite_float(node.get("Total"))
    runtime = _coerce_finite_float(node.get("Runtime"))
    if total is not None and runtime is not None and runtime > 0:
        return total / runtime
    return None


def _circuit_node_aggregate(
    node_per_report: list[tuple[str, dict[str, Any] | None, datetime]],
) -> list[CircuitBucketEntry]:
    """Roll a list of ``(bucket_label, node)`` pairs into per-bucket aggregates.

    Each ``node`` is either a Circuit or a Line dict from the payload,
    or ``None`` if that report didn't have the node. ``None`` reports
    contribute 0 to ``report_count`` (the node didn't exist) and are
    skipped from the means. The mean helpers drop None values.
    """
    by_bucket: dict[str, list[tuple[dict[str, Any], "datetime"]]] = defaultdict(list)
    for label, node, prod_date in node_per_report:
        if isinstance(node, dict):
            by_bucket[label].append((node, prod_date))

    out: list[CircuitBucketEntry] = []
    for label in sorted(by_bucket.keys()):
        pairs = by_bucket[label]
        nodes = [n for n, _ in pairs]
        total_tons = sum(_coerce_finite_float(n.get("Total")) or 0.0 for n in nodes)
        runtime_hours = sum(_coerce_finite_float(n.get("Runtime")) or 0.0 for n in nodes)

        # avg_tph: simple mean of per-report Rate (preferred) or
        # Total/Runtime fallback. See _per_node_tph for the rule.
        avg_tph = _mean_or_none([_per_node_tph(n) for n in nodes])

        # avg_yield: simple mean of per-report Yield (pre-computed).
        avg_yield = _mean_or_none(
            [_coerce_finite_float(n.get("Yield")) for n in nodes]
        )

        # Phase 22: latest node's Calcs (latest by prod_date).
        latest_node, _ = max(pairs, key=lambda p: p[1])
        latest_c = latest_node.get("Calcs")
        latest_calcs: dict[str, str] | None = None
        if isinstance(latest_c, dict) and latest_c:
            latest_calcs = {str(k): str(v) for k, v in latest_c.items()}

        out.append(
            CircuitBucketEntry(
                bucket_label=label,
                total_tons=total_tons,
                runtime_hours=runtime_hours,
                avg_tph=avg_tph,
                avg_yield=avg_yield,
                report_count=len(nodes),
                calcs=latest_calcs,
            )
        )
    return out


async def get_circuit_rollup(
    source: ProductionReportSource,
    *,
    site_id: str,
    bucket: str,
    from_date: date,
    to_date: date,
    department_id: str | None = None,
) -> list[DepartmentCircuitRollup]:
    """Compute hierarchical (department -> circuit -> [lines]) monthly
    rollups across the window. Each report's payload is walked for its
    Circuit hierarchy; circuits and lines are discovered dynamically
    via their slot keys (`A`, `B`, ...) and labeled by their
    ``Description`` field.

    Aggregations per (circuit, month) and per (line, month):
      - ``total_tons`` = sum of node.Total
      - ``runtime_hours`` = sum of node.Runtime
      - ``avg_tph`` = simple mean of per-report node.Total/node.Runtime
      - ``avg_yield`` = simple mean of per-report node.Yield
      - ``report_count`` = reports contributing to the bucket

    A report whose payload lacks the Circuit block, or lacks a
    particular circuit/line slot, simply doesn't contribute to that
    bucket. Buckets that end up empty are present with zero/None
    values so the frontend's per-month axis stays consistent.

    Raises:
        ValueError -- if from_month > to_month.
    """
    if bucket not in ("monthly", "yearly"):
        raise ValueError(
            f"bucket must be 'monthly' or 'yearly'; got {bucket!r}."
        )
    if from_date > to_date:
        raise ValueError(
            f"from_date ({from_date.isoformat()}) must be <= "
            f"to_date ({to_date.isoformat()})."
        )

    rows = await source.fetch_rows()
    rows = [r for r in rows if r.site_id == site_id]
    if department_id is not None:
        rows = [r for r in rows if r.department_id == department_id]
    rows = [
        r for r in rows
        if from_date <= r.prod_date.date() <= to_date
    ]

    # Group reports by department_id.
    by_dept: dict[str, list[ProductionReportRow]] = defaultdict(list)
    for r in rows:
        by_dept[r.department_id].append(r)

    out: list[DepartmentCircuitRollup] = []
    for dept_id in sorted(by_dept.keys()):
        dept_rows = by_dept[dept_id]
        dept_name = dept_rows[0].department_name

        # Topology discovery: walk every report's Circuit block and
        # collect the union of (circuit_id, description) and
        # (circuit_id, line_id, description) tuples. First-seen
        # ordering wins for slot ordering and description (descriptions
        # *should* be stable per-slot but we don't enforce it -- the
        # first one seen wins, which is a deliberate choice over
        # rejecting on disagreement).
        circuit_meta: dict[str, str] = {}      # circuit_id -> description
        line_meta: dict[tuple[str, str], str] = {}  # (cid, lid) -> description
        for r in dept_rows:
            circuits = (r.payload or {}).get("Metrics", {}).get("Circuit") or {}
            if not isinstance(circuits, dict):
                continue
            for cid, cnode in circuits.items():
                if not isinstance(cnode, dict):
                    continue
                if cid not in circuit_meta:
                    circuit_meta[cid] = str(cnode.get("Description") or cid)
                lines = cnode.get("Line")
                if isinstance(lines, dict):
                    for lid, lnode in lines.items():
                        if not isinstance(lnode, dict):
                            continue
                        key = (cid, lid)
                        if key not in line_meta:
                            line_meta[key] = str(lnode.get("Description") or lid)

        # For each discovered circuit / line, build (month, node)
        # tuples per report and run them through the aggregator.
        circuits_out: list[CircuitRollup] = []
        for cid in sorted(circuit_meta.keys()):
            cdesc = circuit_meta[cid]

            circuit_node_per_report: list[tuple[str, dict[str, Any] | None, datetime]] = []
            for r in dept_rows:
                if bucket == "yearly":
                    label = f"{r.prod_date.year:04d}"
                else:
                    label = f"{r.prod_date.year:04d}-{r.prod_date.month:02d}"
                cnode = (r.payload or {}).get("Metrics", {}).get("Circuit", {}).get(cid)
                circuit_node_per_report.append((label, cnode, r.prod_date))
            circuit_buckets = _circuit_node_aggregate(circuit_node_per_report)

            # Lines under this circuit (if any).
            lines_out: list[LineRollup] = []
            for (lc, lid), ldesc in line_meta.items():
                if lc != cid:
                    continue
                line_node_per_report: list[tuple[str, dict[str, Any] | None, datetime]] = []
                for r in dept_rows:
                    if bucket == "yearly":
                        label = f"{r.prod_date.year:04d}"
                    else:
                        label = f"{r.prod_date.year:04d}-{r.prod_date.month:02d}"
                    cnode = (r.payload or {}).get("Metrics", {}).get("Circuit", {}).get(cid) or {}
                    lnode = cnode.get("Line", {}).get(lid) if isinstance(cnode, dict) else None
                    line_node_per_report.append((label, lnode, r.prod_date))
                lines_out.append(
                    LineRollup(
                        line_id=lid,
                        description=ldesc,
                        buckets=_circuit_node_aggregate(line_node_per_report),
                    )
                )
            lines_out.sort(key=lambda l: l.line_id)

            circuits_out.append(
                CircuitRollup(
                    circuit_id=cid,
                    description=cdesc,
                    buckets=circuit_buckets,
                    lines=lines_out,
                )
            )

        out.append(
            DepartmentCircuitRollup(
                department_id=dept_id,
                department_name=dept_name,
                circuits=circuits_out,
            )
        )

    return out

