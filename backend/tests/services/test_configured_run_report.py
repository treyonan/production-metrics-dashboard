"""Service tests for ``get_configured_run_report`` (Phase 31).

The live stored procedure can't run in CI, so the SP execution is stood
in by a fake source (same pattern as ``test_flow_client``'s FakeFlowClient).
These tests verify the service's assembly logic: department enumeration
from production-report rows, per-department SP calls, name resolution,
ordering, window filtering, and the inclusive end-of-day window passed to
the SP.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pytest

from app.integrations.production_report.base import (
    ProductionReportRow,
    SourceStatus,
)
from app.services.production_report import get_configured_run_report


def _row(
    rid: int,
    dept_id: str,
    dept_name: str,
    prod_date: datetime,
    site_id: str = "101",
) -> ProductionReportRow:
    return ProductionReportRow(
        id=rid,
        prod_date=prod_date,
        prod_id=f"PR{rid}",
        site_id=site_id,
        department_id=dept_id,
        department_name=dept_name,
        payload={},
        dtm=None,
    )


class _FakeProdSource:
    name = "fake:prod"

    def __init__(self, rows: list[ProductionReportRow]) -> None:
        self._rows = rows

    async def ping(self) -> SourceStatus:  # pragma: no cover
        return SourceStatus(ok=True, detail="ok", checked_at=datetime.now())

    async def fetch_rows(self) -> list[ProductionReportRow]:
        return list(self._rows)

    async def list_site_ids(self) -> list[str]:  # pragma: no cover
        return sorted({r.site_id for r in self._rows})


class _FakeRunReportSource:
    """Records each fetch_report call; returns canned per-dept columns/rows."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, datetime, datetime]] = []

    async def fetch_report(
        self, *, site_id: str, department_id: str, start: datetime, end: datetime
    ) -> tuple[list[str], list[list[Any]]]:
        self.calls.append((site_id, department_id, start, end))
        columns = ["Date", "PROD_ID", f"Dept{department_id}Col"]
        rows = [["04/01/2026", f"PR-{department_id}", 123]]
        return columns, rows


@pytest.mark.asyncio
async def test_loops_each_department_once_numeric_sorted() -> None:
    rows = [
        _row(1, "10", "Secondary", datetime(2026, 4, 1)),
        _row(2, "10", "Secondary", datetime(2026, 4, 2)),
        _row(3, "2", "Wash Plant", datetime(2026, 4, 2)),
    ]
    prod = _FakeProdSource(rows)
    runrep = _FakeRunReportSource()

    out = await get_configured_run_report(
        prod, runrep, site_id="101",
        from_date=date(2026, 4, 1), to_date=date(2026, 4, 30),
    )

    # One result per distinct department, numeric-id sorted (2 before 10).
    assert [d.department_id for d in out] == ["2", "10"]
    assert [d.department_name for d in out] == ["Wash Plant", "Secondary"]
    # SP invoked once per department.
    assert len(runrep.calls) == 2
    # Columns/rows pass straight through.
    assert out[0].columns[-1] == "Dept2Col"
    assert out[1].columns[-1] == "Dept10Col"
    assert out[0].rows == [["04/01/2026", "PR-2", 123]]


@pytest.mark.asyncio
async def test_filters_to_site_and_window_and_passes_inclusive_endofday() -> None:
    rows = [
        _row(1, "10", "Secondary", datetime(2026, 4, 1), site_id="101"),
        _row(2, "10", "Secondary", datetime(2026, 4, 1), site_id="100"),  # other site
        _row(3, "11", "Other", datetime(2026, 5, 1), site_id="101"),       # outside window
    ]
    prod = _FakeProdSource(rows)
    runrep = _FakeRunReportSource()

    out = await get_configured_run_report(
        prod, runrep, site_id="101",
        from_date=date(2026, 4, 1), to_date=date(2026, 4, 30),
    )

    assert [d.department_id for d in out] == ["10"]
    assert len(runrep.calls) == 1
    _site, _dept, start, end = runrep.calls[0]
    assert (start.hour, start.minute, start.second) == (0, 0, 0)
    assert (end.hour, end.minute) == (23, 59)  # inclusive end-of-day


@pytest.mark.asyncio
async def test_inverted_window_raises() -> None:
    prod = _FakeProdSource([])
    runrep = _FakeRunReportSource()
    with pytest.raises(ValueError):
        await get_configured_run_report(
            prod, runrep, site_id="101",
            from_date=date(2026, 4, 30), to_date=date(2026, 4, 1),
        )


@pytest.mark.asyncio
async def test_site_with_no_rows_returns_empty() -> None:
    prod = _FakeProdSource([_row(1, "10", "Secondary", datetime(2026, 4, 1), site_id="100")])
    runrep = _FakeRunReportSource()
    out = await get_configured_run_report(
        prod, runrep, site_id="999",
        from_date=date(2026, 4, 1), to_date=date(2026, 4, 30),
    )
    assert out == []
    assert runrep.calls == []
