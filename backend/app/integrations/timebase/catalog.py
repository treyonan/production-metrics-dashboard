"""Timebase i3X tag catalog -- YAML loader + resolver (schema v2).

The catalog lives in ``catalog.yaml`` next to this module. Two layers:

* **sites**: per-site config -- ``base_url``, ``dataset``, and a
  ``departments`` map. **Each department now carries its own assets
  list per class**, so the catalog can model conveyors that live in
  Secondary at BCQ but in Primary at another site without lying about
  what's where.

* **asset_classes**: shared metric-definition registry per class
  (``Conveyor`` -> which metrics exist + their tag suffixes). Identical
  across every site by SCADA-tree convention.

Resolution::

    element_id = f"{dataset}:{dept.prefix}/{asset_class}/{asset}/{metric.suffix}"

For example, ``(site_id='101', department='Secondary',
asset_class='Conveyor', asset='C1', metric_key='belt_scale_tph')``
resolves to::

    IAP_BCQ_Controls:Big_Canyon/Secondary/Conveyor/C1/Process_Data/Belt_Scale/TPH

Site IDs are strings throughout for consistency with the rest of the
codebase (Flow / SQL / config.site_names all treat ``site_id`` as a
string identifier even when it looks numeric).

The loaded catalog is immutable at runtime. To pick up edits, restart
the API (same posture as ``.env``). The lifespan loads once and stores
the snapshot on ``app.state.timebase_catalog``.

This module deliberately knows nothing about HTTP -- ``client.py`` is
the i3X transport. ``base_url`` is part of the loaded ``SiteDef`` so
the lifespan can build one client per site, but is **not** surfaced
in ``CatalogResponse`` -- internal historian IPs should not leak
through the public API.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.schemas.timebase import (
    CatalogAsset,
    CatalogAssetClass,
    CatalogDepartment,
    CatalogMetric,
    CatalogResponse,
    CatalogSite,
)

# Catalog file paths. The real catalog (containing per-site historian URLs)
# is gitignored; the committed example file ships the structure with
# placeholder URLs for tests + CI. Production deployments must provide
# catalog.yaml; otherwise we fall back to the example file (every
# historian URL will then be unreachable and /history will return 504).
_CATALOG_REAL_PATH = Path(__file__).resolve().parent / "catalog.yaml"
_CATALOG_EXAMPLE_PATH = Path(__file__).resolve().parent / "catalog.example.yaml"
_DEFAULT_CATALOG_PATH = _CATALOG_REAL_PATH  # exported for tests


class CatalogError(Exception):
    """Raised on malformed catalog YAML or missing required fields."""


@dataclass(frozen=True)
class MetricDef:
    """A metric's suffix + display info, shared across all sites."""

    metric_key: str
    display_name: str
    unit: str
    suffix: str  # tag path fragment under the asset folder


@dataclass(frozen=True)
class AssetClassDef:
    """An asset class (e.g. 'Conveyor'): the metric registry for the class.

    Schema v2: no longer holds an `assets` list. Asset placement is
    per-site, in ``DepartmentDef.assets[asset_class]``.
    """

    asset_class: str
    metrics: tuple[MetricDef, ...]


@dataclass(frozen=True)
class DepartmentDef:
    """One department within a site: prefix path + per-class asset lists.

    `assets` is keyed by asset_class name. A department that doesn't
    physically contain a class simply omits the key. Example::

        DepartmentDef(
            name='Secondary',
            prefix='Big_Canyon/Secondary',
            assets={'Conveyor': ('C1','C2','C3','C4','C5','C6','C7','C8')},
        )
    """

    name: str
    prefix: str
    assets: dict[str, tuple[str, ...]]  # asset_class -> assets in this dept


@dataclass(frozen=True)
class SiteDef:
    """One site's catalog: dataset, code, display name, base_url, departments."""

    site_id: str
    code: str
    display_name: str
    dataset: str
    base_url: str  # NOT surfaced in CatalogSite response
    departments: dict[str, DepartmentDef]  # name -> DepartmentDef


