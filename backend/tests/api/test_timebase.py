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
                    "end_time": "2026-05-02T07:06:00.796Z",
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
