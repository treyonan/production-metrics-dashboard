"""Service tests for the Phase 38 Production ID (PR / PRM) filter.

The dashboard's PR/PRM selection is now honored server-side by the three
rollup aggregations (workcenter, circuit, product). These tests pin the
shared filter helper and confirm each rollup drops non-matching reports:
"PR" excludes the PRM prefix, "PRM" matches only PRM, None/"all" keep all.
The Run Report export is intentionally NOT covered here -- it is left
unfiltered by design (PR/PRM are per-line items there, not aggregations).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pytest

from app.integrations.production_report.base import (
    ProductionReportRow,
    SourceStatus,
)
from app.services.production_report import (
    _matches_prod_id_filter,
    _validate_prod_id_filter,
    get_circuit_rollup,
    get_product_rollup,
    get_rollup,
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


def _row(*, row_id: int, prod_id: str, metrics: dict[str, Any]) -> ProductionReportRow:
    return ProductionReportRow(
        id=row_id,
        prod_date=datetime(2026, 4, 1),
        prod_id=prod_id,
        site_id="101",
        department_id="127",
        department_name="Secondary",
        payload={"Metrics": metrics},
        dtm=None,
    )


def _wc_metrics() -> dict[str, Any]:
    return {
        "Workcenter": {
            "Total": 100.0,
            "Runtime": 1.0,
            "Rate": 50.0,
            "Availability": 90.0,
            "Performance": 95.0,
        }
    }


def _circuit_metrics() -> dict[str, Any]:
    return {
        "Circuit": {
            "A": {"Description": "Main", "Total": 100.0, "Runtime": 1.0, "Yield": 0.5}
        }
    }


def _product_metrics() -> dict[str, Any]:
    return {
        "Produced_Metrics": {
            "Display_Chart": True,
            "Product0": {
                "Produced_Item_Code": "ST1",
                "Produced_Item_Description": "Surge",
                "Total": 100.0,
                "Rate": 50.0,
                "Yield": 0.5,
            },
        }
    }


def _rows(metrics_fn) -> list[ProductionReportRow]:
    # Two PR reports + one PRM report in a single (dept, day) bucket.
    return [
        _row(row_id=1, prod_id="PR_001", metrics=metrics_fn()),
        _row(row_id=2, prod_id="PR_002", metrics=metrics_fn()),
        _row(row_id=3, prod_id="PRM_001", metrics=metrics_fn()),
    ]


# --- pure helper -------------------------------------------------------


@pytest.mark.parametrize(
    "prod_id,flt,expected",
    [
        ("PR_001", None, True),
        ("PR_001", "all", True),
        ("PRM_001", "all", True),
        ("PR_001", "PR", True),
        ("PRM_001", "PR", False),  # "PR" must EXCLUDE the PRM prefix
        ("PRM_001", "PRM", True),
        ("PR_001", "PRM", False),
        ("", "PR", False),
        ("", "PRM", False),
    ],
)
def test_matches_prod_id_filter(prod_id: str, flt: str | None, expected: bool) -> None:
    assert _matches_prod_id_filter(prod_id, flt) is expected


def test_validate_prod_id_filter_accepts_known() -> None:
    for v in (None, "all", "PR", "PRM"):
        _validate_prod_id_filter(v)  # must not raise


def test_validate_prod_id_filter_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        _validate_prod_id_filter("PRX")


# --- each rollup drops non-matching reports ----------------------------


@pytest.mark.asyncio
async def test_get_rollup_filters_pr_prm() -> None:
    async def count(**kw: Any) -> int:
        out = await get_rollup(
            _FakeSource(_rows(_wc_metrics)),
            site_id="101",
            bucket="daily",
            from_date=date(2026, 4, 1),
            to_date=date(2026, 4, 1),
            **kw,
        )
        return out[0].report_count if out else 0

    assert await count() == 3  # default -> all
    assert await count(prod_id_filter="all") == 3
    assert await count(prod_id_filter="PR") == 2  # excludes PRM
    assert await count(prod_id_filter="PRM") == 1


@pytest.mark.asyncio
async def test_get_rollup_rejects_bad_filter() -> None:
    with pytest.raises(ValueError):
        await get_rollup(
            _FakeSource([]),
            site_id="101",
            bucket="daily",
            from_date=date(2026, 4, 1),
            to_date=date(2026, 4, 1),
            prod_id_filter="nope",
        )


@pytest.mark.asyncio
async def test_get_circuit_rollup_filters_pr_prm() -> None:
    src = _FakeSource(_rows(_circuit_metrics))

    async def count(**kw: Any) -> int:
        depts = await get_circuit_rollup(
            src,
            site_id="101",
            bucket="daily",
            from_date=date(2026, 4, 1),
            to_date=date(2026, 4, 1),
            **kw,
        )
        return depts[0].circuits[0].buckets[0].report_count if depts else 0

    assert await count() == 3
    assert await count(prod_id_filter="PR") == 2
    assert await count(prod_id_filter="PRM") == 1


@pytest.mark.asyncio
async def test_get_product_rollup_filters_pr_prm() -> None:
    src = _FakeSource(_rows(_product_metrics))

    async def count(**kw: Any) -> int:
        depts = await get_product_rollup(
            src,
            site_id="101",
            bucket="daily",
            from_date=date(2026, 4, 1),
            to_date=date(2026, 4, 1),
            **kw,
        )
        return depts[0].products[0].buckets[0].report_count if depts else 0

    assert await count() == 3
    assert await count(prod_id_filter="PR") == 2
    assert await count(prod_id_filter="PRM") == 1
