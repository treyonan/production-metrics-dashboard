"""Unit tests for ``compute_conveyor_totals``.

Pure function, no I/O -- tests build ``ProductionReportRow`` dataclasses
by hand rather than exercising either the CSV or SQL source. The
reference case (``test_trey_sample_matrix``) replays the three-prod-run
table Trey sketched in conversation 2026-04-23:

    |            | C1  | C2  | (row total)
    | prod run 1 | 100 |  50 |  150
    | prod run 2 | 250 |  45 |  295
    | prod run 3 |  75 | 125 |  200
    | (col total)| 425 | 220 |  645

Cross-sum invariant: ``sum(per_conveyor.values()) == grand_total`` and
``sum(row totals) == grand_total`` are both asserted.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from app.integrations.production_report.base import ProductionReportRow
from app.services.production_report import (
    ConveyorAggregate,
    compute_conveyor_totals,
)


# ---- helpers --------------------------------------------------------------


def _row(
    *,
    site_id: str = "101",
    department_id: str = "127",
    metrics: dict[str, Any] | None = None,
    prod_date: datetime | None = None,
    row_id: int = 1,
) -> ProductionReportRow:
    """Build a ``ProductionReportRow`` with a ``Metrics`` payload."""
    return ProductionReportRow(
        id=row_id,
        prod_date=prod_date or datetime(2026, 4, 22),
        prod_id=f"TEST_{row_id:03d}",
        site_id=site_id,
        department_id=department_id,
        payload={"Metrics": metrics or {}},
        dtm=None,
    )


def _assert_cross_sum(agg: ConveyorAggregate) -> None:
    """Sum of per-conveyor values must equal grand_total exactly."""
    total = sum(agg.per_conveyor.values())
    assert total == agg.grand_total, (
        f"cross-sum invariant violated: sum(per_conveyor)={total} "
        f"but grand_total={agg.grand_total}"
    )


# ---- tests ----------------------------------------------------------------


def test_single_report_two_conveyors() -> None:
    """Today view: one entry with C1=100 C2=50 -> grand total 150."""
    entries = [
        _row(metrics={
            "C1": {"Total": 100, "Availability": 90},
            "C2": {"Total": 50, "Availability": 80},
        }),
    ]
    result = compute_conveyor_totals(entries)
    agg = result[("101", "127")]
    assert agg.per_conveyor == {"C1": 100.0, "C2": 50.0}
    assert agg.grand_total == 150.0
    assert agg.conveyors_counted == 2
    assert agg.reports_counted == 1
    _assert_cross_sum(agg)


def test_trey_sample_matrix() -> None:
    """Week view: three prod runs, column totals C1=425 C2=220, grand 645.

    This is the canonical reference case from the 2026-04-23 design
    conversation. If this fails, the compute function diverged from
    the documented contract.
    """
    entries = [
        _row(row_id=1, metrics={"C1": {"Total": 100}, "C2": {"Total": 50}}),
        _row(row_id=2, metrics={"C1": {"Total": 250}, "C2": {"Total": 45}}),
        _row(row_id=3, metrics={"C1": {"Total": 75},  "C2": {"Total": 125}}),
    ]
    result = compute_conveyor_totals(entries)
    agg = result[("101", "127")]
    assert agg.per_conveyor == {"C1": 425.0, "C2": 220.0}
    assert agg.grand_total == 645.0
    assert agg.conveyors_counted == 2
    assert agg.reports_counted == 3
    _assert_cross_sum(agg)

    # Second invariant Trey made explicit in the matrix: sum of row
    # totals also equals the grand total.
    row_totals = [100 + 50, 250 + 45, 75 + 125]
    assert sum(row_totals) == agg.grand_total


def test_null_total_treated_as_zero() -> None:
    """Null or missing Total on any row contributes 0, doesn't skip the row."""
    entries = [
        _row(row_id=1, metrics={"C1": {"Total": 100}}),
        _row(row_id=2, metrics={"C1": {"Total": None}}),
        _row(row_id=3, metrics={"C1": {"Total": 75}}),
    ]
    agg = compute_conveyor_totals(entries)[("101", "127")]
    assert agg.per_conveyor == {"C1": 175.0}
    assert agg.grand_total == 175.0
    assert agg.reports_counted == 3  # null-Total row still counted as a report
    _assert_cross_sum(agg)


