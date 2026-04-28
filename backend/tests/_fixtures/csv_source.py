"""Test-only CSV-backed ProductionReportSource.

TEST INFRASTRUCTURE -- not registered in production. Phase 13 (2026-04-28)
removed CSV from the production code path; this implementation lives
under ``tests/_fixtures/`` so the API tests can keep using a
deterministic, file-backed source without spinning up SQL Server.

Why we kept it instead of mocking SQL:
- ~30 API tests verify route shape, parameter validation, Pydantic
  envelope serialization, and service-layer aggregations end-to-end.
  They need ANY ProductionReportSource implementation that returns
  deterministic data.
- Reading the committed sample TSV under
  ``context/sample-data/production-report/sample.csv`` exercises real
  parsing logic (date format, doubled-quote JSON unescape) and
  catches more bugs than a hand-authored Python literal would.
- Production code under ``backend/app/`` cannot import this module
  (different package path); the only consumer is
  ``tests/conftest.py``.

Notes on the file shape (unchanged from pre-Phase-13):

* The file has a ``.csv`` extension but is tab-delimited. Python's
  ``csv`` module handles the CSV-style quoted JSON column cleanly once
  given the right delimiter.
* ``PRODDATE`` and ``DTM`` are formatted as ``M/D/YY H:MM``.
* ``DTM`` may be empty. Every row in the committed sample has a value,
  but the SQL column is nullable so the parser tolerates empty cells
  (returns ``None`` for dtm).
* The ``PAYLOAD`` column is a JSON string with doubled-up ``""`` escapes
  that ``csv.DictReader`` unquotes automatically.
"""

from __future__ import annotations

import asyncio
import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.integrations.production_report.base import ProductionReportRow, SourceStatus

_DATE_FMT = "%m/%d/%y %H:%M"


class CsvProductionReportSource:
    """Reads production-report rows from a tab-delimited export file.

    Test-only. See module docstring.
    """

    name = "csv:production_report"

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    async def ping(self) -> SourceStatus:
        return await asyncio.to_thread(self._ping_sync)

    async def fetch_rows(self) -> list[ProductionReportRow]:
        return await asyncio.to_thread(self._fetch_rows_sync)

    async def list_site_ids(self) -> list[str]:
        rows = await self.fetch_rows()
        return sorted({r.site_id for r in rows})

    # ---- sync impls (run under asyncio.to_thread) --------------------------

    def _ping_sync(self) -> SourceStatus:
        now = datetime.now(UTC)
        try:
            if not self._path.exists():
                return SourceStatus(
                    ok=False,
                    detail=f"File not found: {self._path}",
                    checked_at=now,
                )
            if not self._path.is_file():
                return SourceStatus(
                    ok=False,
                    detail=f"Path is not a file: {self._path}",
                    checked_at=now,
                )
            with self._path.open("r", encoding="utf-8") as f:
                header = f.readline()
            if not header.strip():
                return SourceStatus(
                    ok=False,
                    detail="File is empty",
                    checked_at=now,
                )
            return SourceStatus(
                ok=True,
                detail=f"{self._path.name} readable",
                checked_at=now,
            )
        except OSError as exc:
            return SourceStatus(
                ok=False,
                detail=f"OS error reading file: {exc}",
                checked_at=now,
            )

    def _fetch_rows_sync(self) -> list[ProductionReportRow]:
        rows: list[ProductionReportRow] = []
        with self._path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for raw in reader:
                rows.append(self._parse_row(raw))
        return rows

    @staticmethod
    def _parse_row(raw: dict[str, Any]) -> ProductionReportRow:
        # DTM may be empty in future rows (SQL column is nullable);
        # committed sample always has a value.
        dtm_raw = (raw.get("DTM") or "").strip()
        dtm = datetime.strptime(dtm_raw, _DATE_FMT) if dtm_raw else None
        # Phase 13 (2026-04-28): department_name is non-null in the
        # source-row contract but the test fixture's sample.csv has no
        # Departments column. Synthesize the same "Dept <id>" fallback
        # the SQL source uses on a JOIN miss so test rows look like
        # production rows without a JOIN match.
        dept_id = raw["DEPARTMENT_ID"]
        return ProductionReportRow(
            id=int(raw["ID"]),
            prod_date=datetime.strptime(raw["PRODDATE"], _DATE_FMT),
            prod_id=raw["PROD_ID"],
            site_id=raw["SITE_ID"],
            department_id=dept_id,
            department_name=f"Dept {dept_id}",
            payload=json.loads(raw["PAYLOAD"]),
            dtm=dtm,
        )
