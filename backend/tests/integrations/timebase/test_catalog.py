"""Unit tests for the Timebase i3X catalog loader + resolver."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.integrations.timebase.catalog import (
    _DEFAULT_CATALOG_PATH,
    CatalogError,
    TimebaseCatalog,
    load_catalog,
)

# ============================================================================
# Loading the real shipped catalog.yaml
# ============================================================================


def test_real_catalog_loads() -> None:
    """The shipped catalog.yaml parses cleanly."""
    catalog = load_catalog()
    assert isinstance(catalog, TimebaseCatalog)
    # Site '101' is Phase 1's only configured site.
    assert "101" in catalog.sites
    site = catalog.sites["101"]
    assert site.code == "BCQ"
    assert site.dataset == "IAP_BCQ_Controls"
    assert site.base_url == "http://10.44.135.12:8080"
    assert "Secondary" in site.departments
    assert site.departments["Secondary"] == "Big_Canyon/Secondary"


def test_real_catalog_site_id_is_string() -> None:
    """Site IDs are strings throughout for consistency with Flow / SQL."""
    catalog = load_catalog()
    for sid in catalog.sites:
        assert isinstance(sid, str)


def test_real_catalog_has_conveyor_class() -> None:
    catalog = load_catalog()
    assert "Conveyor" in catalog.asset_classes
    conveyor = catalog.asset_classes["Conveyor"]
    assert conveyor.assets == ("C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8")
    metric_keys = [m.metric_key for m in conveyor.metrics]
    assert "belt_scale_tph" in metric_keys


def test_real_catalog_resolves_known_tag() -> None:
    """The example tag from the spec resolves correctly end-to-end."""
    catalog = load_catalog()
    element_id = catalog.resolve_element_id(
        site_id="101",
        department="Secondary",
        asset_class="Conveyor",
        asset="C1",
        metric_key="belt_scale_tph",
    )
    assert element_id == (
        "IAP_BCQ_Controls:Big_Canyon/Secondary/Conveyor/C1"
        "/Process_Data/Belt_Scale/TPH"
    )


def test_default_catalog_path_resolves_under_integration_module() -> None:
    """Sanity: the shipped catalog ships in the right spot."""
    assert _DEFAULT_CATALOG_PATH.name == "catalog.yaml"
    assert _DEFAULT_CATALOG_PATH.is_file()


# ============================================================================
# Response builder
# ============================================================================


def test_build_response_all_sites() -> None:
    """Whole-catalog response includes every configured site."""
    catalog = load_catalog()
    resp = catalog.build_response()
    site_ids = [s.site_id for s in resp.sites]
    assert "101" in site_ids


def test_build_response_one_site() -> None:
    """Single-site response surfaces just the requested site."""
    catalog = load_catalog()
    resp = catalog.build_response(site_id="101")
    assert len(resp.sites) == 1
    site = resp.sites[0]
    assert site.site_id == "101"
    secondary = next(d for d in site.departments if d.name == "Secondary")
    conveyor = next(
        ac for ac in secondary.asset_classes if ac.asset_class == "Conveyor"
    )
    c1 = next(a for a in conveyor.assets if a.asset == "C1")
    tph = next(m for m in c1.metrics if m.metric_key == "belt_scale_tph")
    assert tph.element_id == (
        "IAP_BCQ_Controls:Big_Canyon/Secondary/Conveyor/C1"
        "/Process_Data/Belt_Scale/TPH"
    )
    assert tph.display_name == "Belt Scale TPH"
    assert tph.unit == "tph"


def test_build_response_does_not_expose_base_url() -> None:
    """base_url is internal -- don't leak historian IPs through public API."""
    catalog = load_catalog()
    resp = catalog.build_response(site_id="101")
    j = resp.model_dump_json(by_alias=True)
    assert "10.44.135.12" not in j
    assert "base_url" not in j


def test_build_response_unknown_site_raises() -> None:
    catalog = load_catalog()
    with pytest.raises(CatalogError):
        catalog.build_response(site_id="999")