def test_missing_total_field_treated_as_zero() -> None:
    """Entirely absent ``Total`` key on a CX object also behaves as 0."""
    entries = [
        _row(row_id=1, metrics={"C1": {"Total": 100, "Availability": 90}}),
        _row(row_id=2, metrics={"C1": {"Availability": 0}}),  # no Total key
    ]
    agg = compute_conveyor_totals(entries)[("101", "127")]
    assert agg.per_conveyor == {"C1": 100.0}
    assert agg.grand_total == 100.0
    _assert_cross_sum(agg)


def test_nan_string_treated_as_zero() -> None:
    """"NaN" parses as IEEE NaN via float() but must not poison the sum.

    ``float("NaN")`` succeeds and returns an IEEE NaN -- it does NOT
    raise ValueError. Without a finiteness check, that NaN would
    propagate through ``sum()`` and silently corrupt the grand total
    (NaN + anything = NaN). The finite-float guard catches it.
    """
    entries = [
        _row(metrics={"C1": {"Total": "NaN"}, "C2": {"Total": 50}}),
    ]
    agg = compute_conveyor_totals(entries)[("101", "127")]
    assert agg.per_conveyor == {"C1": 0.0, "C2": 50.0}
    assert agg.grand_total == 50.0
    _assert_cross_sum(agg)


def test_actual_nan_float_treated_as_zero() -> None:
    """A raw ``float("nan")`` value survives JSON round-trip in some
    stacks (e.g. Python's ``json`` module with ``allow_nan=True``) and
    must be rejected the same way the "NaN" string is.
    """
    entries = [
        _row(metrics={"C1": {"Total": float("nan")}, "C2": {"Total": 50}}),
    ]
    agg = compute_conveyor_totals(entries)[("101", "127")]
    assert agg.per_conveyor == {"C1": 0.0, "C2": 50.0}
    assert agg.grand_total == 50.0


def test_infinite_total_treated_as_zero() -> None:
    """+inf and -inf are also non-finite and must not propagate."""
    entries_pos = [_row(metrics={"C1": {"Total": float("inf")}, "C2": {"Total": 50}})]
    entries_neg = [_row(metrics={"C1": {"Total": float("-inf")}, "C2": {"Total": 50}})]
    assert compute_conveyor_totals(entries_pos)[("101", "127")].grand_total == 50.0
    assert compute_conveyor_totals(entries_neg)[("101", "127")].grand_total == 50.0


def test_unparseable_string_treated_as_zero() -> None:
    """A true garbage string (e.g. from a corrupt row) gets 0, not an exception."""
    entries = [
        _row(metrics={"C1": {"Total": "not a number"}, "C2": {"Total": 50}}),
    ]
    agg = compute_conveyor_totals(entries)[("101", "127")]
    assert agg.per_conveyor == {"C1": 0.0, "C2": 50.0}


def test_numeric_string_is_accepted() -> None:
    """A well-formed numeric string ("100.5") is a legitimate value and sums.

    Guards against an over-aggressive fix to the NaN case -- we still
    want to accept real numeric strings, since JSON doesn't strictly
    distinguish strings from numbers in all upstream toolchains.
    """
    entries = [
        _row(metrics={"C1": {"Total": "100.5"}, "C2": {"Total": 50}}),
    ]
    agg = compute_conveyor_totals(entries)[("101", "127")]
    assert agg.per_conveyor == {"C1": 100.5, "C2": 50.0}
    assert agg.grand_total == 150.5
    _assert_cross_sum(agg)


def test_non_cx_keys_excluded() -> None:
    """Workcenter, Site, Circuit, Crusher_1, Screen_1 all ignored.

    Only keys matching /^C\\d+$/ contribute. Crusher_1 is deliberately
    excluded even though it has a Total field (belt scales only).
    """
    entries = [
        _row(metrics={
            "Workcenter": {"Total": 999, "Availability": 80},
            "Site":       {"Total": 888},
            "Circuit":    {"A": {"Runtime": 500}},
            "Crusher_1":  {"Total": 1000, "Availability": 75},
            "Screen_1":   {"Total": 2000, "Availability": 98},
            "C1":         {"Total": 100},
            "C3":         {"Total": 50},
        }),
    ]
    agg = compute_conveyor_totals(entries)[("101", "127")]
    assert agg.per_conveyor == {"C1": 100.0, "C3": 50.0}
    assert agg.grand_total == 150.0
    _assert_cross_sum(agg)


