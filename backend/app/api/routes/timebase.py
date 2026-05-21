"""/api/timebase/* routes -- single history endpoint + tag catalog.

Three endpoints:

* ``POST /api/timebase/history?site_id=<id>`` -- tag history for one
  site's historian. Caller sends tag paths (without dataset prefix);
  the server resolves ``base_url`` and ``dataset`` from the YAML
  catalog, composes ``<dataset>:<tag_path>`` elementIds, calls the
  upstream Timebase i3X ``POST /i3x/objects/history``, and returns
  the response re-keyed by the caller's tag_path so the dataset
  prefix never leaks to consumers.

* ``GET  /api/timebase/catalog`` -- resolved per-site tag catalog for
  the dashboard. Full elementIds pre-computed (dashboard convenience).
  Internal historian URLs are NOT surfaced here.

* ``GET  /api/timebase/catalog/{site_id}`` -- one site's slice.

The same /history endpoint is used by the dashboard AND by any other
caller (Ignition scripts, ad-hoc tools, ETL jobs). Everyone passes
``site_id``; the YAML catalog lookup happens server-side. There is no
endpoint that accepts an arbitrary ``base_url`` -- adding a new site
means editing ``catalog.yaml`` + restart, same workflow as ``.env``.

``site_id`` is a query parameter on ``/history`` (matching the
existing ``/api/metrics`` and ``/api/production-report`` convention)
and a path parameter on ``/catalog/{site_id}`` (REST-conventional and
consistent with how the dashboard already constructs catalog links).

Per-source 503 graceful degradation:

* Catalog routes 503 when the YAML failed to load.
* /history 503 when the registry is unavailable OR when the site is
  configured but its client didn't open at startup.
* /history 404 when the requested ``site_id`` isn't configured.

Upstream errors:

* Upstream 5xx       -> 502 Bad Gateway
* Upstream 4xx       -> 502 Bad Gateway with body in ``detail``
* Timeout / connect  -> 504 Gateway Timeout
* Other httpx errors -> 502 with type name + message in ``detail``
"""

from __future__ import annotations

from typing import Annotated, Any

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request

from app.integrations.timebase.cache import TimebaseHistoryCache
from app.integrations.timebase.catalog import CatalogError, TimebaseCatalog
from app.integrations.timebase.client import TimebaseClient, TimebaseClientRegistry
from app.schemas.timebase import CatalogResponse, HistoryRequest, HistoryResponse

router = APIRouter()
log = structlog.get_logger("api.routes.timebase")


# ============================================================================
# DI providers
# ============================================================================


def get_timebase_client_registry(request: Request) -> TimebaseClientRegistry:
    """Return the lifespan-created Timebase client registry.

    503 when the registry isn't on app.state. Test contexts inject a
    fake registry via ``app.dependency_overrides``.
    """
    registry = getattr(request.app.state, "timebase_clients", None)
    if registry is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Timebase client registry unavailable: not initialized. "
                "Check uvicorn startup log."
            ),
        )
    return registry


def get_timebase_catalog(request: Request) -> TimebaseCatalog:
    """Return the lifespan-loaded Timebase catalog.

    503 when the catalog YAML failed to load.
    """
    catalog = getattr(request.app.state, "timebase_catalog", None)
    if catalog is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Timebase catalog unavailable: not loaded. Check uvicorn "
                "startup log for 'timebase.catalog_load_failed'."
            ),
        )
    return catalog


def get_timebase_history_cache(request: Request) -> TimebaseHistoryCache:
    """Return the lifespan-created cache instance.

    Distinct from the client / catalog providers because the cache is
    a pure in-memory helper and is always present once the lifespan
    runs. Defensive fallback creates a default when missing (handy in
    tests that bypass the lifespan).
    """
    cache = getattr(request.app.state, "timebase_history_cache", None)
    if cache is None:
        cache = TimebaseHistoryCache()
        request.app.state.timebase_history_cache = cache
    return cache


def _resolve_site_client(
    registry: TimebaseClientRegistry, site_id: str
) -> TimebaseClient:
    """Return the client for ``site_id`` or raise the right HTTPException.

    * 404 when site_id isn't configured at all (typo, unknown site).
    * 503 when the site is configured but its client failed to open
      at startup (network unreachable, bad URL).
    """
    client = registry.get(site_id)
    if client is None:
        if site_id in registry:
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Timebase site {site_id!r} configured but client did not "
                    "initialize. Check uvicorn startup log for "
                    "'timebase.client_create_failed'."
                ),
            )
        raise HTTPException(
            status_code=404,
            detail=(
                f"Unknown Timebase site_id: {site_id!r}. Configured sites: "
                f"{sorted(registry.site_ids())}."
            ),
        )
    return client


TimebaseClientRegistryDep = Annotated[
    TimebaseClientRegistry, Depends(get_timebase_client_registry)
]
TimebaseCatalogDep = Annotated[TimebaseCatalog, Depends(get_timebase_catalog)]
TimebaseCacheDep = Annotated[
    TimebaseHistoryCache, Depends(get_timebase_history_cache)
]


# ============================================================================
# Routes
# ============================================================================


def _rekey_to_tag_paths(
    upstream_response: dict[str, Any],
    composed_to_tag_path: dict[str, str],
) -> dict[str, Any]:
    """Rewrite top-level keys from composed elementIds back to tag_paths.

    The upstream returns ``{ "<dataset>:<tag_path>": {data: [...]}, ... }``.
    Callers send and think in terms of ``tag_path`` -- they shouldn't
    have to know about the dataset prefix to find their data. We strip
    the prefix off the keys before returning.

    Keys we don't recognize (theoretically shouldn't happen, but
    upstream-defense) are returned as-is.
    """
    rekeyed: dict[str, Any] = {}
    for composed, payload in upstream_response.items():
        rekeyed[composed_to_tag_path.get(composed, composed)] = payload
    return rekeyed


