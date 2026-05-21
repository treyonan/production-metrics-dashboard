"""Unit tests for TimebaseClient.

Uses ``httpx.MockTransport`` so tests run without network. Covers
request shape, base-URL handling, response parsing, error
propagation, and the ISO-8601 helper.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone

import httpx
import pytest

from app.integrations.timebase.client import TimebaseClient, _to_iso

# ============================================================================
# _to_iso helper
# ============================================================================


def test_to_iso_utc() -> None:
    dt = datetime(2026, 5, 1, 6, 6, 0, 796000, tzinfo=UTC)
    # ISO with millis + Z. The trailing Z is what i3X examples use.
    assert _to_iso(dt) == "2026-05-01T06:06:00.796000Z"


def test_to_iso_converts_to_utc() -> None:
    # Non-UTC input is converted to UTC.
    east = timezone(timedelta(hours=2))
    dt = datetime(2026, 5, 1, 8, 6, 0, 0, tzinfo=east)
    out = _to_iso(dt)
    assert out.endswith("Z")
    assert out.startswith("2026-05-01T06:06:00")  # 08:06 +0200 -> 06:06 UTC


def test_to_iso_naive_datetime_is_treated_as_utc() -> None:
    dt = datetime(2026, 5, 1, 6, 6, 0)
    assert _to_iso(dt).endswith("Z")


# ============================================================================
# get_history
# ============================================================================


@pytest.mark.asyncio
async def test_get_history_posts_i3x_shape_to_history_endpoint() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "IAP_BCQ_Controls:Big_Canyon/Secondary/Conveyor/C1/Process_Data/Belt_Scale/TPH": {
                    "data": [
                        {
                            "value": 42,
                            "quality": "GOOD",
                            "timestamp": "2026-05-01T13:30:00.000Z",
                        }
                    ]
                }
            },
        )

    transport = httpx.MockTransport(handler)
    client = TimebaseClient(
        site_id="test", base_url="http://timebase.example:8080", transport=transport
    )
    await client.aopen()
    try:
        result = await client.get_history(
            element_ids=[
                "IAP_BCQ_Controls:Big_Canyon/Secondary/Conveyor/C1"
                "/Process_Data/Belt_Scale/TPH"
            ],
            start_time=datetime(2026, 5, 1, 6, 6, 0, tzinfo=UTC),
            end_time=datetime(2026, 5, 2, 7, 6, 0, tzinfo=UTC),
            max_depth=1,
        )
    finally:
        await client.aclose()

    # Endpoint, method, body shape all match i3X.
    assert captured["url"] == "http://timebase.example:8080/i3x/objects/history"
    assert captured["method"] == "POST"
    body = captured["body"]
    assert body["elementIds"] == [
        "IAP_BCQ_Controls:Big_Canyon/Secondary/Conveyor/C1/Process_Data/Belt_Scale/TPH"
    ]
    assert body["startTime"].endswith("Z")
    assert body["endTime"].endswith("Z")
    assert body["maxDepth"] == 1

    # Response is parsed and returned unmodified.
    assert isinstance(result, dict)
    key = next(iter(result))
    assert result[key]["data"][0]["value"] == 42


@pytest.mark.asyncio
async def test_get_history_strips_trailing_slash_on_base_url() -> None:
    captured_url: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_url.append(str(request.url))
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    # Trailing slash on base URL should be normalized; we don't want
    # `//i3x/objects/history`.
    client = TimebaseClient(
        site_id="test", base_url="http://timebase.example:8080/", transport=transport
    )
    await client.aopen()
    try:
        await client.get_history(
            element_ids=["x:y/z"],
            start_time=datetime(2026, 1, 1, tzinfo=UTC),
            end_time=datetime(2026, 1, 2, tzinfo=UTC),
        )
    finally:
        await client.aclose()
    assert captured_url[0] == "http://timebase.example:8080/i3x/objects/history"


@pytest.mark.asyncio
async def test_get_history_raises_on_500() -> None:
    transport = httpx.MockTransport(
        lambda req: httpx.Response(500, text="boom")
    )
    client = TimebaseClient(site_id="test", base_url="http://x", transport=transport)
    await client.aopen()
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await client.get_history(
                element_ids=["x:y/z"],
                start_time=datetime(2026, 1, 1, tzinfo=UTC),
                end_time=datetime(2026, 1, 2, tzinfo=UTC),
            )
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_get_history_raises_on_400() -> None:
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            400,
            json={
                "type": "string",
                "title": "Bad Request",
                "detail": "elementIds must be Tag ids",
            },
        )
    )
    client = TimebaseClient(site_id="test", base_url="http://x", transport=transport)
    await client.aopen()
    try:
        with pytest.raises(httpx.HTTPStatusError) as info:
            await client.get_history(
                element_ids=["x"],
                start_time=datetime(2026, 1, 1, tzinfo=UTC),
                end_time=datetime(2026, 1, 2, tzinfo=UTC),
            )
        assert info.value.response.status_code == 400
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_get_history_raises_on_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    transport = httpx.MockTransport(handler)
    client = TimebaseClient(site_id="test", base_url="http://x", transport=transport)
    await client.aopen()
    try:
        with pytest.raises(httpx.TimeoutException):
            await client.get_history(
                element_ids=["x:y/z"],
                start_time=datetime(2026, 1, 1, tzinfo=UTC),
                end_time=datetime(2026, 1, 2, tzinfo=UTC),
            )
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_get_history_raises_on_non_object_response() -> None:
    # Defense in depth: i3X spec says the response is a JSON object.
    # If a misconfigured proxy returns a list, the client surfaces it
    # as an HTTPError rather than silently corrupting data downstream.
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json=["unexpected", "list"])
    )
    client = TimebaseClient(site_id="test", base_url="http://x", transport=transport)
    await client.aopen()
    try:
        with pytest.raises(httpx.HTTPError, match="Unexpected i3X response"):
            await client.get_history(
                element_ids=["x:y/z"],
                start_time=datetime(2026, 1, 1, tzinfo=UTC),
                end_time=datetime(2026, 1, 2, tzinfo=UTC),
            )
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_get_history_returns_empty_on_empty_body() -> None:
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, content=b"")
    )
    client = TimebaseClient(site_id="test", base_url="http://x", transport=transport)
    await client.aopen()
    try:
        out = await client.get_history(
            element_ids=["x:y/z"],
            start_time=datetime(2026, 1, 1, tzinfo=UTC),
            end_time=datetime(2026, 1, 2, tzinfo=UTC),
        )
        assert out == {}
    finally:
        await client.aclose()


# ============================================================================
# get_namespaces (health ping)
# ============================================================================


@pytest.mark.asyncio
async def test_get_namespaces_returns_list() -> None:
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            200,
            json=[
                {
                    "uri": "https://timebase.com/historian",
                    "displayName": "Timebase Historian",
                }
            ],
        )
    )
    client = TimebaseClient(site_id="test", base_url="http://x", transport=transport)
    await client.aopen()
    try:
        ns = await client.get_namespaces()
        assert isinstance(ns, list)
        assert ns[0]["uri"] == "https://timebase.com/historian"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_get_namespaces_raises_on_non_list_response() -> None:
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json={"oops": True})
    )
    client = TimebaseClient(site_id="test", base_url="http://x", transport=transport)
    await client.aopen()
    try:
        with pytest.raises(httpx.HTTPError, match="namespaces"):
            await client.get_namespaces()
    finally:
        await client.aclose()


# ============================================================================
# Lifecycle
# ============================================================================


@pytest.mark.asyncio
async def test_calls_without_aopen_raise_runtimeerror() -> None:
    """Helpful error when someone forgets the lifespan wiring."""
    client = TimebaseClient(site_id="test", base_url="http://x")
    with pytest.raises(RuntimeError, match="aopen"):
        await client.get_history(
            element_ids=["x:y/z"],
            start_time=datetime(2026, 1, 1, tzinfo=UTC),
            end_time=datetime(2026, 1, 2, tzinfo=UTC),
        )


@pytest.mark.asyncio
async def test_aclose_is_idempotent() -> None:
    client = TimebaseClient(
        site_id="test",
        base_url="http://x",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
    )
    await client.aopen()
    await client.aclose()
    # Second close is a no-op, not an error.
    await client.aclose()


@pytest.mark.asyncio
async def test_client_name_includes_site_id() -> None:
    """``.name`` is used in /api/health output; carries site_id."""
    client = TimebaseClient(
        site_id="101",
        base_url="http://x",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
    )
    assert client.name == "timebase:i3x:101"
    assert client.site_id == "101"
    await client.aopen()
    await client.aclose()


@pytest.mark.asyncio
async def test_client_registry_holds_per_site_clients() -> None:
    """Registry stores clients by site_id and can close them all."""
    from app.integrations.timebase.client import TimebaseClientRegistry

    c1 = TimebaseClient(
        site_id="101",
        base_url="http://x",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
    )
    c2 = TimebaseClient(
        site_id="100",
        base_url="http://y",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
    )
    await c1.aopen()
    await c2.aopen()
    registry = TimebaseClientRegistry()
    registry.add(c1)
    registry.add(c2)
    assert len(registry) == 2
    assert "101" in registry
    assert "100" in registry
    assert registry.get("101") is c1
    assert registry.get("999") is None
    assert sorted(registry.site_ids()) == ["100", "101"]
    await registry.aclose_all()
    assert len(registry) == 0


def test_client_exposes_dataset() -> None:
    """``.dataset`` is used by /history route to compose elementIds."""
    client = TimebaseClient(
        site_id="101", base_url="http://x", dataset="IAP_BCQ_Controls"
    )
    assert client.dataset == "IAP_BCQ_Controls"
    # Default is empty string when not provided (test contexts).
    bare = TimebaseClient(site_id="x", base_url="http://x")
    assert bare.dataset == ""

