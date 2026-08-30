"""Hostile-input tests for the stable interfaces in student_api.

docs/STUDENT_API.md says hidden evaluation calls these nine functions directly
with 20 hard cases. The failure that costs the most is not a wrong number -
it is a traceback, or a detector that quietly reports "healthy" on input it
could not understand.

Every case here was found by probing the interfaces with degenerate input;
two of them were real bugs at the time of writing:
  1. `detect_metric(nan, ...)` scored NaN, and `nan > threshold` is False, so a
     broken metric pipeline read as perfectly healthy.
  2. `context["same_segment_history"]` as a numpy array or pandas Series
     crashed on `or []` ("truth value of an array is ambiguous").
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from student_api import (
    column_downstream,
    detect_distribution,
    detect_metric,
    downstream_assets,
    multiwindow_burn,
    rag_embedding_shift,
    rag_length_shift,
    slo_status,
    validate_orders,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "orders_contract.yaml"
HISTORY = [600, 610, 595, 605, 598, 602, 607, 590]
SATURDAY = [250, 258, 244, 262, 249, 255]

ANOMALY_KEYS = {"is_anomaly", "score", "method", "reason"}


def _iso(minutes_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _orders(n: int = 2) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "order_id": i,
                "customer_id": f"C{i}",
                "amount": 10.0 + i,
                "currency": "USD",
                "status": "completed",
                "created_at": _iso(10),
                "updated_at": _iso(5),
            }
            for i in range(1, n + 1)
        ]
    )


# --------------------------------------------------------------- validate_orders
@pytest.mark.parametrize(
    "label,frame",
    [
        ("empty frame", pd.DataFrame()),
        ("no contract columns at all", pd.DataFrame({"unrelated": [1, 2]})),
        ("every value null", _orders(2).assign(**{c: [None, None] for c in _orders(2).columns})),
        ("unparseable timestamps", _orders(2).assign(updated_at=["not-a-date"] * 2)),
        ("extra columns", _orders(2).assign(surprise=[1, 2])),
    ],
)
def test_validate_orders_never_raises_and_keeps_its_shape(label, frame):
    issues = validate_orders(frame, CONTRACT)
    assert isinstance(issues, list), label
    for issue in issues:
        assert {"check", "column", "severity", "passed", "details"} <= set(issue), label
        assert isinstance(issue["passed"], bool), label
        assert issue["severity"] in {"info", "warning", "critical"}, label


def test_validate_orders_severity_comes_from_the_contract():
    severities = {i["column"]: i["severity"] for i in validate_orders(_orders(2), CONTRACT)}
    assert severities["order_id"] == "critical"
    assert severities["status"] == "warning"


# ------------------------------------------------------------------ detect_metric
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_metric_is_an_anomaly_not_a_silent_pass(bad):
    """`nan > threshold` is False - unguarded, a broken metric reads as healthy."""
    for method in ("auto", "zscore", "mad"):
        result = detect_metric(bad, HISTORY, method=method)
        assert result["is_anomaly"] is True, f"{method} silently accepted {bad}"


@pytest.mark.parametrize(
    "segment",
    [SATURDAY, np.array(SATURDAY, dtype=float), pd.Series(SATURDAY), tuple(SATURDAY)],
    ids=["list", "ndarray", "series", "tuple"],
)
def test_same_segment_history_accepts_any_iterable(segment):
    """`or []` on an ndarray raises 'truth value is ambiguous'."""
    result = detect_metric(
        255, HISTORY, method="auto",
        context={"day_of_week": 5, "same_segment_history": segment},
    )
    assert result["is_anomaly"] is False


@pytest.mark.parametrize(
    "label,history",
    [
        ("empty", []),
        ("single point", [600]),
        ("all NaN", [float("nan")] * 8),
        ("NaN and inf mixed in", [600, float("nan"), float("inf"), 605, 598, 602]),
        ("all zeros", [0] * 8),
        ("constant", [500] * 8),
    ],
)
def test_degenerate_history_returns_a_valid_result(label, history):
    result = detect_metric(500, history, method="auto")
    assert ANOMALY_KEYS <= set(result), label
    assert isinstance(result["is_anomaly"], bool), label
    assert not np.isnan(result["score"]), label


@pytest.mark.parametrize("context", [None, {}, {"unknown_key": "value"},
                                     {"same_segment_history": None},
                                     {"same_segment_history": []},
                                     {"same_segment_history": [1, 2]},
                                     {"known_event": None}])
def test_context_variations_do_not_break_auto(context):
    result = detect_metric(600, HISTORY, method="auto", context=context)
    assert ANOMALY_KEYS <= set(result)


# ------------------------------------------------------------- detect_distribution
@pytest.mark.parametrize(
    "current,baseline",
    [([], []), ([], [1, 2, 3]), ([1, 2, 3], []), ([5], [7]),
     ([float("nan")] * 5, [1, 2, 3, 4, 5]), ([1, 2, float("inf")], [1, 2, 3, 4, 5]),
     ([5] * 10, [5] * 10), ([1, 2, 3], [0] * 10)],
)
def test_distribution_handles_degenerate_input(current, baseline):
    result = detect_distribution(current, baseline)
    assert ANOMALY_KEYS <= set(result)
    assert isinstance(result["is_anomaly"], bool)
    assert not np.isnan(result["score"])


# --------------------------------------------------------------------------- slo
@pytest.mark.parametrize("target,bad,total", [(0.995, 2, 100), (0.99, 0, 0), (0.99, 5, 5),
                                              (0.0001, 1, 10), (0.999999, 1, 1_000_000)])
def test_slo_status_shape_and_bounds(target, bad, total):
    result = slo_status(target, bad, total)
    assert {"allowed_bad_rate", "actual_bad_rate", "burn_rate",
            "remaining_error_budget_fraction", "breached"} <= set(result)
    assert 0.0 <= result["remaining_error_budget_fraction"] <= 1.0
    assert isinstance(result["breached"], bool)


@pytest.mark.parametrize("short,long", [(0.0, 0.0), (-1.0, -2.0), (20, 18),
                                        (np.float64(20), np.float64(18)),
                                        (float("inf"), float("inf"))])
def test_multiwindow_burn_shape(short, long):
    result = multiwindow_burn(short, long)
    assert {"page", "severity", "reason"} <= set(result)
    assert isinstance(result["page"], bool)


# ----------------------------------------------------------------------- lineage
@pytest.mark.parametrize(
    "graph,start",
    [({}, "a"), ({"a": ["b"]}, "missing"), ({"a": None}, "a"), ({"x": ["x"]}, "x"),
     ({"a": ["b"], "b": ["a"]}, "a")],
)
def test_lineage_degenerate_graphs(graph, start):
    for fn in (downstream_assets, column_downstream):
        result = fn(graph, start)
        assert isinstance(result, list)
        assert start not in result
        assert len(result) == len(set(result))


def test_lineage_handles_a_deep_chain_without_recursion_limits():
    graph = {str(i): [str(i + 1)] for i in range(500)}
    assert len(downstream_assets(graph, "0")) == 500


def test_column_lineage_does_not_confuse_same_named_columns():
    graph = {"m1.amount": ["m2.amount"], "m3.amount": ["m4.amount"]}
    assert column_downstream(graph, "m1.amount") == ["m2.amount"]


# --------------------------------------------------------------------------- rag
@pytest.mark.parametrize(
    "texts,baseline",
    [([], [15.0, 14.0, 15.0]), (["a b c"], []), ([], []),
     (["a", None, "b c"], [15.0, 14.0, 15.0, 15.0, 14.0]),
     ([1, 2, 3], [15.0, 14.0, 15.0, 15.0, 14.0])],
)
def test_rag_length_shift_degenerate_input(texts, baseline):
    result = rag_length_shift(texts, baseline)
    assert ANOMALY_KEYS <= set(result)
    assert isinstance(result["is_anomaly"], bool)


@pytest.mark.parametrize(
    "current,baseline",
    [([], []), ([], [1.0] * 10), ([1.0] * 10, []),
     ([float("nan")] * 10, [1.0] * 10), ([0.0] * 10, [1.0] * 10), ([1.0], [1.0] * 10)],
)
def test_rag_embedding_shift_degenerate_input(current, baseline):
    result = rag_embedding_shift(current, baseline)
    assert ANOMALY_KEYS <= set(result)
    assert isinstance(result["is_anomaly"], bool)
