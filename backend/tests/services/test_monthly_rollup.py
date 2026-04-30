"""Service-level tests for ``get_monthly_rollup`` -- Phase 14a additions.

Constructs ``ProductionReportRow`` instances directly with known
``Workcenter.Rate`` / ``Workcenter.Availability`` values (and the
fallback denominators ``Total`` / ``Runtime`` / ``Scheduled_Runtime``)
to verify simple-mean aggregation, fallback resolution, and None
propagation when no report in a bucket has a usable value.

Indirectly exercises ``_avg_tph_fed_for_report``,
``_avg_runtime_pct_for_report``, and ``_mean_or_none`` via the
``get_monthly_rollup`` boundary -- the helpers themselves are
private, but the service emits their output as fields on each
``MonthlyRollup``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pytest

from app.integrations.production_report.base import (
    ProductionReportRow,
    SourceStatus,
)
from app.services.production_report import get_monthly_rollup


def _row(
    *,
    row_id: int,
    prod_date: datetime,
    workcenter: dict[str, Any] | None,
    site_id: str = "101",
    department_id: str = "127",
) -> ProductionReportRow:
    """Construct a row with whatever ``Workcenter`` payload the test needs.

    The Phase 14a helpers ignore ``Site``, ``Circuit``, and per-asset
    keys -- only the ``Workcenter`` object matters here.
    """
    metrics: dict[str, Any] = {}
    if workcenter is not None:
        metrics["Workcenter"] = workcenter
    return ProductionReportRow(
        id=row_id,
        prod_date=prod_date,
        prod_id=f"PR_TEST_{row_id:03d}",
        site_id=site_id,
        department_id=department_id,
        department_name=f"Dept {department_id}",
        payload={"Metrics": metrics},
        dtm=None,
    )


class _FakeSource:
    """Minimal ProductionReportSource implementation backed by a list."""

    name = "fake:test"

    def __init__(self, rows: list[ProductionReportRow]) -> None:
        self._rows = rows

    async def ping(self) -> SourceStatus:  # pragma: no cover -- not exercised
        return SourceStatus(ok=True, detail="ok", checked_at=datetime.now())

    async def fetch_rows(self) -> list[ProductionReportRow]:
        return list(self._rows)

    async def list_site_ids(self) -> list[str]:  # pragma: no cover
        return sorted({r.site_id for r in self._rows})


@pytest.mark.asyncio
async def test_avg_tph_fed_uses_workcenter_rate_when_present() -> None:
    """Three reports in the same month with explicit Rate values average
    to their arithmetic mean. Fallback path is not exercised here."""
    rows = [
        _row(
            row_id=i,
            prod_date=datetime(2026, 4, day),
            workcenter={"Rate": rate, "Runtime": 5.0, "Scheduled_Runtime": 8.0},
        )
        for i, (day, rate) in enumerate([(1, 600.0), (2, 800.0), (3, 1000.0)], start=1)
    ]
    rollups = await get_monthly_rollup(
        _FakeSource(rows),
        site_id="101",
        from_month=date(2026, 4, 1),
        to_month=date(2026, 4, 30),
    )
    assert len(rollups) == 1
    assert rollups[0].avg_tph_fed == pytest.approx(800.0)


@pytest.mark.asyncio
async def test_avg_tph_fed_falls_back_to_total_over_runtime_when_rate_null() -> None:
    """When ``Rate`` is null, fallback divides ``Total`` by ``Runtime``."""
    rows = [
        _row(
            row_id=1,
            prod_date=datetime(2026, 4, 1),
            workcenter={"Rate": None, "Total": 1000.0, "Runtime": 5.0},
        )
    ]
    rollups = await get_monthly_rollup(
        _FakeSource(rows),
        site_id="101",
        from_month=date(2026, 4, 1),
        to_month=date(2026, 4, 30),
    )
    assert rollups[0].avg_tph_fed == pytest.approx(200.0)


@pytest.mark.asyncio
async def test_avg_tph_fed_skips_unusable_reports_in_average() -> None:
    """Reports whose Rate is null AND whose Total/Runtime fallback
    can't be computed are dropped from the mean. The remaining usable
    reports' Rates are averaged."""
    rows = [
        _row(
            row_id=1,
            prod_date=datetime(2026, 4, 1),
            workcenter={"Rate": 600.0},
        ),
        _row(
            row_id=2,
            prod_date=datetime(2026, 4, 2),
            workcenter={"Rate": None, "Total": None, "Runtime": None},
        ),
        _row(
            row_id=3,
            prod_date=datetime(2026, 4, 3),
            workcenter={"Rate": 1000.0},
        ),
    ]
    rollups = await get_monthly_rollup(
        _FakeSource(rows),
        site_id="101",
        from_month=date(2026, 4, 1),
        to_month=date(2026, 4, 30),
    )
    assert rollups[0].avg_tph_fed == pytest.approx(800.0)
    assert rollups[0].report_count == 3  # all three counted as reports