def test_build_response_uses_class_alias_on_wire() -> None:
    """The asset_class field serializes as 'class' (i3X-style alias)."""
    catalog = load_catalog()
    resp = catalog.build_response(site_id="101")
    j = resp.model_dump_json(by_alias=True)
    assert '"class":' in j


# ============================================================================
# Resolver error cases
# ============================================================================


def test_resolve_unknown_site_raises() -> None:
    catalog = load_catalog()
    with pytest.raises(CatalogError, match="Unknown site_id"):
        catalog.resolve_element_id(
            site_id="999",
            department="Secondary",
            asset_class="Conveyor",
            asset="C1",
            metric_key="belt_scale_tph",
        )


def test_resolve_unknown_department_raises() -> None:
    catalog = load_catalog()
    with pytest.raises(CatalogError, match="Unknown department"):
        catalog.resolve_element_id(
            site_id="101",
            department="Tertiary",
            asset_class="Conveyor",
            asset="C1",
            metric_key="belt_scale_tph",
        )


def test_resolve_unknown_asset_class_raises() -> None:
    catalog = load_catalog()
    with pytest.raises(CatalogError, match="Unknown asset_class"):
        catalog.resolve_element_id(
            site_id="101",
            department="Secondary",
            asset_class="Crusher",
            asset="C1",
            metric_key="belt_scale_tph",
        )


def test_resolve_unknown_asset_raises() -> None:
    catalog = load_catalog()
    with pytest.raises(CatalogError, match="Unknown asset"):
        catalog.resolve_element_id(
            site_id="101",
            department="Secondary",
            asset_class="Conveyor",
            asset="C99",
            metric_key="belt_scale_tph",
        )


def test_resolve_unknown_metric_raises() -> None:
    catalog = load_catalog()
    with pytest.raises(CatalogError, match="Unknown metric_key"):
        catalog.resolve_element_id(
            site_id="101",
            department="Secondary",
            asset_class="Conveyor",
            asset="C1",
            metric_key="does_not_exist",
        )


# ============================================================================
# Loader error cases (malformed YAML, missing fields)
# ============================================================================


