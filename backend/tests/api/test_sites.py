"""Tests for /api/sites."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_sites_returns_union_of_configured_and_data(client: TestClient) -> None:
    """The response is the union of configured site_names AND site IDs
    observed in the source's data.

    Configured-but-empty sites (Ardmore=100 has no test fixture rows)
    appear in the response anyway so the dashboard's dropdown can
    pre-show them ahead of data landing.

    Test fixture state:
      - Configured site_names: {"101": "Big Canyon Quarry", "100": "Ardmore Quarry"}
      - Source data: site_ids 101 + 102 (synthetic demo)
      - Union: {100, 101, 102} -- all three appear.

    Name resolution:
      - 100 -> "Ardmore Quarry" (configured, even though no data)
      - 101 -> "Big Canyon Quarry" (configured AND in data)
      - 102 -> "Site 102" (in data, no config entry, fallback)
    """
    resp = client.get("/api/sites")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 3
    ids = {s["id"] for s in body["sites"]}
    assert ids == {"100", "101", "102"}

    by_id = {s["id"]: s for s in body["sites"]}
    assert by_id["100"]["name"] == "Ardmore Quarry"
    assert by_id["101"]["name"] == "Big Canyon Quarry"
    assert by_id["102"]["name"] == "Site 102"


def test_sites_order_is_configured_first_then_data_only(client: TestClient) -> None:
    """Configured site_names control listing order (sites[0] is the
    dashboard's default no-deep-link site). Data-only ids without a
    config entry append after, so they don't quietly become the
    default just by virtue of publishing data first.

    _DEFAULT_SITE_NAMES order: 101, 100 -> BCQ first, Ardmore second.
    Fixture data adds 102 (not configured) -> appended at end.

    Expected: ["101", "100", "102"]
    """
    resp = client.get("/api/sites")
    ids = [s["id"] for s in resp.json()["sites"]]
    assert ids == ["101", "100", "102"]
