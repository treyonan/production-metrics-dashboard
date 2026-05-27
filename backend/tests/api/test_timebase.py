"""Tests for /api/timebase/* routes."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.routes.timebase import (
    get_timebase_catalog,
    get_timebase_client_registry,
    get_timebase_history_cache,
)
from app.integrations.timebase.cache import TimebaseHistoryCache
from app.integrations.timebase.catalog import load_catalog
from app.integrations.timebase.client import TimebaseClient, TimebaseClientRegistry
from app.main import app

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def real_catalog() -> Any:
    """Use the shipped catalog.yaml -- this is the production data."""
    return load_catalog()


@pytest.fixture
def make_mock_client():
    """Build a TimebaseClient backed by a per-test MockTransport handler.

    Takes the catalog's dataset for the site so the route can compose
    elementIds correctly. Caller is responsible for closing the client
    (the wire_timebase fixture handles registry cleanup via aclose_all).
    """

    async def _build(
        site_id: str,
        handler,
        *,
        dataset: str = "IAP_TEST_Controls",
    ) -> TimebaseClient:
        client = TimebaseClient(
            site_id=site_id,
            base_url="http://timebase.test:8080",
            dataset=dataset,
            transport=httpx.MockTransport(handler),
        )
        await client.aopen()
        return client

    return _build


@pytest.fixture
def wire_timebase(real_catalog):
    """Wire all three timebase deps for the test, then clean up.

    Usage::

        def test_xxx(wire_timebase, ...):
            with wire_timebase(clients={"101": mock_client}) as testclient:
                resp = testclient.post(...)
    """

    @contextmanager
    def _ctx(
        *,
        clients: dict[str, TimebaseClient] | None = None,
        catalog=None,
    ):
        registry = TimebaseClientRegistry()
        for c in (clients or {}).values():
            registry.add(c)
        app.dependency_overrides[get_timebase_client_registry] = lambda: registry
        if catalog is None:
            catalog = real_catalog
        app.dependency_overrides[get_timebase_catalog] = lambda: catalog
        # One cache instance across the whole block so cache-hit tests work.
        shared_cache = TimebaseHistoryCache()
        app.dependency_overrides[get_timebase_history_cache] = lambda: shared_cache
        try:
            with TestClient(app) as tc:
                yield tc
        finally:
            for dep in (
                get_timebase_client_registry,
                get_timebase_catalog,
                get_timebase_history_cache,
            ):
                app.dependency_overrides.pop(dep, None)

    return _ctx


# ============================================================================
# /catalog
# ============================================================================


def test_catalog_returns_all_sites(wire_timebase) -> None:
    with wire_timebase() as tc:
        resp = tc.get("/api/timebase/catalog")
    assert resp.status_code == 200
    body = resp.json()
    site_ids = [s["site_id"] for s in body["sites"]]
    assert "101" in site_ids


def test_catalog_by_site_id_returns_one_site(wire_timebase) -> None:
    with wire_timebase() as tc:
        resp = tc.get("/api/timebase/catalog/101")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["sites"]) == 1
    site = body["sites"][0]
    assert site["site_id"] == "101"
    secondary = next(d for d in site["departments"] if d["name"] == "Secondary")
    conveyor = next(
        ac for ac in secondary["asset_classes"] if ac["class"] == "Conveyor"
    )
    c1 = next(a for a in conveyor["assets"] if a["asset"] == "C1")
    tph = next(m for m in c1["metrics"] if m["metric_key"] == "belt_scale_tph")
    assert tph["element_id"] == (
        "IAP_BCQ_Controls:Big_Canyon/Secondary/Conveyor/C1"
        "/Process_Data/Belt_Scale/TPH"
    )
    assert tph["display_name"] == "Belt Scale TPH"
    assert tph["unit"] == "tph"


def test_catalog_response_excludes_base_url(wire_timebase) -> None:
    """Internal historian IPs are not exposed via the public API."""
    with wire_timebase() as tc:
        resp = tc.get("/api/timebase/catalog/101")
    assert resp.status_code == 200
    body = resp.text
    assert "10.44.135.12" not in body
    assert "base_url" not in body


def test_catalog_unknown_site_returns_404(wire_timebase) -> None:
    with wire_timebase() as tc:
        resp = tc.get("/api/timebase/catalog/999")
    assert resp.status_code == 404
    assert "Unknown site_id" in resp.json()["detail"]


def test_catalog_503_when_not_loaded() -> None:
    """When the catalog isn't on app.state, /catalog returns 503.

    State mutation must happen AFTER TestClient enters its context
    (i.e. after the lifespan runs and populates app.state), otherwise
    the lifespan loads the real catalog and the override is wiped.
    """
    app.dependency_overrides.pop(get_timebase_catalog, None)
    with TestClient(app) as tc:
        app.state.timebase_catalog = None  # post-lifespan
        resp = tc.get("/api/timebase/catalog")
    assert resp.status_code == 503
    assert "catalog unavailable" in resp.json()["detail"].lower()


# ============================================================================
# /history -- unified: tag_paths + server-side dataset composition
# ============================================================================


_TAG_PATH = "Big_Canyon/Secondary/Conveyor/C1/Process_Data/Belt_Scale/TPH"
_DATASET = "IAP_BCQ_Controls"
_COMPOSED_ELEMENT_ID = f"{_DATASET}:{_TAG_PATH}"

_UPSTREAM_RESPONSE = {
    _COMPOSED_ELEMENT_ID: {
        "data": [
            {"value": 3, "quality": "GOOD", "timestamp": "2026-04-30T22:36:06.110Z"},
            {"value": 44, "quality": "GOOD", "timestamp": "2026-05-01T13:29:57.952Z"},
        ]
    }
}


@pytest.mark.asyncio
async def test_history_composes_element_ids_and_rekeys_response(
    wire_timebase, make_mock_client
) -> None:
    """Server composes <dataset>:<tag_path>, response is re-keyed back."""
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=_UPSTREAM_RESPONSE)

    client = await make_mock_client("101", handler, dataset=_DATASET)
    try:
        with wire_timebase(clients={"101": client}) as tc:
            resp = tc.post(
                "/api/timebase/history?site_id=101",
                json={
                    "tag_paths": [_TAG_PATH],
                    "start_time": "2026-05-01T06:06:00.796Z",
                    "end_time": "2026-05-01T07:06:00.796Z",
                    "max_depth": 1,
                },
            )
        assert resp.status_code == 200, resp.text

        # Response is keyed by tag_path -- not by composed elementId.
        body = resp.json()
        assert _TAG_PATH in body, (
            f"Expected response keyed by tag_path; got keys: {list(body.keys())}"
        )
        assert _COMPOSED_ELEMENT_ID not in body, (
            "Dataset prefix leaked into response keys"
        )
        assert body[_TAG_PATH]["data"][0]["value"] == 3

        # Upstream got the *composed* elementId (server-side composition).
        assert seen["url"].endswith("/i3x/objects/history")
        assert seen["body"]["elementIds"] == [_COMPOSED_ELEMENT_ID]
        assert seen["body"]["startTime"].endswith("Z")
        assert seen["body"]["maxDepth"] == 1
    finally:
        await client.aclose()


_MIXED_QUALITY_UPSTREAM = {
    _COMPOSED_ELEMENT_ID: {
        "data": [
            {"value": 10, "quality": "GOOD", "timestamp": "2026-05-01T00:00:00Z"},
            {"value": 11, "quality": "BAD", "timestamp": "2026-05-01T00:05:00Z"},
            {"value": 12, "quality": "UNCERTAIN", "timestamp": "2026-05-01T00:10:00Z"},
            {"value": 13, "quality": "GOOD", "timestamp": "2026-05-01T00:15:00Z"},
        ]
    }
}


@pytest.mark.asyncio
async def test_history_filters_non_good_quality_by_default(
    wire_timebase, make_mock_client
) -> None:
    """By default, /history drops samples whose quality != 'GOOD'.

    Filter happens AFTER the cache + rekey -- the upstream response
    has 4 samples (2 GOOD + 1 BAD + 1 UNCERTAIN); the client sees 2.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_MIXED_QUALITY_UPSTREAM)

    client = await make_mock_client("101", handler, dataset=_DATASET)
    try:
        with wire_timebase(clients={"101": client}) as tc:
            resp = tc.post(
                "/api/timebase/history?site_id=101",
                json={
                    "tag_paths": [_TAG_PATH],
                    "start_time": "2026-05-01T00:00:00Z",
                    "end_time": "2026-05-01T01:00:00Z",
                },
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()[_TAG_PATH]["data"]
        assert len(data) == 2
        assert {s["value"] for s in data} == {10, 13}
        assert all(s["quality"] == "GOOD" for s in data)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_history_include_all_qualities_passes_through(
    wire_timebase, make_mock_client
) -> None:
    """include_all_qualities=true bypasses the filter -- every sample
    comes through with its original quality preserved."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_MIXED_QUALITY_UPSTREAM)

    client = await make_mock_client("101", handler, dataset=_DATASET)
    try:
        with wire_timebase(clients={"101": client}) as tc:
            resp = tc.post(
                "/api/timebase/history?site_id=101&include_all_qualities=true",
                json={
                    "tag_paths": [_TAG_PATH],
                    "start_time": "2026-05-01T00:00:00Z",
                    "end_time": "2026-05-01T01:00:00Z",
                },
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()[_TAG_PATH]["data"]
        assert len(data) == 4
        assert {s["quality"] for s in data} == {"GOOD", "BAD", "UNCERTAIN"}
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_history_filter_does_not_corrupt_cached_payload(
    wire_timebase, make_mock_client
) -> None:
    """Regression guard: the filter must be non-mutating.

    The cache holds the raw upstream response and `_rekey_to_tag_paths`
    reuses payload references. If `_filter_quality` mutated payload['data']
    in place, the cache would be corrupted -- a subsequent
    include_all_qualities=true request would still see filtered data.
    Verify both modes work back-to-back against the same cached entry.
    """
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(200, json=_MIXED_QUALITY_UPSTREAM)

    client = await make_mock_client("101", handler, dataset=_DATASET)
    try:
        with wire_timebase(clients={"101": client}) as tc:
            # First request: default (filtered). Caches the upstream.
            r1 = tc.post(
                "/api/timebase/history?site_id=101",
                json={
                    "tag_paths": [_TAG_PATH],
                    "start_time": "2026-05-01T00:00:00Z",
                    "end_time": "2026-05-01T01:00:00Z",
                },
            )
            assert r1.status_code == 200
            assert len(r1.json()[_TAG_PATH]["data"]) == 2  # filtered

            # Second request: same window, include_all_qualities=true.
            # Should serve from cache (same upstream) but see all 4
            # samples -- only possible if the cached copy is intact.
            r2 = tc.post(
                "/api/timebase/history?site_id=101&include_all_qualities=true",
                json={
                    "tag_paths": [_TAG_PATH],
                    "start_time": "2026-05-01T00:00:00Z",
                    "end_time": "2026-05-01T01:00:00Z",
                },
            )
            assert r2.status_code == 200
            assert len(r2.json()[_TAG_PATH]["data"]) == 4  # unfiltered

            # Both requests should have hit ONE upstream fetch (cached).
            assert call_count["n"] == 1
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_history_strips_stray_slashes_from_tag_paths(
    wire_timebase, make_mock_client
) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json={})

    client = await make_mock_client("101", handler, dataset=_DATASET)
    try:
        with wire_timebase(clients={"101": client}) as tc:
            resp = tc.post(
                "/api/timebase/history?site_id=101",
                json={
                    "tag_paths": ["/" + _TAG_PATH + "/"],
                    "start_time": "2026-05-01T06:06:00Z",
                    "end_time": "2026-05-01T07:06:00Z",
                },
            )
        assert resp.status_code == 200
        # Exactly one composed elementId, no double slashes.
        assert captured["elementIds"] == [_COMPOSED_ELEMENT_ID]
        assert "//" not in captured["elementIds"][0]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_history_routes_to_correct_site(
    wire_timebase, make_mock_client
) -> None:
    """site_id=101 must hit the BCQ historian, not the ARP one."""
    bcq_hits = 0
    arp_hits = 0

    def bcq_handler(request: httpx.Request) -> httpx.Response:
        nonlocal bcq_hits
        bcq_hits += 1
        return httpx.Response(200, json=_UPSTREAM_RESPONSE)

    def arp_handler(request: httpx.Request) -> httpx.Response:
        nonlocal arp_hits
        arp_hits += 1
        return httpx.Response(200, json={})

    bcq = await make_mock_client("101", bcq_handler, dataset=_DATASET)
    arp = await make_mock_client("100", arp_handler, dataset="IAP_ARP_Controls")
    try:
        with wire_timebase(clients={"101": bcq, "100": arp}) as tc:
            resp = tc.post(
                "/api/timebase/history?site_id=101",
                json={
                    "tag_paths": [_TAG_PATH],
                    "start_time": "2026-05-01T06:06:00Z",
                    "end_time": "2026-05-01T07:06:00Z",
                },
            )
        assert resp.status_code == 200
        assert bcq_hits == 1
        assert arp_hits == 0
    finally:
        await bcq.aclose()
        await arp.aclose()


@pytest.mark.asyncio
async def test_history_unknown_site_id_returns_404(
    wire_timebase, make_mock_client
) -> None:
    client = await make_mock_client(
        "101",
        lambda r: httpx.Response(200, json=_UPSTREAM_RESPONSE),
        dataset=_DATASET,
    )
    try:
        with wire_timebase(clients={"101": client}) as tc:
            resp = tc.post(
                "/api/timebase/history?site_id=999",
                json={
                    "tag_paths": [_TAG_PATH],
                    "start_time": "2026-05-01T06:06:00Z",
                    "end_time": "2026-05-01T07:06:00Z",
                },
            )
        assert resp.status_code == 404
        assert "Unknown Timebase site_id" in resp.json()["detail"]
    finally:
        await client.aclose()


def test_history_missing_site_id_returns_422(wire_timebase) -> None:
    """site_id is a required query parameter."""
    with wire_timebase() as tc:
        resp = tc.post(
            "/api/timebase/history",
            json={
                "tag_paths": [_TAG_PATH],
                "start_time": "2026-05-01T06:06:00Z",
                "end_time": "2026-05-01T07:06:00Z",
            },
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_history_second_call_hits_cache(
    wire_timebase, make_mock_client
) -> None:
    """Identical second call within 10s should NOT re-hit upstream."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_UPSTREAM_RESPONSE)

    client = await make_mock_client("101", handler, dataset=_DATASET)
    try:
        with wire_timebase(clients={"101": client}) as tc:
            body = {
                "tag_paths": [_TAG_PATH],
                "start_time": "2026-05-01T06:06:00Z",
                "end_time": "2026-05-01T07:06:00Z",
            }
            r1 = tc.post("/api/timebase/history?site_id=101", json=body)
            r2 = tc.post("/api/timebase/history?site_id=101", json=body)
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert calls == 1
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_history_upstream_500_returns_502(
    wire_timebase, make_mock_client
) -> None:
    client = await make_mock_client(
        "101",
        lambda r: httpx.Response(500, text="upstream boom"),
        dataset=_DATASET,
    )
    try:
        with wire_timebase(clients={"101": client}) as tc:
            resp = tc.post(
                "/api/timebase/history?site_id=101",
                json={
                    "tag_paths": [_TAG_PATH],
                    "start_time": "2026-05-01T06:06:00Z",
                    "end_time": "2026-05-01T07:06:00Z",
                },
            )
        assert resp.status_code == 502
        assert "Timebase (101) returned 500" in resp.json()["detail"]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_history_timeout_returns_504(
    wire_timebase, make_mock_client
) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=req)

    client = await make_mock_client("101", handler, dataset=_DATASET)
    try:
        with wire_timebase(clients={"101": client}) as tc:
            resp = tc.post(
                "/api/timebase/history?site_id=101",
                json={
                    "tag_paths": [_TAG_PATH],
                    "start_time": "2026-05-01T06:06:00Z",
                    "end_time": "2026-05-01T07:06:00Z",
                },
            )
        assert resp.status_code == 504
        assert "timed out" in resp.json()["detail"].lower()
    finally:
        await client.aclose()


