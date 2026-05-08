"""Tests for /api/sites."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_sites_returns_configured_and_fallback_names(client: TestClient) -> None:
    """Configured sites use their settings name; sites in the data but
    not in settings fall through to the generic 'Site <id>' label.

    The test fixture's source returns two site IDs (101 and 102). After
    Phase 24 the synthetic-demo entry for 102 was removed from the
    default config, so 102 hits the fallback. 101 keeps its configured
    name. New site 100 (Ardmore Quarry) is in the config but not in
    the test fixture's data, so it doesn't appear in the response.
    """
    resp = client.get("/api/sites")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    ids = {s["id"] for s in body["sites"]}
    assert ids == {"101", "102"}

    by_id = {s["id"]: s for s in body["sites"]}
    # 101 -> configured name from settings.
    assert by_id["101"]["name"] == "Big Canyon Quarry"
    # 102 -> fallback (no config entry).
    assert by_id["102"]["name"] == "Site 102"


def test_sites_sorted_by_id(client: TestClient) -> None:
    resp = client.get("/api/sites")
    body = resp.json()
    ids = [s["id"] for s in body["sites"]]
    assert ids == sorted(ids)