@pytest.mark.asyncio
async def test_avg_tph_fed_none_when_every_report_unusable() -> None:
    """A bucket where no report has a usable Rate (and no fallback is
    computable) produces avg_tph_fed=None -- the chart shows a gap."""
    rows = [
        _row(
            row_id=1,
            prod_date=datetime(2026, 4, 1),
            workcenter={"Rate": None, "Runtime": 0.0},  # zero runtime kills fallback
        ),
        _row(
            row_id=2,
            prod_date=datetime(2026, 4, 2),
            workcenter={},  # empty workcenter
        ),
    ]
    rollups = await get_monthly_rollup(
        _FakeSource(rows),
        site_id="101",
        from_month=date(2026, 4, 1),
        to_month=date(2026, 4, 30),
    )
    assert rollups[0].avg_tph_fed is None


@pytest.mark.asyncio
async def test_avg_runtime_pct_uses_workcenter_availability_when_present() -> None:
    """Availability values average to their mean."""
    rows = [
        _row(
            row_id=i,
            prod_date=datetime(2026, 4, day),
            workcenter={"Availability": pct, "Runtime": 8.0, "Scheduled_Runtime": 8.0},
        )
        for i, (day, pct) in enumerate([(1, 49.0), (2, 46.0), (3, 56.0), (4, 62.0)], start=1)
    ]
    rollups = await get_monthly_rollup(
        _FakeSource(rows),
        site_id="101",
        from_month=date(2026, 4, 1),
        to_month=date(2026, 4, 30),
    )
    assert rollups[0].avg_runtime_pct == pytest.approx(53.25)


@pytest.mark.asyncio
async def test_avg_runtime_pct_falls_back_to_runtime_over_scheduled_capped_at_100() -> None:
    """When Availability is null, fallback computes Runtime /
    Scheduled_Runtime * 100, capped at 100 (a workcenter that runs
    longer than scheduled isn't 'more available than 100%')."""
    rows = [
        _row(
            row_id=1,
            prod_date=datetime(2026, 4, 1),
            workcenter={"Availability": None, "Runtime": 4.0, "Scheduled_Runtime": 8.0},
        ),
        _row(
            row_id=2,
            prod_date=datetime(2026, 4, 2),
            # 5.1 / 5.0 = 102%, cap at 100
            workcenter={"Availability": None, "Runtime": 5.1, "Scheduled_Runtime": 5.0},
        ),
    ]
    rollups = await get_monthly_rollup(
        _FakeSource(rows),
        site_id="101",
        from_month=date(2026, 4, 1),
        to_month=date(2026, 4, 30),
    )
    # mean of 50.0 (4/8 * 100) and 100.0 (capped from 102) = 75.0
    assert rollups[0].avg_runtime_pct == pytest.approx(75.0)


@pytest.mark.asyncio
async def test_avg_runtime_pct_none_when_all_unusable() -> None:
    """Bucket with every report missing both Availability and the
    fallback inputs collapses to None."""
    rows = [
        _row(
            row_id=1,
            prod_date=datetime(2026, 4, 1),
            workcenter={"Availability": None, "Scheduled_Runtime": 0.0},
        ),
    ]
    rollups = await get_monthly_rollup(
        _FakeSource(rows),
        site_id="101",
        from_month=date(2026, 4, 1),
        to_month=date(2026, 4, 30),
    )
    assert rollups[0].avg_runtime_pct is None


@pytest.mark.asyncio
async def test_avg_performance_pct_uses_workcenter_performance() -> None:
    """Phase 14a Performance %: simple mean of per-report
    Workcenter.Performance (no fallback chain -- if Performance is null
    upstream, the report drops out of the mean)."""
    rows = [
        _row(
            row_id=i,
            prod_date=datetime(2026, 4, day),
            workcenter={"Performance": p},
        )
        for i, (day, p) in enumerate([(1, 60.0), (2, 80.0), (3, 100.0)], start=1)
    ]
    rollups = await get_monthly_rollup(
        _FakeSource(rows),
        site_id="101",
        from_month=date(2026, 4, 1),
        to_month=date(2026, 4, 30),
    )
    assert rollups[0].avg_performance_pct == pytest.approx(80.0)


@pytest.mark.asyncio
async def test_avg_performance_pct_skips_null_reports() -> None:
    """Reports with Performance=null are dropped from the mean rather
    than treated as zero. Three reports, two usable values, one null
    -> mean of just the two."""
    rows = [
        _row(row_id=1, prod_date=datetime(2026, 4, 1), workcenter={"Performance": 70.0}),
        _row(row_id=2, prod_date=datetime(2026, 4, 2), workcenter={"Performance": None}),
        _row(row_id=3, prod_date=datetime(2026, 4, 3), workcenter={"Performance": 90.0}),
    ]
    rollups = await get_monthly_rollup(
        _FakeSource(rows),
        site_id="101",
        from_month=date(2026, 4, 1),
        to_month=date(2026, 4, 30),
    )
    assert rollups[0].avg_performance_pct == pytest.approx(80.0)
    assert rollups[0].report_count == 3  # all three counted as reports


@pytest.mark.asyncio
async def test_avg_performance_pct_none_when_all_reports_null() -> None:
    """Bucket where every report has Performance=null collapses to None.
    Chart consumers render None as a gap."""
    rows = [
        _row(row_id=1, prod_date=datetime(2026, 4, 1), workcenter={"Performance": None}),
        _row(row_id=2, prod_date=datetime(2026, 4, 2), workcenter={}),
    ]
    rollups = await get_monthly_rollup(
        _FakeSource(rows),
        site_id="101",
        from_month=date(2026, 4, 1),
        to_month=date(2026, 4, 30),
    )
    assert rollups[0].avg_performance_pct is None