def test_history_returns_503_when_registry_not_initialized() -> None:
    """No registry on app.state -> /history returns 503.

    Mutate state post-lifespan; otherwise the real lifespan would
    rebuild the registry and the request would hit the real (or
    unreachable) historian instead of getting the 503 we want to test.
    """
    app.dependency_overrides.pop(get_timebase_client_registry, None)
    with TestClient(app) as tc:
        app.state.timebase_clients = None  # post-lifespan
        resp = tc.post(
            "/api/timebase/history?site_id=101",
            json={
                "tag_paths": [_TAG_PATH],
                "start_time": "2026-05-01T06:06:00Z",
                "end_time": "2026-05-01T07:06:00Z",
            },
        )
    assert resp.status_code == 503
    assert "registry unavailable" in resp.json()["detail"].lower()


def test_history_validates_empty_tag_paths(wire_timebase) -> None:
    """Empty tag_paths is a Pydantic min_length=1 violation: 422."""
    with wire_timebase() as tc:
        resp = tc.post(
            "/api/timebase/history?site_id=101",
            json={
                "tag_paths": [],
                "start_time": "2026-05-01T06:06:00Z",
                "end_time": "2026-05-01T07:06:00Z",
            },
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_history_rejects_window_over_cap(wire_timebase, make_mock_client) -> None:
    """Server-side window cap: > 8h window must 422 without hitting upstream."""
    upstream_called = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal upstream_called
        upstream_called += 1
        return httpx.Response(200, json=_UPSTREAM_RESPONSE)

    client = await make_mock_client("101", handler, dataset=_DATASET)
    try:
        with wire_timebase(clients={"101": client}) as tc:
            resp = tc.post(
                "/api/timebase/history?site_id=101",
                json={
                    "tag_paths": [_TAG_PATH],
                    # 13-hour window -- one hour over the 12h cap.
                    "start_time": "2026-05-01T06:00:00Z",
                    "end_time": "2026-05-01T19:00:00Z",
                },
            )
        assert resp.status_code == 422
        assert "limit" in resp.json()["detail"].lower()
        # Upstream must not have been called.
        assert upstream_called == 0
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_history_rejects_zero_or_negative_window(
    wire_timebase, make_mock_client
) -> None:
    """end_time <= start_time is a 422."""
    client = await make_mock_client(
        "101",
        lambda r: httpx.Response(200, json=_UPSTREAM_RESPONSE),
        dataset=_DATASET,
    )
    try:
        with wire_timebase(clients={"101": client}) as tc:
            resp = tc.post(
                "/api/timebase/history?site_id=101",
                json={
                    "tag_paths": [_TAG_PATH],
                    "start_time": "2026-05-01T10:00:00Z",
                    "end_time": "2026-05-01T10:00:00Z",   # zero window
                },
            )
        assert resp.status_code == 422
        assert "after start_time" in resp.json()["detail"]
    finally:
        await client.aclose()


def test_history_allows_window_inside_cap(wire_timebase) -> None:
    """A window inside the cap is not rejected by the validator."""
    # We don't need a mock client here -- if it gets past validation,
    # the actual fetch will be tested elsewhere. This just verifies
    # the boundary doesn't trip the 422.
    with wire_timebase() as tc:
        resp = tc.post(
            "/api/timebase/history?site_id=101",
            json={
                "tag_paths": [_TAG_PATH],
                "start_time": "2026-05-01T06:00:00Z",
                "end_time": "2026-05-01T14:00:00Z",  # exactly 8h
            },
        )
    # 503 because no client is configured for site 101 in this test (the
    # wire_timebase context with no `clients=` arg). What we're confirming
    # is that we got past the window-cap validation -- otherwise it'd be 422.
    assert resp.status_code != 422

