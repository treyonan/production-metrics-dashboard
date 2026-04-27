"""Tests for CsvProductionReportSource against the real sample TSV."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.integrations.production_report.csv_source import CsvProductionReportSource


@pytest.mark.asyncio
async def test_ping_ok_on_sample_file(sample_csv_path: Path) -> None:
    source = CsvProductionReportSource(sample_csv_path)
    status = await source.ping()
    assert status.ok is True
    assert "readable" in status.detail
    assert status.checked_at is not None


@pytest.mark.asyncio
async def test_ping_reports_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.csv"
    source = CsvProductionReportSource(missing)
    status = await source.ping()
    assert status.ok is False
    assert "not found" in status.detail.lower()


@pytest.mark.asyncio
async def test_fetch_rows_parses_every_row(sample_csv_path: Path) -> None:
    source = CsvProductionReportSource(sample_csv_path)
    rows = await source.fetch_rows()
    # Sample has 62 real (site 101) + 62 synthetic (site 102) rows.
    # Lower bound so appending more rows does not break this test.
    assert len(rows) >= 124
    for row in rows:
        assert isinstance(row.id, int)
        assert row.site_id in {"101", "102"}
        assert row.department_id in {"127", "130"}
        assert isinstance(row.payload, dict)
        assert "Metrics" in row.payload


@pytest.mark.asyncio
async def test_fetch_rows_covers_both_sites_and_departments(sample_csv_path: Path) -> None:
    source = CsvProductionReportSource(sample_csv_path)
    rows = await source.fetch_rows()
    pairs = {(r.site_id, r.department_id) for r in rows}
    assert pairs == {("101", "127"), ("101", "130"), ("102", "127"), ("102", "130")}


@pytest.mark.asyncio
async def test_list_site_ids_returns_sorted_distinct(sample_csv_path: Path) -> None:
    source = CsvProductionReportSource(sample_csv_path)
    ids = await source.list_site_ids()
    assert ids == ["101", "102"]