@dataclass(frozen=True)
class TimebaseCatalog:
    """The whole catalog, post-parse and ready to resolve elementIds.

    Immutable. ``resolve_element_id`` is pure. ``build_response`` walks
    the structure and returns the Pydantic ``CatalogResponse`` for the
    catalog endpoint.
    """

    sites: dict[str, SiteDef]
    asset_classes: dict[str, AssetClassDef]

    def resolve_element_id(
        self,
        *,
        site_id: str,
        department: str,
        asset_class: str,
        asset: str,
        metric_key: str,
    ) -> str:
        """Resolve a single (site, dept, asset, metric) tuple to an elementId.

        Raises ``CatalogError`` if any tuple component isn't configured.
        Asset is validated against the **department's** asset list for
        the class, not a global per-class list -- so e.g. C1 at BCQ
        (Secondary) and C1 at ARP (Primary) are distinct and each only
        resolves under their actual home department.
        """
        site = self.sites.get(site_id)
        if site is None:
            raise CatalogError(f"Unknown site_id: {site_id!r}")
        dept = site.departments.get(department)
        if dept is None:
            raise CatalogError(
                f"Unknown department {department!r} for site_id {site_id}"
            )
        class_def = self.asset_classes.get(asset_class)
        if class_def is None:
            raise CatalogError(f"Unknown asset_class: {asset_class!r}")
        dept_assets = dept.assets.get(asset_class)
        if dept_assets is None:
            raise CatalogError(
                f"asset_class {asset_class!r} not configured in "
                f"site_id {site_id} department {department!r}"
            )
        if asset not in dept_assets:
            raise CatalogError(
                f"Unknown asset {asset!r} in class {asset_class!r} "
                f"at site_id {site_id} department {department!r}"
            )
        metric = next(
            (m for m in class_def.metrics if m.metric_key == metric_key), None
        )
        if metric is None:
            raise CatalogError(
                f"Unknown metric_key {metric_key!r} on class {asset_class!r}"
            )
        return f"{site.dataset}:{dept.prefix}/{asset_class}/{asset}/{metric.suffix}"

    def build_response(self, *, site_id: str | None = None) -> CatalogResponse:
        """Build the Pydantic catalog response, optionally filtered to one site.

        Walks every site, every department, every asset_class **declared
        in that department** (not all asset_classes globally), every
        asset in that department's list, and every metric defined for
        the class. Pre-resolves the full elementId so the frontend
        doesn't need to do path concatenation client-side. Unknown
        ``site_id`` raises ``CatalogError`` -- routes translate that to 404.
        """
        if site_id is not None and site_id not in self.sites:
            raise CatalogError(f"Unknown site_id: {site_id!r}")
        site_ids = [site_id] if site_id is not None else sorted(self.sites.keys())
        return CatalogResponse(sites=[self._build_site(sid) for sid in site_ids])

    def _build_site(self, site_id: str) -> CatalogSite:
        site = self.sites[site_id]
        return CatalogSite(
            site_id=site.site_id,
            code=site.code,
            display_name=site.display_name,
            dataset=site.dataset,
            departments=[
                self._build_department(site, dept)
                for dept in site.departments.values()
            ],
        )

    def _build_department(
        self, site: SiteDef, dept: DepartmentDef
    ) -> CatalogDepartment:
        # Only emit asset_classes that the department actually owns
        # (i.e. that appear in dept.assets), not every class in the
        # global registry. Order: as declared in dept.assets.
        return CatalogDepartment(
            name=dept.name,
            asset_classes=[
                self._build_asset_class(site, dept, class_name)
                for class_name in dept.assets
                if class_name in self.asset_classes
            ],
        )

    def _build_asset_class(
        self, site: SiteDef, dept: DepartmentDef, class_name: str
    ) -> CatalogAssetClass:
        class_def = self.asset_classes[class_name]
        return CatalogAssetClass(
            asset_class=class_name,
            assets=[
                CatalogAsset(
                    asset=asset,
                    metrics=[
                        CatalogMetric(
                            metric_key=m.metric_key,
                            display_name=m.display_name,
                            unit=m.unit,
                            element_id=self.resolve_element_id(
                                site_id=site.site_id,
                                department=dept.name,
                                asset_class=class_name,
                                asset=asset,
                                metric_key=m.metric_key,
                            ),
                        )
                        for m in class_def.metrics
                    ],
                )
                for asset in dept.assets[class_name]
            ],
        )


# ============================================================================
# Loading
# ============================================================================