def test_workcenter_with_no_cx_is_omitted() -> None:
    """A workcenter whose payload has no CX keys doesn't appear in the output.

    The frontend reads the absent key as 'no chart to render' and
    shows the empty-state caption. Returning an empty aggregate would
    be no more informative and just bloats the response.
    """
    entries = [
        _row(department_id="127", metrics={"C1": {"Total": 100}}),
        _row(department_id="130", metrics={"Workcenter": {"Total": 500}}),  # no CX
    ]
    result = compute_conveyor_totals(entries)
    assert ("101", "127") in result
    assert ("101", "130") not in result


def test_multiple_workcenters_kept_separate() -> None:
    """Different (site_id, department_id) tuples produce independent aggregates."""
    entries = [
        _row(department_id="127", row_id=1, metrics={"C1": {"Total": 100}}),
        _row(department_id="127", row_id=2, metrics={"C1": {"Total": 50}}),
        _row(department_id="130", row_id=3, metrics={"C1": {"Total": 200}}),
    ]
    result = compute_conveyor_totals(entries)
    assert result[("101", "127")].per_conveyor == {"C1": 150.0}
    assert result[("101", "127")].reports_counted == 2
    assert result[("101", "130")].per_conveyor == {"C1": 200.0}
    assert result[("101", "130")].reports_counted == 1


def test_numeric_sort_order() -> None:
    """C1, C3, C10 sort numerically, not lexically (C1, C10, C3)."""
    entries = [
        _row(metrics={
            "C10": {"Total": 10},
            "C1":  {"Total": 1},
            "C3":  {"Total": 3},
            "C7":  {"Total": 7},
        }),
    ]
    agg = compute_conveyor_totals(entries)[("101", "127")]
    # dict preserves insertion order; we rely on that for the wire shape.
    assert list(agg.per_conveyor.keys()) == ["C1", "C3", "C7", "C10"]


def test_empty_entries_returns_empty_result() -> None:
    """No entries in, no aggregates out."""
    assert compute_conveyor_totals([]) == {}


def test_no_metrics_key_in_payload() -> None:
    """Payload without a ``Metrics`` key contributes nothing, doesn't raise."""
    rows = [
        ProductionReportRow(
            id=1,
            prod_date=datetime(2026, 4, 22),
            prod_id="TEST",
            site_id="101",
            department_id="127",
            payload={},  # no Metrics at all
            dtm=None,
        ),
    ]
    assert compute_conveyor_totals(rows) == {}


def test_metrics_not_a_dict_is_skipped() -> None:
    """If Metrics is malformed (not a dict), we skip rather than crash."""
    rows = [
        ProductionReportRow(
            id=1,
            prod_date=datetime(2026, 4, 22),
            prod_id="TEST",
            site_id="101",
            department_id="127",
            payload={"Metrics": "not a dict"},
            dtm=None,
        ),
    ]
    assert compute_conveyor_totals(rows) == {}


@pytest.mark.parametrize(
    "bad_cx_data",
    [
        None,
        "string instead of object",
        ["array", "instead"],
        42,
    ],
)
def test_cx_value_not_a_dict_is_skipped(bad_cx_data: Any) -> None:
    """CX keys with non-dict values (malformed payload) don't contribute."""
    entries = [
        _row(metrics={
            "C1": bad_cx_data,
            "C2": {"Total": 50},
        }),
    ]
    agg = compute_conveyor_totals(entries)[("101", "127")]
    assert agg.per_conveyor == {"C2": 50.0}
    assert agg.grand_total == 50.0




# ---- Phase 5.3: product_mode (most-frequent product) --------------------