@router.post(
    "/history",
    response_model=HistoryResponse,
    summary="Tag history for one site (YAML-resolved URL + dataset)",
    description=(
        "Returns historical values for one or more tags on the requested "
        "site's historian. Caller passes `site_id` (query param) plus tag "
        "paths under the site's dataset; the server resolves the per-site "
        "`base_url` and `dataset` from the YAML catalog, composes "
        "`<dataset>:<tag_path>` elementIds, and calls the upstream "
        "Timebase i3X `POST /i3x/objects/history`. The response is "
        "re-keyed by `tag_path` so callers never see the dataset prefix. "
        "Responses are cached in-process for ~45s; the cache key "
        "normalizes `start_time` and `end_time` to a 10-second UTC "
        "boundary so consecutive polls of the same window share a single "
        "upstream round-trip. Returns 404 when `site_id` is not "
        "configured, 503 when the site's historian failed to initialize "
        "at startup."
    ),
)
async def post_history(
    payload: HistoryRequest,
    registry: TimebaseClientRegistryDep,
    cache: TimebaseCacheDep,
    site_id: Annotated[
        str,
        Query(
            description=(
                "Site identifier (e.g. '101'). Determines which "
                "historian to query. Must match a configured site in "
                "catalog.yaml."
            ),
        ),
    ],
) -> HistoryResponse:
    client = _resolve_site_client(registry, site_id)
    if not client.dataset:
        # Should be unreachable in normal operation -- catalog enforces
        # non-empty dataset at load time -- but defend against test
        # contexts that construct a client by hand without a dataset.
        raise HTTPException(
            status_code=503,
            detail=(
                f"Timebase site {site_id!r} client has no dataset configured. "
                "This means the catalog loaded but the client was constructed "
                "without one. Check uvicorn startup log."
            ),
        )

    # Compose <dataset>:<tag_path> for each input. Strip stray slashes
    # so callers don't have to worry about exact shape.
    clean_paths = [p.strip("/") for p in payload.tag_paths]
    composed_ids = [f"{client.dataset}:{path}" for path in clean_paths]
    composed_to_tag = dict(zip(composed_ids, clean_paths, strict=True))

    async def _fetch(eids, start, end, depth):
        return await client.get_history(
            element_ids=eids,
            start_time=start,
            end_time=end,
            max_depth=depth,
        )

    try:
        result, hit, _, _ = await cache.get_or_fetch(
            element_ids=composed_ids,
            start_time=payload.start_time,
            end_time=payload.end_time,
            max_depth=payload.max_depth,
            fetch=_fetch,
        )
    except httpx.HTTPStatusError as exc:
        body_excerpt = exc.response.text[:500] if exc.response is not None else ""
        upstream_status = (
            exc.response.status_code if exc.response is not None else "?"
        )
        log.error(
            "timebase.http_error",
            site_id=site_id,
            status=upstream_status,
            body=body_excerpt,
            tag_paths=clean_paths,
        )
        raise HTTPException(
            status_code=502,
            detail=(
                f"Timebase ({site_id}) returned {upstream_status}: {body_excerpt}"
                if body_excerpt
                else f"Timebase ({site_id}) returned {upstream_status}"
            ),
        ) from exc
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        log.error(
            "timebase.connect_error",
            site_id=site_id,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        raise HTTPException(
            status_code=504,
            detail=(
                f"Cannot reach Timebase site {site_id}: "
                f"{type(exc).__name__}: {exc}."
            ),
        ) from exc
    except httpx.TimeoutException as exc:
        log.error(
            "timebase.timeout", site_id=site_id, error_message=str(exc)
        )
        raise HTTPException(
            status_code=504,
            detail=f"Timebase site {site_id} request timed out: {exc}",
        ) from exc
    except httpx.HTTPError as exc:
        log.error(
            "timebase.http_error_generic",
            site_id=site_id,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        raise HTTPException(
            status_code=502,
            detail=(
                f"Timebase site {site_id} call failed: "
                f"{type(exc).__name__}: {exc}"
            ),
        ) from exc

    log.debug(
        "timebase.history.served",
        site_id=site_id,
        cache_hit=hit,
        tag_path_count=len(clean_paths),
    )
    rekeyed = _rekey_to_tag_paths(result, composed_to_tag)
    return HistoryResponse.model_validate(rekeyed)


@router.get(
    "/catalog",
    response_model=CatalogResponse,
    summary="Resolved Timebase tag catalog for all configured sites",
    description=(
        "Returns the per-site catalog of available assets and metrics "
        "with their fully-resolved i3X elementIds pre-computed. The "
        "frontend's tag picker hangs off this; client code never has "
        "to concatenate path segments. Internal historian URLs are "
        "intentionally NOT included. Catalog is loaded from a YAML "
        "file at startup; restart the API to pick up edits."
    ),
)
async def get_catalog(catalog: TimebaseCatalogDep) -> CatalogResponse:
    return catalog.build_response()


@router.get(
    "/catalog/{site_id}",
    response_model=CatalogResponse,
    summary="Resolved Timebase tag catalog for one site",
    description=(
        "Same shape as /catalog but filtered to a single site. Returns "
        "404 when the site is not configured for Timebase."
    ),
)
async def get_catalog_for_site(
    catalog: TimebaseCatalogDep,
    site_id: Annotated[str, Path(description="Site identifier (e.g. '101').")],
) -> CatalogResponse:
    try:
        return catalog.build_response(site_id=site_id)
    except CatalogError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
