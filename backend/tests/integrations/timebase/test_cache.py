"""Unit tests for TimebaseHistoryCache + normalize_timestamp."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from app.integrations.timebase.cache import (
    NORMALIZATION_SECONDS,
    TimebaseHistoryCache,
    make_key,
    normalize_timestamp,
)

# ============================================================================
# normalize_timestamp
# ============================================================================


def test_normalize_floors_to_10s() -> None:
    dt = datetime(2026, 5, 1, 6, 6, 7, 555000, tzinfo=UTC)
    assert normalize_timestamp(dt) == datetime(2026, 5, 1, 6, 6, 0, tzinfo=UTC)


def test_normalize_keeps_aligned_timestamp() -> None:
    dt = datetime(2026, 5, 1, 6, 6, 20, 0, tzinfo=UTC)
    # Already on a 10s boundary -- no change.
    assert normalize_timestamp(dt) == dt


def test_normalize_drops_microseconds() -> None:
    dt = datetime(2026, 5, 1, 6, 6, 30, 999999, tzinfo=UTC)
    assert normalize_timestamp(dt) == datetime(2026, 5, 1, 6, 6, 30, tzinfo=UTC)


def test_normalize_converts_to_utc() -> None:
    east = timezone(timedelta(hours=2))
    dt = datetime(2026, 5, 1, 8, 6, 7, tzinfo=east)
    # 08:06:07 +0200 = 06:06:07 UTC; floored to 06:06:00 UTC.
    expected = datetime(2026, 5, 1, 6, 6, 0, tzinfo=UTC)
    assert normalize_timestamp(dt) == expected


def test_normalize_naive_datetime_treated_as_utc() -> None:
    dt = datetime(2026, 5, 1, 6, 6, 7)
    out = normalize_timestamp(dt)
    assert out.tzinfo is UTC
    assert out.second == 0


def test_normalization_window_constant() -> None:
    assert NORMALIZATION_SECONDS == 10


# ============================================================================
# make_key: order-insensitivity
# ============================================================================


def test_make_key_sorts_element_ids() -> None:
    a = make_key(
        element_ids=["x:1/a", "x:2/b"],
        start_time=datetime(2026, 5, 1, tzinfo=UTC),
        end_time=datetime(2026, 5, 2, tzinfo=UTC),
        max_depth=1,
    )
    b = make_key(
        element_ids=["x:2/b", "x:1/a"],
        start_time=datetime(2026, 5, 1, tzinfo=UTC),
        end_time=datetime(2026, 5, 2, tzinfo=UTC),
        max_depth=1,
    )
    assert a == b


def test_make_key_distinguishes_max_depth() -> None:
    base = {
        "element_ids": ["x:y/z"],
        "start_time": datetime(2026, 5, 1, tzinfo=UTC),
        "end_time": datetime(2026, 5, 2, tzinfo=UTC),
    }
    assert make_key(**base, max_depth=1) != make_key(**base, max_depth=0)


# ============================================================================
# Cache: hit / miss / TTL / LRU
# ============================================================================


def test_get_miss_returns_none() -> None:
    c = TimebaseHistoryCache()
    key = make_key(
        element_ids=["x:y/z"],
        start_time=datetime(2026, 5, 1, tzinfo=UTC),
        end_time=datetime(2026, 5, 2, tzinfo=UTC),
        max_depth=1,
    )
    assert c.get(key) is None


def test_put_then_get_hits() -> None:
    c = TimebaseHistoryCache()
    key = make_key(
        element_ids=["x:y/z"],
        start_time=datetime(2026, 5, 1, tzinfo=UTC),
        end_time=datetime(2026, 5, 2, tzinfo=UTC),
        max_depth=1,
    )
    payload = {
        "x:y/z": {
            "data": [
                {
                    "value": 1,
                    "quality": "GOOD",
                    "timestamp": "2026-05-01T00:00:00Z",
                }
            ]
        }
    }
    c.put(key, payload)
    assert c.get(key) == payload


def test_ttl_eviction_on_read(monkeypatch: pytest.MonkeyPatch) -> None:
    c = TimebaseHistoryCache(ttl_seconds=1.0)
    key = make_key(
        element_ids=["x"],
        start_time=datetime(2026, 5, 1, tzinfo=UTC),
        end_time=datetime(2026, 5, 2, tzinfo=UTC),
        max_depth=1,
    )
    fake_now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: fake_now[0])
    c.put(key, {"hit": True})
    assert c.get(key) == {"hit": True}
    fake_now[0] += 2.0  # well past TTL
    assert c.get(key) is None
    # Evicted on the previous read.
    assert len(c) == 0


def test_lru_eviction_at_capacity() -> None:
    c = TimebaseHistoryCache(max_entries=2)

    def k(name: str) -> Any:
        return make_key(
            element_ids=[name],
            start_time=datetime(2026, 5, 1, tzinfo=UTC),
            end_time=datetime(2026, 5, 2, tzinfo=UTC),
            max_depth=1,
        )

    c.put(k("a"), {"a": 1})
    c.put(k("b"), {"b": 1})
    # Touch 'a' so 'b' becomes the LRU candidate.
    assert c.get(k("a")) == {"a": 1}
    c.put(k("c"), {"c": 1})
    assert c.get(k("b")) is None  # 'b' was evicted
    assert c.get(k("a")) == {"a": 1}
    assert c.get(k("c")) == {"c": 1}


def test_put_existing_key_refreshes_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    c = TimebaseHistoryCache(ttl_seconds=5.0)
    key = make_key(
        element_ids=["x"],
        start_time=datetime(2026, 5, 1, tzinfo=UTC),
        end_time=datetime(2026, 5, 2, tzinfo=UTC),
        max_depth=1,
    )
    fake = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: fake[0])
    c.put(key, {"v": 1})
    fake[0] += 4.0
    # Re-put before TTL: expires_at should slide forward.
    c.put(key, {"v": 2})
    fake[0] += 4.0
    # Original would have expired at 1005; new puts at 1004 means
    # expiry at 1009. Now at 1008 -- still valid.
    assert c.get(key) == {"v": 2}


def test_invalid_ttl_rejected() -> None:
    with pytest.raises(ValueError):
        TimebaseHistoryCache(ttl_seconds=0)


def test_invalid_max_entries_rejected() -> None:
    with pytest.raises(ValueError):
        TimebaseHistoryCache(max_entries=0)


def test_clear_drops_entries() -> None:
    c = TimebaseHistoryCache()
    key = make_key(
        element_ids=["x"],
        start_time=datetime(2026, 5, 1, tzinfo=UTC),
        end_time=datetime(2026, 5, 2, tzinfo=UTC),
        max_depth=1,
    )
    c.put(key, {"v": 1})
    c.clear()
    assert len(c) == 0


# ============================================================================
# get_or_fetch: end-to-end behavior
# ============================================================================


@pytest.mark.asyncio
async def test_get_or_fetch_calls_fetch_on_miss() -> None:
    c = TimebaseHistoryCache()
    fetch_calls: list[tuple[list[str], datetime, datetime, int]] = []

    async def fake_fetch(eids, s, e, d):
        fetch_calls.append((eids, s, e, d))
        return {"fetched": True}

    val, hit, ns, ne = await c.get_or_fetch(
        element_ids=["x:y/z"],
        start_time=datetime(2026, 5, 1, 6, 6, 7, 500000, tzinfo=UTC),
        end_time=datetime(2026, 5, 1, 7, 6, 7, 500000, tzinfo=UTC),
        max_depth=1,
        fetch=fake_fetch,
    )
    assert val == {"fetched": True}
    assert hit is False
    assert ns == datetime(2026, 5, 1, 6, 6, 0, tzinfo=UTC)
    assert ne == datetime(2026, 5, 1, 7, 6, 0, tzinfo=UTC)
    assert len(fetch_calls) == 1
    # Fetch saw the normalized timestamps, not the raw ones.
    _, fetched_start, fetched_end, _ = fetch_calls[0]
    assert fetched_start == ns
    assert fetched_end == ne


@pytest.mark.asyncio
async def test_get_or_fetch_uses_cache_on_second_call() -> None:
    c = TimebaseHistoryCache()
    calls = 0

    async def fake_fetch(eids, s, e, d):
        nonlocal calls
        calls += 1
        return {"call": calls}

    args = {
        "element_ids": ["x:y/z"],
        "start_time": datetime(2026, 5, 1, 6, 6, 7, tzinfo=UTC),
        "end_time": datetime(2026, 5, 1, 7, 6, 7, tzinfo=UTC),
        "max_depth": 1,
    }
    v1, h1, *_ = await c.get_or_fetch(fetch=fake_fetch, **args)
    v2, h2, *_ = await c.get_or_fetch(fetch=fake_fetch, **args)
    assert h1 is False and v1 == {"call": 1}
    assert h2 is True and v2 == {"call": 1}
    assert calls == 1


@pytest.mark.asyncio
async def test_get_or_fetch_hits_when_only_microseconds_differ() -> None:
    """Two polls within the same 10s window share a cache slot."""
    c = TimebaseHistoryCache()
    calls = 0

    async def fake_fetch(eids, s, e, d):
        nonlocal calls
        calls += 1
        return {"call": calls}

    poll_a = {
        "element_ids": ["x:y/z"],
        "start_time": datetime(2026, 5, 1, 6, 6, 1, 0, tzinfo=UTC),
        "end_time": datetime(2026, 5, 1, 6, 6, 7, 999999, tzinfo=UTC),
        "max_depth": 1,
    }
    poll_b = {
        "element_ids": ["x:y/z"],
        "start_time": datetime(2026, 5, 1, 6, 6, 4, 500000, tzinfo=UTC),
        "end_time": datetime(2026, 5, 1, 6, 6, 9, 0, tzinfo=UTC),
        "max_depth": 1,
    }
    await c.get_or_fetch(fetch=fake_fetch, **poll_a)
    _, hit, *_ = await c.get_or_fetch(fetch=fake_fetch, **poll_b)
    # Both poll_a and poll_b normalize to (06:06:00, 06:06:00) -- same key.
    assert hit is True
    assert calls == 1


@pytest.mark.asyncio
async def test_get_or_fetch_misses_when_windows_in_different_buckets() -> None:
    """A request that crosses to the next 10s window is a cache miss."""
    c = TimebaseHistoryCache()
    calls = 0

    async def fake_fetch(eids, s, e, d):
        nonlocal calls
        calls += 1
        return {"call": calls}

    poll_a = {
        "element_ids": ["x:y/z"],
        "start_time": datetime(2026, 5, 1, 6, 6, 1, tzinfo=UTC),
        "end_time": datetime(2026, 5, 1, 6, 6, 7, tzinfo=UTC),
        "max_depth": 1,
    }
    poll_b = {
        "element_ids": ["x:y/z"],
        "start_time": datetime(2026, 5, 1, 6, 6, 11, tzinfo=UTC),
        "end_time": datetime(2026, 5, 1, 6, 6, 17, tzinfo=UTC),
        "max_depth": 1,
    }
    await c.get_or_fetch(fetch=fake_fetch, **poll_a)
    _, hit, *_ = await c.get_or_fetch(fetch=fake_fetch, **poll_b)
    assert hit is False
    assert calls == 2
