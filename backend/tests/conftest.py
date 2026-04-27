"""Shared pytest fixtures.

``client`` gives you a FastAPI ``TestClient`` wired to the real sample
CSV -- no env vars to set, no mocking of FS, and the production-report
source dependency is overridden per-test so anything on ``app.state``
from the normal startup doesn't leak between tests.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_production_report_source
from app.integrations.production_report.csv_source import CsvProductionReportSource
from app.main import app

_REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_CSV_PATH = _REPO_ROOT / "context" / "sample-data" / "production-report" / "sample.csv"


@pytest.fixture
def sample_csv_path() -> Path:
    assert SAMPLE_CSV_PATH.exists(), (
        f"Missing test fixture: {SAMPLE_CSV_PATH} -- tests depend on the "
        "committed sample TSV under context/sample-data/."
    )
    return SAMPLE_CSV_PATH


@pytest.fixture
def client(sample_csv_path: Path) -> Iterator[TestClient]:
    """TestClient with the production-report source bound to the sample CSV."""
    app.dependency_overrides[get_production_report_source] = lambda: CsvProductionReportSource(
        sample_csv_path
    )
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
