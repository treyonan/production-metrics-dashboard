"""Unit tests for the Timebase i3X catalog loader + resolver (schema v2)."""

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
# Loading the real shipped catalog.yaml (BCQ-only, all conveyors in Secondary)
# ============================================================================


def test_real_catalog_loads() -> None:
    """The shipped catalog.yaml parses cleanly."""
    catalog = load_catalog()
    assert isinstance(catalog, TimebaseCatalog)
    assert "101" in catalog.sites
    site = catalog.sites["101"]
    assert site.code == "BCQ"
    assert site.dataset == "IAP_BCQ_Controls"
    assert site.base_url.startswith("http://")
    assert "Secondary" in site.departments
    secondary = site.departments["Secondary"]
    assert secondary.prefix == "Big_Canyon/Secondary"
    assert "Conveyor" in secondary.assets


def test_real_catalog_site_id_is_string() -> None:
    catalog = load_catalog()
    for sid in catalog.sites:
        assert isinstance(sid, str)


def test_real_catalog_has_conveyor_metric_registry() -> None:
    """Schema v2: asset_classes holds metrics only, no global assets list."""
    catalog = load_catalog()
    conveyor = catalog.asset_classes["Conveyor"]
    metric_keys = [m.metric_key for m in conveyor.metrics]
    assert "belt_scale_tph" in metric_keys


def test_real_catalog_conveyor_placement_is_per_department() -> None:
    """Per-site placement: Conveyor assets are declared inside the dept block.

    Asserts INVARIANTS, not a snapshot. The exact conveyor list is
    operational config that changes whenever a site adds or moves a
    conveyor, so pinning it here would break this test on every
    catalog.yaml edit -- which is exactly the wrong cost / benefit
    trade for a "does the schema work" test.

    What we actually want to verify:
      * Conveyor lives under at least one department on site 101.
      * Each conveyor entry is a string matching the C<digits>
        naming convention (catches things like accidental empty
        strings or paths leaking into the asset list).
      * The list contains at least the founding conveyor (C1) so
        we'd notice if the loader silently returned an empty tuple.
    """
    import re

    catalog = load_catalog()
    site = catalog.sites["101"]
    assert site.departments, "Site 101 should have at least one department"

    # Find every department that owns conveyors -- per-site placement
    # means we don't pin which department they live in.
    departments_with_conveyors = {
        name: dept
        for name, dept in site.departments.items()
        if "Conveyor" in dept.assets
    }
    assert departments_with_conveyors, (
        "Site 101 should have Conveyor assets in at least one department"
    )

    all_conveyors: list[str] = []
    conveyor_pattern = re.compile(r"^C\d+$")
    for dept_name, dept in departments_with_conveyors.items():
        assets = dept.assets["Conveyor"]
        assert isinstance(assets, tuple), (
            f"Department {dept_name!r} Conveyor list should be a tuple, "
            f"got {type(assets).__name__}"
        )
        assert assets, f"Department {dept_name!r} has an empty Conveyor list"
        for c in assets:
            assert conveyor_pattern.match(c), (
                f"Conveyor id {c!r} in dept {dept_name!r} does not match "
                f"the C<digits> convention"
            )
            all_conveyors.append(c)

    assert "C1" in all_conveyors, (
        "Founding conveyor C1 missing from site 101 -- the loader may "
        "have returned empty placement data"
    )


def test_real_catalog_resolves_known_tag() -> None:
    """The spec example resolves correctly with the new schema."""
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
    assert _DEFAULT_CATALOG_PATH.name == "catalog.yaml"
    assert _DEFAULT_CATALOG_PATH.is_file()


# ============================================================================
# Response builder
# ============================================================================


def test_build_response_all_sites() -> None:
    catalog = load_catalog()
    resp = catalog.build_response()
    site_ids = [s.site_id for s in resp.sites]
    assert "101" in site_ids