def load_catalog(path: Path | None = None) -> TimebaseCatalog:
    """Load and validate the catalog YAML.

    When ``path`` is None, prefers ``catalog.yaml`` (gitignored, real
    URLs); falls back to ``catalog.example.yaml`` (committed,
    placeholder URLs) so tests + fresh checkouts work without manual
    setup. In production, ``catalog.yaml`` MUST exist for routes to
    reach real historians.

    Raises ``CatalogError`` on missing file, malformed YAML, or
    required-field violations. The lifespan in ``main.py`` catches
    this and logs it, leaving ``app.state.timebase_catalog = None``.
    """
    if path is not None:
        target = path
    elif _CATALOG_REAL_PATH.is_file():
        target = _CATALOG_REAL_PATH
    elif _CATALOG_EXAMPLE_PATH.is_file():
        target = _CATALOG_EXAMPLE_PATH
    else:
        raise CatalogError(
            f"No catalog file found. Expected one of: "
            f"{_CATALOG_REAL_PATH} (preferred, gitignored), "
            f"{_CATALOG_EXAMPLE_PATH} (committed example)."
        )
    try:
        raw = target.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise CatalogError(f"Catalog file not found: {target}") from exc
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise CatalogError(f"Catalog YAML parse error in {target}: {exc}") from exc
    if not isinstance(data, dict):
        raise CatalogError(
            f"Catalog YAML must be a mapping at the top level (got {type(data).__name__})"
        )
    return _build_catalog(data)


def _build_catalog(data: dict[str, Any]) -> TimebaseCatalog:
    sites_raw = data.get("sites") or {}
    asset_classes_raw = data.get("asset_classes") or {}
    if not isinstance(sites_raw, dict):
        raise CatalogError("`sites:` must be a mapping of site_id -> site config")
    if not isinstance(asset_classes_raw, dict):
        raise CatalogError("`asset_classes:` must be a mapping")
    sites: dict[str, SiteDef] = {}
    for site_id_raw, site_data in sites_raw.items():
        site = _build_site_def(site_id_raw, site_data)
        sites[site.site_id] = site
    asset_classes: dict[str, AssetClassDef] = {}
    for class_name, class_data in asset_classes_raw.items():
        ac = _build_asset_class_def(class_name, class_data)
        asset_classes[ac.asset_class] = ac
    # Cross-validate: every (site, dept) asset_class key must be defined
    # in the global asset_classes registry. Catch typos at load time
    # rather than 404 at request time.
    for site in sites.values():
        for dept in site.departments.values():
            for class_name in dept.assets:
                if class_name not in asset_classes:
                    raise CatalogError(
                        f"sites.{site.site_id}.departments.{dept.name}.assets: "
                        f"unknown asset_class {class_name!r} (not in "
                        f"asset_classes registry: {sorted(asset_classes)})"
                    )
    return TimebaseCatalog(sites=sites, asset_classes=asset_classes)


def _build_site_def(site_id_raw: Any, site_data: Any) -> SiteDef:
    # Site IDs are strings throughout. YAML keys that look numeric
    # (101) parse as int unless quoted; coerce to str.
    site_id = str(site_id_raw) if site_id_raw is not None else ""
    if not site_id:
        raise CatalogError(f"sites: key {site_id_raw!r} must be a non-empty site_id")
    if not isinstance(site_data, dict):
        raise CatalogError(f"sites.{site_id}: must be a mapping")
    code = site_data.get("code")
    display_name = site_data.get("display_name")
    dataset = site_data.get("dataset")
    base_url = site_data.get("base_url")
    departments_raw = site_data.get("departments") or {}
    if not isinstance(code, str) or not code:
        raise CatalogError(f"sites.{site_id}.code: required non-empty string")
    if not isinstance(display_name, str) or not display_name:
        raise CatalogError(
            f"sites.{site_id}.display_name: required non-empty string"
        )
    if not isinstance(dataset, str) or not dataset:
        raise CatalogError(f"sites.{site_id}.dataset: required non-empty string")
    if not isinstance(base_url, str) or not base_url:
        raise CatalogError(
            f"sites.{site_id}.base_url: required non-empty string"
        )
    if not isinstance(departments_raw, dict) or not departments_raw:
        raise CatalogError(
            f"sites.{site_id}.departments: required non-empty mapping"
        )
    departments: dict[str, DepartmentDef] = {}
    for dept_name, dept_body in departments_raw.items():
        departments[dept_name] = _build_department_def(site_id, dept_name, dept_body)
    return SiteDef(
        site_id=site_id,
        code=code,
        display_name=display_name,
        dataset=dataset,
        base_url=base_url.rstrip("/"),
        departments=departments,
    )


