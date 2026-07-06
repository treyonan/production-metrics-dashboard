"""Service tests for ``get_product_rollup`` -- Phase 37.

Builds ProductionReportRow instances with synthetic Produced_Metrics
blocks to verify the per-product aggregation (sum tons / mean rate /
mean yield), the Display_Chart gate, keying by Produced_Item_Code
across positional slots, bucketing, and Yield None-safety.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pytest

from app.integrations.production_report.base import (
    ProductionReportRow,
    SourceStatus,
)
from app.services.production_report import get_product_rollup


def _row(
    *,
    row_id: int,
    prod_date: datetime,
    produced_metrics: dict[str, Any] | None,
    site_id: str = "101",
    department_id: str = "127",
    department_name: str = "Secondary",
) -> ProductionReportRow:
    metrics: dict[str, Any] = {}
    if produced_metrics is not None:
        metrics["Produced_Metrics"] = produced_metrics
    return ProductionReportRow(
        id=row_id,
        prod_date=prod_date,
        prod_id=f"PR_{row_id:03d}",
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


def _prod(
    code: str, desc: str, total: float, rate: float, yld: float | None = None
) -> dict[str, Any]:
    d: dict[str, Any] = {
        "Produced_Item_Code": code,
        "Produced_Item_Description": desc,
        "Total": total,
        "Rate": rate,
    }
    if yld is not None:
        d["Yield"] = yld
    return d


@pytest.mark.asyncio
async def test_sum_mean_aggregation_keyed_by_code() -> None:
    """Same product (ST7900) in the Product0 slot of two reports aggregates
    by CODE, not by slot: total sums, tph/yield are simple means."""
    pm1 = {
        "Display_Chart": True,
        "Product0": _prod("ST7900", '10" SURGE', 1000, 150, 0.40),
        "Product1": _prod("ST5450", "CRUSHER RUN", 2000, 180, 0.53),
    }
    pm2 = {"Display_Chart": True, "Product0": _prod("ST7900", '10" SURGE', 1500, 250, 0.60)}
    depts = await get_product_rollup(
        _FakeSource([
            _row(row_id=1, prod_date=datetime(2026, 4, 1), produced_metrics=pm1),
            _row(row_id=2, prod_date=datetime(2026, 4, 1), produced_metrics=pm2),
        ]),
        site_id="101", bucket="daily",
        from_date=date(2026, 4, 1), to_date=date(2026, 4, 30),
    )
    assert len(depts) == 1
    products = {p.description: p for p in depts[0].products}
    surge = products['10" SURGE'].buckets[0]
    assert surge.total_tons == pytest.approx(2500.0)   # 1000 + 1500
    assert surge.avg_tph == pytest.approx(200.0)        # mean(150, 250)
    assert surge.avg_yield == pytest.approx(0.50)        # mean(0.40, 0.60)
    assert surge.report_count == 2
    assert products["CRUSHER RUN"].buckets[0].total_tons == pytest.approx(2000.0)


@pytest.mark.asyncio
async def test_display_chart_off_yields_no_products() -> None:
    pm = {"Display_Chart": False, "Product0": _prod("ST7900", "X", 100, 10)}
    depts = await get_product_rollup(
        _FakeSource([_row(row_id=1, prod_date=datetime(2026, 4, 1), produced_metrics=pm)]),
        site_id="101", bucket="daily",
        from_date=date(2026, 4, 1), to_date=date(2026, 4, 30),
    )
    assert depts == []


@pytest.mark.asyncio
async def test_missing_produced_metrics_yields_no_products() -> None:
    depts = await get_product_rollup(
        _FakeSource([_row(row_id=1, prod_date=datetime(2026, 4, 1), produced_metrics=None)]),
        site_id="101", bucket="daily",
        from_date=date(2026, 4, 1), to_date=date(2026, 4, 30),
    )
    assert depts == []


@pytest.mark.asyncio
async def test_monthly_bucketing_sums_across_days() -> None:
    pm = {"Display_Chart": True, "Product0": _prod("ST7900", "Surge", 1000, 150, 0.4)}
    depts = await get_product_rollup(
        _FakeSource([
            _row(row_id=1, prod_date=datetime(2026, 4, 1), produced_metrics=pm),
            _row(row_id=2, prod_date=datetime(2026, 4, 15), produced_metrics=pm),
        ]),
        site_id="101", bucket="monthly",
        from_date=date(2026, 4, 1), to_date=date(2026, 4, 30),
    )
    buckets = depts[0].products[0].buckets
    assert [b.bucket_label for b in buckets] == ["2026-04"]
    assert buckets[0].total_tons == pytest.approx(2000.0)


@pytest.mark.asyncio
async def test_yield_none_when_absent() -> None:
    pm = {"Display_Chart": True, "Product0": _prod("ST7900", "No Yield", 500, 50)}
    depts = await get_product_rollup(
        _FakeSource([_row(row_id=1, prod_date=datetime(2026, 4, 1), produced_metrics=pm)]),
        site_id="101", bucket="daily",
        from_date=date(2026, 4, 1), to_date=date(2026, 4, 30),
    )
    assert depts[0].products[0].buckets[0].avg_yield is None


@pytest.mark.asyncio
async def test_inverted_window_raises() -> None:
    with pytest.raises(ValueError):
        await get_product_rollup(
            _FakeSource([]), site_id="101", bucket="daily",
            from_date=date(2026, 4, 30), to_date=date(2026, 4, 1),
        )