def test_build_response_one_site() -> None:
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
    catalog = load_catalog()
    resp = catalog.build_response(site_id="101")
    j = resp.model_dump_json(by_alias=True)
    # Real or example IP must not leak into the public response.
    assert "10.44.135.12" not in j
    assert "example.invalid" not in j
    assert "base_url" not in j


def test_build_response_unknown_site_raises() -> None:
    catalog = load_catalog()
    with pytest.raises(CatalogError):
        catalog.build_response(site_id="999")


def test_build_response_uses_class_alias_on_wire() -> None:
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
# Per-site asset placement (schema v2 key feature)
# ============================================================================


_MULTI_SITE_YAML = """
sites:
  "101":
    code: BCQ
    display_name: Big Canyon Quarry
    base_url: http://10.0.0.1:4511
    dataset: IAP_BCQ_Controls
    departments:
      Secondary:
        prefix: Big_Canyon/Secondary
        assets:
          Conveyor: [C1, C2, C3, C4, C5, C6, C7, C8]
  "100":
    code: ARQ
    display_name: Ardmore Quarry
    base_url: http://10.0.0.2:4511
    dataset: IAP_ARQ_Controls
    departments:
      Primary:
        prefix: Ardmore/Primary
        assets:
          Conveyor: [C1, C2]
      Secondary:
        prefix: Ardmore/Secondary
        assets:
          Conveyor: [C3, C4, C5, C6, C7, C8]
asset_classes:
  Conveyor:
    metrics:
      belt_scale_tph:
        display_name: Belt Scale TPH
        unit: tph
        suffix: Process_Data/Belt_Scale/TPH
"""