def _build_department_def(
    site_id: str, dept_name: Any, dept_body: Any
) -> DepartmentDef:
    if not isinstance(dept_name, str) or not dept_name:
        raise CatalogError(
            f"sites.{site_id}.departments: keys must be non-empty strings"
        )
    if not isinstance(dept_body, dict):
        raise CatalogError(
            f"sites.{site_id}.departments.{dept_name}: must be a mapping "
            "with `prefix` and `assets` keys"
        )
    prefix = dept_body.get("prefix")
    assets_raw = dept_body.get("assets") or {}
    if not isinstance(prefix, str) or not prefix:
        raise CatalogError(
            f"sites.{site_id}.departments.{dept_name}.prefix: required non-empty string"
        )
    if not isinstance(assets_raw, dict) or not assets_raw:
        raise CatalogError(
            f"sites.{site_id}.departments.{dept_name}.assets: required non-empty "
            "mapping of asset_class -> [asset_id, ...]"
        )
    assets: dict[str, tuple[str, ...]] = {}
    for class_name, asset_list in assets_raw.items():
        if not isinstance(class_name, str) or not class_name:
            raise CatalogError(
                f"sites.{site_id}.departments.{dept_name}.assets: "
                "keys must be non-empty asset_class names"
            )
        if not isinstance(asset_list, list) or not asset_list:
            raise CatalogError(
                f"sites.{site_id}.departments.{dept_name}.assets.{class_name}: "
                "must be a non-empty list of asset ids"
            )
        for a in asset_list:
            if not isinstance(a, str) or not a:
                raise CatalogError(
                    f"sites.{site_id}.departments.{dept_name}.assets.{class_name}: "
                    "entries must be non-empty strings"
                )
        assets[class_name] = tuple(asset_list)
    return DepartmentDef(
        name=dept_name, prefix=prefix.rstrip("/"), assets=assets
    )


def _build_asset_class_def(class_name: Any, class_data: Any) -> AssetClassDef:
    if not isinstance(class_name, str) or not class_name:
        raise CatalogError("asset_classes keys must be non-empty strings")
    if not isinstance(class_data, dict):
        raise CatalogError(f"asset_classes.{class_name}: must be a mapping")
    metrics_raw = class_data.get("metrics") or {}
    if not isinstance(metrics_raw, dict) or not metrics_raw:
        raise CatalogError(
            f"asset_classes.{class_name}.metrics: required non-empty mapping"
        )
    # Schema v2: 'assets' key under asset_classes is no longer used.
    # Reject it with a clear error so anyone porting an old catalog
    # knows where to move the list.
    if "assets" in class_data:
        raise CatalogError(
            f"asset_classes.{class_name}.assets is no longer supported (schema v2). "
            "Move per-class asset lists into sites.<id>.departments.<dept>.assets.<class>."
        )
    metrics: list[MetricDef] = []
    for metric_key, metric_data in metrics_raw.items():
        metrics.append(_build_metric_def(class_name, metric_key, metric_data))
    return AssetClassDef(asset_class=class_name, metrics=tuple(metrics))


def _build_metric_def(
    class_name: str, metric_key: Any, metric_data: Any
) -> MetricDef:
    if not isinstance(metric_key, str) or not metric_key:
        raise CatalogError(
            f"asset_classes.{class_name}.metrics: keys must be non-empty strings"
        )
    if not isinstance(metric_data, dict):
        raise CatalogError(
            f"asset_classes.{class_name}.metrics.{metric_key}: must be a mapping"
        )
    display_name = metric_data.get("display_name")
    unit = metric_data.get("unit", "")
    suffix = metric_data.get("suffix")
    if not isinstance(display_name, str) or not display_name:
        raise CatalogError(
            f"asset_classes.{class_name}.metrics.{metric_key}.display_name: required"
        )
    if not isinstance(suffix, str) or not suffix:
        raise CatalogError(
            f"asset_classes.{class_name}.metrics.{metric_key}.suffix: required"
        )
    if not isinstance(unit, str):
        raise CatalogError(
            f"asset_classes.{class_name}.metrics.{metric_key}.unit: must be a string"
        )
    return MetricDef(
        metric_key=metric_key,
        display_name=display_name,
        unit=unit,
        suffix=suffix.strip("/"),
    )