def _write_yaml(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "catalog.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def test_load_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(CatalogError, match="not found"):
        load_catalog(tmp_path / "nope.yaml")


def test_load_malformed_yaml_raises(tmp_path: Path) -> None:
    p = _write_yaml(tmp_path, "this: : is: invalid:")
    with pytest.raises(CatalogError, match="parse error"):
        load_catalog(p)


def test_load_non_mapping_top_level_raises(tmp_path: Path) -> None:
    p = _write_yaml(tmp_path, "- just\n- a\n- list\n")
    with pytest.raises(CatalogError, match="mapping at the top level"):
        load_catalog(p)


def test_load_site_missing_dataset_raises(tmp_path: Path) -> None:
    body = """
sites:
  "101":
    code: BCQ
    display_name: Big Canyon Quarry
    base_url: http://10.44.135.12:8080
    departments:
      Secondary: Big_Canyon/Secondary
asset_classes:
  Conveyor:
    assets: [C1]
    metrics:
      belt_scale_tph:
        display_name: Belt Scale TPH
        unit: tph
        suffix: Process_Data/Belt_Scale/TPH
"""
    p = _write_yaml(tmp_path, body)
    with pytest.raises(CatalogError, match="dataset"):
        load_catalog(p)


def test_load_site_missing_base_url_raises(tmp_path: Path) -> None:
    body = """
sites:
  "101":
    code: BCQ
    display_name: Big Canyon Quarry
    dataset: IAP_BCQ_Controls
    departments:
      Secondary: Big_Canyon/Secondary
asset_classes:
  Conveyor:
    assets: [C1]
    metrics:
      belt_scale_tph:
        display_name: Belt Scale TPH
        unit: tph
        suffix: Process_Data/Belt_Scale/TPH
"""
    p = _write_yaml(tmp_path, body)
    with pytest.raises(CatalogError, match="base_url"):
        load_catalog(p)


def test_load_metric_missing_suffix_raises(tmp_path: Path) -> None:
    body = """
sites:
  "101":
    code: BCQ
    display_name: Big Canyon Quarry
    dataset: IAP_BCQ_Controls
    base_url: http://10.44.135.12:8080
    departments:
      Secondary: Big_Canyon/Secondary
asset_classes:
  Conveyor:
    assets: [C1]
    metrics:
      belt_scale_tph:
        display_name: Belt Scale TPH
        unit: tph
"""
    p = _write_yaml(tmp_path, body)
    with pytest.raises(CatalogError, match="suffix"):
        load_catalog(p)


def test_int_yaml_key_coerced_to_str(tmp_path: Path) -> None:
    """Unquoted integer YAML keys (101: ...) are coerced to str."""
    body = """
sites:
  101:
    code: BCQ
    display_name: Big Canyon Quarry
    dataset: IAP_BCQ_Controls
    base_url: http://10.44.135.12:8080
    departments:
      Secondary: Big_Canyon/Secondary
asset_classes:
  Conveyor:
    assets: [C1]
    metrics:
      belt_scale_tph:
        display_name: Belt Scale TPH
        unit: tph
        suffix: Process_Data/Belt_Scale/TPH
"""
    p = _write_yaml(tmp_path, body)
    catalog = load_catalog(p)
    assert "101" in catalog.sites
    assert isinstance(catalog.sites["101"].site_id, str)


def test_trailing_slashes_in_paths_are_trimmed(tmp_path: Path) -> None:
    """Defensive: editors sometimes leave trailing slashes. We strip them."""
    body = """
sites:
  "101":
    code: BCQ
    display_name: Big Canyon Quarry
    dataset: IAP_BCQ_Controls
    base_url: http://10.44.135.12:8080/
    departments:
      Secondary: Big_Canyon/Secondary/
asset_classes:
  Conveyor:
    assets: [C1]
    metrics:
      belt_scale_tph:
        display_name: Belt Scale TPH
        unit: tph
        suffix: /Process_Data/Belt_Scale/TPH/
"""
    p = _write_yaml(tmp_path, body)
    catalog = load_catalog(p)
    assert catalog.sites["101"].base_url == "http://10.44.135.12:8080"
    element_id = catalog.resolve_element_id(
        site_id="101",
        department="Secondary",
        asset_class="Conveyor",
        asset="C1",
        metric_key="belt_scale_tph",
    )
    assert element_id == (
        "IAP_BCQ_Controls:Big_Canyon/Secondary/Conveyor/C1"
        "/Process_Data/Belt_Scale/TPH"
    )
    assert "//" not in element_id


def test_loader_falls_back_to_example_file_when_real_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When catalog.yaml is absent, loader uses catalog.example.yaml.

    This keeps tests + fresh checkouts working without manual setup.
    Production deployments must provide a real catalog.yaml.
    """
    from app.integrations.timebase import catalog as catalog_module

    # Point _CATALOG_REAL_PATH at a non-existent location so the real
    # file is "missing"; the example file still ships in the repo.
    fake_real = tmp_path / "definitely_not_here.yaml"
    monkeypatch.setattr(catalog_module, "_CATALOG_REAL_PATH", fake_real)
    catalog = load_catalog()
    # The example file has the safe placeholder URL.
    assert "example.invalid" in catalog.sites["101"].base_url


def test_loader_raises_when_neither_file_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.integrations.timebase import catalog as catalog_module

    monkeypatch.setattr(
        catalog_module, "_CATALOG_REAL_PATH", tmp_path / "no_real.yaml"
    )
    monkeypatch.setattr(
        catalog_module, "_CATALOG_EXAMPLE_PATH", tmp_path / "no_example.yaml"
    )
    with pytest.raises(CatalogError, match="No catalog file found"):
        load_catalog()