def _write_yaml(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "catalog.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def test_per_site_placement_resolves_correctly(tmp_path: Path) -> None:
    """C1 lives in Secondary at BCQ but in Primary at ARQ -- both resolve."""
    p = _write_yaml(tmp_path, _MULTI_SITE_YAML)
    catalog = load_catalog(p)

    bcq_c1 = catalog.resolve_element_id(
        site_id="101", department="Secondary",
        asset_class="Conveyor", asset="C1", metric_key="belt_scale_tph",
    )
    assert bcq_c1 == (
        "IAP_BCQ_Controls:Big_Canyon/Secondary/Conveyor/C1"
        "/Process_Data/Belt_Scale/TPH"
    )

    arq_c1 = catalog.resolve_element_id(
        site_id="100", department="Primary",
        asset_class="Conveyor", asset="C1", metric_key="belt_scale_tph",
    )
    assert arq_c1 == (
        "IAP_ARQ_Controls:Ardmore/Primary/Conveyor/C1"
        "/Process_Data/Belt_Scale/TPH"
    )


def test_per_site_placement_rejects_wrong_department(tmp_path: Path) -> None:
    """ARQ/C1 is in Primary; querying it under Secondary must fail."""
    p = _write_yaml(tmp_path, _MULTI_SITE_YAML)
    catalog = load_catalog(p)
    with pytest.raises(CatalogError, match="Unknown asset.*C1"):
        catalog.resolve_element_id(
            site_id="100", department="Secondary",
            asset_class="Conveyor", asset="C1", metric_key="belt_scale_tph",
        )


def test_per_site_placement_in_response(tmp_path: Path) -> None:
    """Response builder honors per-dept assets, doesn't duplicate."""
    p = _write_yaml(tmp_path, _MULTI_SITE_YAML)
    catalog = load_catalog(p)
    resp = catalog.build_response(site_id="100")
    arq = resp.sites[0]
    primary = next(d for d in arq.departments if d.name == "Primary")
    primary_conv = next(
        ac for ac in primary.asset_classes if ac.asset_class == "Conveyor"
    )
    assert [a.asset for a in primary_conv.assets] == ["C1", "C2"]

    secondary = next(d for d in arq.departments if d.name == "Secondary")
    secondary_conv = next(
        ac for ac in secondary.asset_classes if ac.asset_class == "Conveyor"
    )
    assert [a.asset for a in secondary_conv.assets] == [
        "C3", "C4", "C5", "C6", "C7", "C8"
    ]


def test_department_can_omit_class_entirely(tmp_path: Path) -> None:
    """A dept with no conveyors emits no Conveyor block in the response."""
    body = """
sites:
  "200":
    code: ZZZ
    display_name: Test Site
    base_url: http://x:4511
    dataset: IAP_ZZZ_Controls
    departments:
      ScreensOnly:
        prefix: Plant/Screens
        assets:
          Screen: [S1, S2]
asset_classes:
  Conveyor:
    metrics:
      belt_scale_tph:
        display_name: Belt Scale TPH
        unit: tph
        suffix: Process_Data/Belt_Scale/TPH
  Screen:
    metrics:
      runtime_pct:
        display_name: Runtime %
        unit: pct
        suffix: Process_Data/Runtime
"""
    p = _write_yaml(tmp_path, body)
    catalog = load_catalog(p)
    resp = catalog.build_response(site_id="200")
    classes = [
        ac.asset_class
        for ac in resp.sites[0].departments[0].asset_classes
    ]
    assert classes == ["Screen"]  # Conveyor NOT emitted


# ============================================================================
# Loader error cases (malformed YAML, missing fields, schema v2 enforcement)
# ============================================================================


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


def test_load_site_missing_base_url_raises(tmp_path: Path) -> None:
    body = """
sites:
  "101":
    code: BCQ
    display_name: Big Canyon Quarry
    dataset: IAP_BCQ_Controls
    departments:
      Secondary:
        prefix: Big_Canyon/Secondary
        assets:
          Conveyor: [C1]
asset_classes:
  Conveyor:
    metrics:
      belt_scale_tph:
        display_name: Belt Scale TPH
        unit: tph
        suffix: Process_Data/Belt_Scale/TPH
"""
    p = _write_yaml(tmp_path, body)
    with pytest.raises(CatalogError, match="base_url"):
        load_catalog(p)


def test_load_department_missing_prefix_raises(tmp_path: Path) -> None:
    body = """
sites:
  "101":
    code: BCQ
    display_name: Big Canyon Quarry
    base_url: http://x:4511
    dataset: IAP_BCQ_Controls
    departments:
      Secondary:
        assets:
          Conveyor: [C1]
asset_classes:
  Conveyor:
    metrics:
      belt_scale_tph:
        display_name: Belt Scale TPH
        unit: tph
        suffix: Process_Data/Belt_Scale/TPH
"""
    p = _write_yaml(tmp_path, body)
    with pytest.raises(CatalogError, match="prefix"):
        load_catalog(p)


def test_load_department_missing_assets_raises(tmp_path: Path) -> None:
    body = """
sites:
  "101":
    code: BCQ
    display_name: Big Canyon Quarry
    base_url: http://x:4511
    dataset: IAP_BCQ_Controls
    departments:
      Secondary:
        prefix: Big_Canyon/Secondary
asset_classes:
  Conveyor:
    metrics:
      belt_scale_tph:
        display_name: Belt Scale TPH
        unit: tph
        suffix: Process_Data/Belt_Scale/TPH
"""
    p = _write_yaml(tmp_path, body)
    with pytest.raises(CatalogError, match="assets"):
        load_catalog(p)


def test_load_dept_assets_class_not_in_registry_raises(tmp_path: Path) -> None:
    """Cross-validation: dept references an asset_class that doesn't exist."""
    body = """
sites:
  "101":
    code: BCQ
    display_name: Big Canyon Quarry
    base_url: http://x:4511
    dataset: IAP_BCQ_Controls
    departments:
      Secondary:
        prefix: Big_Canyon/Secondary
        assets:
          Conveyer: [C1]   # typo: Conveyer (not in asset_classes)
asset_classes:
  Conveyor:
    metrics:
      belt_scale_tph:
        display_name: Belt Scale TPH
        unit: tph
        suffix: Process_Data/Belt_Scale/TPH
"""
    p = _write_yaml(tmp_path, body)
    with pytest.raises(CatalogError, match="unknown asset_class"):
        load_catalog(p)


def test_load_metric_missing_suffix_raises(tmp_path: Path) -> None:
    body = """
sites:
  "101":
    code: BCQ
    display_name: Big Canyon Quarry
    base_url: http://x:4511
    dataset: IAP_BCQ_Controls
    departments:
      Secondary:
        prefix: Big_Canyon/Secondary
        assets:
          Conveyor: [C1]
asset_classes:
  Conveyor:
    metrics:
      belt_scale_tph:
        display_name: Belt Scale TPH
        unit: tph
"""
    p = _write_yaml(tmp_path, body)
    with pytest.raises(CatalogError, match="suffix"):
        load_catalog(p)


def test_load_rejects_legacy_global_assets_under_class(tmp_path: Path) -> None:
    """Schema v2: assets under asset_classes.<class> is no longer accepted."""
    body = """
sites:
  "101":
    code: BCQ
    display_name: Big Canyon Quarry
    base_url: http://x:4511
    dataset: IAP_BCQ_Controls
    departments:
      Secondary:
        prefix: Big_Canyon/Secondary
        assets:
          Conveyor: [C1]
asset_classes:
  Conveyor:
    assets: [C1, C2, C3, C4, C5, C6, C7, C8]   # legacy v1 shape
    metrics:
      belt_scale_tph:
        display_name: Belt Scale TPH
        unit: tph
        suffix: Process_Data/Belt_Scale/TPH
"""
    p = _write_yaml(tmp_path, body)
    with pytest.raises(CatalogError, match="no longer supported"):
        load_catalog(p)


def test_int_yaml_key_coerced_to_str(tmp_path: Path) -> None:
    """Unquoted integer YAML keys (101: ...) are coerced to str."""
    body = """
sites:
  101:
    code: BCQ
    display_name: Big Canyon Quarry
    base_url: http://x:4511
    dataset: IAP_BCQ_Controls
    departments:
      Secondary:
        prefix: Big_Canyon/Secondary
        assets:
          Conveyor: [C1]
asset_classes:
  Conveyor:
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
    body = """
sites:
  "101":
    code: BCQ
    display_name: Big Canyon Quarry
    base_url: http://10.44.135.12:4511/
    dataset: IAP_BCQ_Controls
    departments:
      Secondary:
        prefix: Big_Canyon/Secondary/
        assets:
          Conveyor: [C1]
asset_classes:
  Conveyor:
    metrics:
      belt_scale_tph:
        display_name: Belt Scale TPH
        unit: tph
        suffix: /Process_Data/Belt_Scale/TPH/
"""
    p = _write_yaml(tmp_path, body)
    catalog = load_catalog(p)
    assert catalog.sites["101"].base_url == "http://10.44.135.12:4511"
    eid = catalog.resolve_element_id(
        site_id="101", department="Secondary",
        asset_class="Conveyor", asset="C1", metric_key="belt_scale_tph",
    )
    assert eid == (
        "IAP_BCQ_Controls:Big_Canyon/Secondary/Conveyor/C1"
        "/Process_Data/Belt_Scale/TPH"
    )
    assert "//" not in eid


# ============================================================================
# Missing-file behavior
# ============================================================================


def test_loader_raises_when_catalog_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Single committed source of truth -- no example.yaml fallback.

    Missing catalog.yaml is a hard error so the lifespan logs it
    and /api/timebase/* surfaces 503, instead of silently loading
    a placeholder template and surprising the operator with
    historian.example.invalid in production.
    """
    from app.integrations.timebase import catalog as catalog_module

    monkeypatch.setattr(
        catalog_module, "_DEFAULT_CATALOG_PATH", tmp_path / "no_catalog.yaml"
    )
    with pytest.raises(CatalogError, match="not found"):
        load_catalog()
