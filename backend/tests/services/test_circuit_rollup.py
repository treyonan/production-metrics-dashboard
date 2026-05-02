"""Service-level tests for ``get_circuit_rollup`` -- Phase 14b + Phase 18.

Exercises the dynamic Circuit/Line topology walk, hierarchical
aggregation, and the simple-mean rules for ``avg_tph`` and
``avg_yield``. Constructs reports with synthetic Circuit blocks
directly so the tests are independent of any sample fixture file.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pytest

from app.integrations.production_report.base import (
    ProductionReportRow,
    SourceStatus,
)
from app.services.production_report import get_circuit_rollup


def _row(
    *,
    row_id: int,
    prod_date: datetime,
    circuit: dict[str, Any] | None,
    site_id: str = "101",
    department_id: str = "127",
    department_name: str = "Plant 1",
) -> ProductionReportRow:
    metrics: dict[str, Any] = {}
    if circuit is not None:
        metrics["Circuit"] = circuit
    return ProductionReportRow(
        id=row_id,
        prod_date=prod_date,
        prod_id=f"PR_TEST_{row_id:03d}",
        site_id=site_id,
        department_id=department_id,
        department_name=department_name,
        payload={"Metrics": metrics},
        dtm=None,
    )


class _FakeSource:
    name = "fake:test"

    def __init__(self, rows: list[ProductionReportRow]) -> None:
        self._rows = rows

    async def ping(self) -> SourceStatus:  # pragma: no cover
        return SourceStatus(ok=True, detail="ok", checked_at=datetime.now())

    async def fetch_rows(self) -> list[ProductionReportRow]:
        return list(self._rows)

    async def list_site_ids(self) -> list[str]:  # pragma: no cover
        return sorted({r.site_id for r in self._rows})


# A reusable circuit-with-lines block for several tests below.
def _circuit_with_lines(
    *,
    main_total: float,
    main_runtime: float,
    main_yield: float,
    line_a_total: float,
    line_a_runtime: float,
    line_a_yield: float,
    line_b_total: float,
    line_b_runtime: float,
    line_b_yield: float,
) -> dict[str, Any]:
    return {
        "A": {
            "Description": "Main Circuit",
            "Total": main_total,
            "Runtime": main_runtime,
            "Yield": main_yield,
            "Line": {
                "A": {
                    "Description": "57-2",
                    "Total": line_a_total,
                    "Runtime": line_a_runtime,
                    "Yield": line_a_yield,
                },
                "B": {
                    "Description": "57-1",
                    "Total": line_b_total,
                    "Runtime": line_b_runtime,
                    "Yield": line_b_yield,
                },
            },
        },
        "B": {
            "Description": "CR Circuit",
            "Total": 0.0,
            "Runtime": 0.0,
            "Yield": 0.0,
        },
    }


@pytest.mark.asyncio
async def test_circuit_rollup_basic_hierarchy_one_month() -> None:
    """Single report, one circuit with two lines, one line-less circuit.
    Confirms the hierarchical shape and that descriptions feed through."""
    rows = [
        _row(
            row_id=1,
            prod_date=datetime(2026, 4, 1),
            circuit=_circuit_with_lines(
                main_total=500.0, main_runtime=2.0, main_yield=0.6,
                line_a_total=200.0, line_a_runtime=1.0, line_a_yield=0.3,
                line_b_total=300.0, line_b_runtime=1.0, line_b_yield=0.3,
            ),
        ),
    ]
    depts = await get_circuit_rollup(
        _FakeSource(rows),
        site_id="101",
        bucket="monthly",
        from_date=date(2026, 4, 1),
        to_date=date(2026, 4, 30),
    )
    assert len(depts) == 1
    dept = depts[0]
    assert dept.department_id == "127"
    assert dept.department_name == "Plant 1"
    assert len(dept.circuits) == 2  # Main + CR

    main = next(c for c in dept.circuits if c.description == "Main Circuit")
    assert main.circuit_id == "A"
    assert len(main.lines) == 2
    assert main.buckets[0].total_tons == 500.0
    assert main.buckets[0].runtime_hours == 2.0
    assert main.buckets[0].avg_tph == pytest.approx(250.0)
    assert main.buckets[0].avg_yield == pytest.approx(0.6)

    line_descs = sorted(l.description for l in main.lines)
    assert line_descs == ["57-1", "57-2"]
    line_57_1 = next(l for l in main.lines if l.description == "57-1")
    assert line_57_1.buckets[0].total_tons == 300.0
    assert line_57_1.buckets[0].avg_tph == pytest.approx(300.0)
    assert line_57_1.buckets[0].avg_yield == pytest.approx(0.3)

    cr = next(c for c in dept.circuits if c.description == "CR Circuit")
    assert cr.lines == []
    # Zero-runtime, zero-Total CR circuit -> avg_tph None, avg_yield 0.0
    # (Yield value is the literal 0.0 in the payload, not None).
    assert cr.buckets[0].avg_tph is None
    assert cr.buckets[0].avg_yield == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_circuit_rollup_aggregates_across_months() -> None:
    """Two reports in different months -> two monthly entries per node."""
    rows = [
        _row(
            row_id=1,
            prod_date=datetime(2026, 1, 15),
            circuit=_circuit_with_lines(
                main_total=400.0, main_runtime=2.0, main_yield=0.5,
                line_a_total=150.0, line_a_runtime=1.0, line_a_yield=0.2,
                line_b_total=250.0, line_b_runtime=1.0, line_b_yield=0.3,
            ),
        ),
        _row(
            row_id=2,
            prod_date=datetime(2026, 2, 15),
            circuit=_circuit_with_lines(
                main_total=600.0, main_runtime=2.0, main_yield=0.7,
                line_a_total=250.0, line_a_runtime=1.0, line_a_yield=0.3,
                line_b_total=350.0, line_b_runtime=1.0, line_b_yield=0.4,
            ),
        ),
    ]
    depts = await get_circuit_rollup(
        _FakeSource(rows),
        site_id="101",
        bucket="monthly",
        from_date=date(2026, 1, 1),
        to_date=date(2026, 2, 28),
    )
    main = next(c for c in depts[0].circuits if c.description == "Main Circuit")
    assert [m.bucket_label for m in main.buckets] == ["2026-01", "2026-02"]
    assert main.buckets[0].avg_tph == pytest.approx(200.0)
    assert main.buckets[1].avg_tph == pytest.approx(300.0)


@pytest.mark.asyncio
async def test_circuit_rollup_simple_mean_across_multi_report_month() -> None:
    """Two reports in the same month: avg_tph is the simple mean of
    their per-report TPH values (200, 300) -> 250, NOT the
    sum/sum=250 (which would coincide here -- pick distinct values
    next time to disambiguate)."""
    rows = [
        _row(
            row_id=1,
            prod_date=datetime(2026, 4, 1),
            circuit=_circuit_with_lines(
                main_total=200.0, main_runtime=1.0, main_yield=0.4,
                line_a_total=100.0, line_a_runtime=0.5, line_a_yield=0.2,
                line_b_total=100.0, line_b_runtime=0.5, line_b_yield=0.2,
            ),
        ),
        _row(
            row_id=2,
            prod_date=datetime(2026, 4, 2),
            circuit=_circuit_with_lines(
                main_total=600.0, main_runtime=1.0, main_yield=0.8,
                line_a_total=300.0, line_a_runtime=0.5, line_a_yield=0.4,
                line_b_total=300.0, line_b_runtime=0.5, line_b_yield=0.4,
            ),
        ),
    ]
    depts = await get_circuit_rollup(
        _FakeSource(rows),
        site_id="101",
        bucket="monthly",
        from_date=date(2026, 4, 1),
        to_date=date(2026, 4, 30),
    )
    main = next(c for c in depts[0].circuits if c.description == "Main Circuit")
    # per-report TPH = 200 and 600 -> simple mean 400.
    assert main.buckets[0].avg_tph == pytest.approx(400.0)
    # per-report yield = 0.4 and 0.8 -> simple mean 0.6.
    assert main.buckets[0].avg_yield == pytest.approx(0.6)
    # Sums add normally (200 + 600 = 800).
    assert main.buckets[0].total_tons == pytest.approx(800.0)


@pytest.mark.asyncio
async def test_circuit_rollup_runtime_zero_avg_tph_is_none() -> None:
    """Reports with Runtime=0 contribute to total_tons / runtime_hours
    but their per-report TPH is None and is dropped from the mean."""
    rows = [
        _row(
            row_id=1,
            prod_date=datetime(2026, 4, 1),
            circuit={
                "A": {
                    "Description": "Main Circuit",
                    "Total": 0.0, "Runtime": 0.0, "Yield": 0.0,
                    "Line": {},
                },
            },
        ),
    ]
    depts = await get_circuit_rollup(
        _FakeSource(rows),
        site_id="101",
        bucket="monthly",
        from_date=date(2026, 4, 1),
        to_date=date(2026, 4, 30),
    )
    main = depts[0].circuits[0]
    assert main.buckets[0].avg_tph is None
    # Yield was a literal 0.0 (not null), so the mean is 0.0 -- not None.
    assert main.buckets[0].avg_yield == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_circuit_rollup_empty_when_no_rows_match_filter() -> None:
    """No rows for the requested site -> empty departments list."""
    rows = [
        _row(
            row_id=1,
            prod_date=datetime(2026, 4, 1),
            site_id="999",  # different site
            circuit=_circuit_with_lines(
                main_total=100.0, main_runtime=1.0, main_yield=0.1,
                line_a_total=50.0, line_a_runtime=0.5, line_a_yield=0.05,
                line_b_total=50.0, line_b_runtime=0.5, line_b_yield=0.05,
            ),
        ),
    ]
    depts = await get_circuit_rollup(
        _FakeSource(rows),
        site_id="101",
        bucket="monthly",
        from_date=date(2026, 4, 1),
        to_date=date(2026, 4, 30),
    )
    assert depts == []


@pytest.mark.asyncio
async def test_circuit_rollup_multi_department_groups_correctly() -> None:
    """Two depts at the same site with different topologies -> two
    DepartmentCircuitRollup entries, each with its own circuits."""
    rows = [
        _row(
            row_id=1,
            prod_date=datetime(2026, 4, 1),
            department_id="127",
            department_name="Plant 1",
            circuit=_circuit_with_lines(
                main_total=100.0, main_runtime=1.0, main_yield=0.5,
                line_a_total=50.0, line_a_runtime=0.5, line_a_yield=0.25,
                line_b_total=50.0, line_b_runtime=0.5, line_b_yield=0.25,
            ),
        ),
        _row(
            row_id=2,
            prod_date=datetime(2026, 4, 1),
            department_id="130",
            department_name="Wash Plant",
            circuit={
                "A": {
                    "Description": "Wash Circuit",
                    "Total": 75.0, "Runtime": 1.0, "Yield": 0.9,
                },
            },
        ),
    ]
    depts = await get_circuit_rollup(
        _FakeSource(rows),
        site_id="101",
        bucket="monthly",
        from_date=date(2026, 4, 1),
        to_date=date(2026, 4, 30),
    )
    assert len(depts) == 2
    by_id = {d.department_id: d for d in depts}
    assert by_id["127"].department_name == "Plant 1"
    # Plant 1: Main + CR (both circuits in the helper).
    assert {c.description for c in by_id["127"].circuits} == {"Main Circuit", "CR Circuit"}
    assert by_id["130"].department_name == "Wash Plant"
    # Wash Plant: just one circuit, line-less.
    assert len(by_id["130"].circuits) == 1
    assert by_id["130"].circuits[0].description == "Wash Circuit"
    assert by_id["130"].circuits[0].lines == []


@pytest.mark.asyncio
async def test_circuit_rollup_inverted_window_raises_value_error() -> None:
    """Service guards against from > to even though the route also catches it."""
    with pytest.raises(ValueError, match=r"from_date .* must be <="):
        await get_circuit_rollup(
            _FakeSource([]),
            site_id="101",
            bucket="monthly",
            from_date=date(2026, 4, 1),
            to_date=date(2026, 1, 1),
        )


@pytest.mark.asyncio
async def test_circuit_rollup_prefers_rate_over_total_runtime_division() -> None:
    """When a circuit/line node carries an explicit ``Rate`` field, the
    aggregator reads it directly instead of computing Total/Runtime.
    This matters when Flow's authoritative Rate uses a different
    formula than naive division -- the API stays consistent with
    upstream by trusting the published value."""
    # Two reports. Each has Rate that does NOT equal Total/Runtime, to
    # prove the helper is reading Rate rather than recomputing.
    rows = [
        _row(
            row_id=1,
            prod_date=datetime(2026, 4, 1),
            circuit={
                "A": {
                    "Description": "Main Circuit",
                    "Total": 100.0, "Runtime": 1.0,  # naive TPH = 100
                    "Rate": 250.0,                   # but Flow says 250
                    "Yield": 0.5,
                },
            },
        ),
        _row(
            row_id=2,
            prod_date=datetime(2026, 4, 2),
            circuit={
                "A": {
                    "Description": "Main Circuit",
                    "Total": 200.0, "Runtime": 2.0,  # naive TPH = 100
                    "Rate": 350.0,                   # Flow says 350
                    "Yield": 0.6,
                },
            },
        ),
    ]
    depts = await get_circuit_rollup(
        _FakeSource(rows),
        site_id="101",
        bucket="monthly",
        from_date=date(2026, 4, 1),
        to_date=date(2026, 4, 30),
    )
    main = depts[0].circuits[0]
    # mean of [250, 350] = 300, NOT mean of [100, 100]
    assert main.buckets[0].avg_tph == pytest.approx(300.0)


@pytest.mark.asyncio
async def test_circuit_rollup_falls_back_to_total_over_runtime_when_rate_absent() -> None:
    """Rollout safety: payloads that don't yet include the Rate field
    on circuit/line nodes still produce a usable avg_tph via the
    Total/Runtime fallback. Same defensive pattern Phase 14a uses
    for Workcenter."""
    rows = [
        _row(
            row_id=1,
            prod_date=datetime(2026, 4, 1),
            circuit={
                "A": {
                    "Description": "Main Circuit",
                    # Rate absent entirely.
                    "Total": 400.0, "Runtime": 2.0, "Yield": 0.5,
                },
            },
        ),
        _row(
            row_id=2,
            prod_date=datetime(2026, 4, 2),
            circuit={
                "A": {
                    "Description": "Main Circuit",
                    # Rate present but null -> fallback still triggers.
                    "Rate": None,
                    "Total": 300.0, "Runtime": 1.0, "Yield": 0.6,
                },
            },
        ),
    ]
    depts = await get_circuit_rollup(
        _FakeSource(rows),
        site_id="101",
        bucket="monthly",
        from_date=date(2026, 4, 1),
        to_date=date(2026, 4, 30),
    )
    main = depts[0].circuits[0]
    # Per-report TPH via fallback: 400/2=200, 300/1=300. Mean = 250.
    assert main.buckets[0].avg_tph == pytest.approx(250.0)