def test_product_mode_picks_most_frequent() -> None:
    """Mode is the value that appears most often for the conveyor."""
    entries = [
        # Newest first (higher row_id = more recent in this test setup).
        _row(row_id=5, metrics={"C1": {"Total": 100, "Produced_Item_Description": "#57"}}),
        _row(row_id=4, metrics={"C1": {"Total": 100, "Produced_Item_Description": "#57"}}),
        _row(row_id=3, metrics={"C1": {"Total": 100, "Produced_Item_Description": "#8"}}),
        _row(row_id=2, metrics={"C1": {"Total": 100, "Produced_Item_Description": "#57"}}),
        _row(row_id=1, metrics={"C1": {"Total": 100, "Produced_Item_Description": "#8"}}),
    ]
    agg = compute_conveyor_totals(entries)[("101", "127")]
    assert agg.product_mode == {"C1": "#57"}
    # Totals still accumulate across all reports regardless of mode
    assert agg.per_conveyor == {"C1": 500.0}


def test_product_mode_tie_broken_by_newest() -> None:
    """On a tie, the value in the newer report wins.

    Counter.most_common(1) returns the first-seen max; with entries
    walked newest-first, the first-inserted value in a tie is the
    newer one. "Mode, tied to newest" semantics.
    """
    entries = [
        _row(row_id=4, metrics={"C1": {"Total": 100, "Produced_Item_Description": "#57"}}),  # newest
        _row(row_id=3, metrics={"C1": {"Total": 100, "Produced_Item_Description": "#8"}}),
        _row(row_id=2, metrics={"C1": {"Total": 100, "Produced_Item_Description": "#57"}}),
        _row(row_id=1, metrics={"C1": {"Total": 100, "Produced_Item_Description": "#8"}}),   # oldest
    ]
    agg = compute_conveyor_totals(entries)[("101", "127")]
    assert agg.product_mode == {"C1": "#57"}


def test_product_mode_excludes_placeholders() -> None:
    """Placeholder values don't contribute to the mode count.

    If a conveyor was idle ("_") more often than it ran "#57", the mode
    is still "#57" because that's the only real product reported.
    Operators want to know what product was on the belt, not how often
    it was idle.
    """
    entries = [
        _row(row_id=4, metrics={"C1": {"Total": 0, "Produced_Item_Description": "_"}}),
        _row(row_id=3, metrics={"C1": {"Total": 0, "Produced_Item_Description": "_"}}),
        _row(row_id=2, metrics={"C1": {"Total": 0, "Produced_Item_Description": "_"}}),
        _row(row_id=1, metrics={"C1": {"Total": 100, "Produced_Item_Description": "#57"}}),
    ]
    agg = compute_conveyor_totals(entries)[("101", "127")]
    assert agg.product_mode == {"C1": "#57"}


def test_product_mode_all_placeholders_is_none() -> None:
    """Every observation is a placeholder -> product_mode is None."""
    entries = [
        _row(row_id=3, metrics={"C1": {"Total": 0, "Produced_Item_Description": "_"}}),
        _row(row_id=2, metrics={"C1": {"Total": 0, "Produced_Item_Description": "None"}}),
        _row(row_id=1, metrics={"C1": {"Total": 0, "Produced_Item_Description": ""}}),
    ]
    agg = compute_conveyor_totals(entries)[("101", "127")]
    assert agg.product_mode == {"C1": None}


def test_product_mode_missing_or_non_string_is_none() -> None:
    """Absent, null, or non-string description values contribute nothing."""
    entries = [
        _row(metrics={
            "C1": {"Total": 100},                                    # no description field
            "C2": {"Total": 50, "Produced_Item_Description": None},  # explicit null
            "C3": {"Total": 25, "Produced_Item_Description": 42},    # non-string
        }),
    ]
    agg = compute_conveyor_totals(entries)[("101", "127")]
    assert agg.product_mode == {"C1": None, "C2": None, "C3": None}


def test_product_mode_key_order_matches_per_conveyor() -> None:
    """``product_mode`` iterates in the same numeric-CX order as ``per_conveyor``."""
    entries = [_row(metrics={
        "C10": {"Total": 10, "Produced_Item_Description": "#10"},
        "C1":  {"Total": 1,  "Produced_Item_Description": "#1"},
        "C3":  {"Total": 3,  "Produced_Item_Description": "#3"},
    })]
    agg = compute_conveyor_totals(entries)[("101", "127")]
    assert list(agg.product_mode.keys()) == ["C1", "C3", "C10"]
    assert list(agg.per_conveyor.keys()) == ["C1", "C3", "C10"]
