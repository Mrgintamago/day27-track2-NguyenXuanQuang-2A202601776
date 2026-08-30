from datetime import datetime, timedelta, timezone
from pathlib import Path
import pandas as pd

from student_api import validate_orders

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "orders_contract.yaml"


def _iso(minutes_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def healthy_df():
    """A healthy frame must also be a *fresh* frame.

    The original fixture hardcoded 2026-08-28 timestamps, so it silently aged
    into a freshness breach (contract allows 30 minutes) as soon as the lab was
    run on a later day. Timestamps are now relative so "healthy" stays healthy
    regardless of the run date.
    """
    return pd.DataFrame([
        {
            "order_id": 1,
            "customer_id": "C1",
            "amount": 10.0,
            "currency": "USD",
            "status": "completed",
            "created_at": _iso(10),
            "updated_at": _iso(5),
        },
        {
            "order_id": 2,
            "customer_id": "C2",
            "amount": 20.0,
            "currency": "USD",
            "status": "pending",
            "created_at": _iso(9),
            "updated_at": _iso(4),
        },
    ])


def failed(issues):
    return [i for i in issues if not i["passed"]]


def test_healthy_contract_passes_starter_checks():
    assert not failed(validate_orders(healthy_df(), CONTRACT))


def test_duplicate_order_id_is_detected():
    df = healthy_df()
    df.loc[1, "order_id"] = 1
    issues = failed(validate_orders(df, CONTRACT))
    assert any(i["check"] == "unique" and i["column"] == "order_id" for i in issues)


def test_invalid_currency_is_detected():
    df = healthy_df()
    df.loc[0, "currency"] = "BTC"
    issues = failed(validate_orders(df, CONTRACT))
    assert any(i["check"] == "accepted_values" and i["column"] == "currency" for i in issues)


def test_type_drift_in_amount_is_detected():
    df = healthy_df()
    df["amount"] = df["amount"].astype(object)
    df.loc[0, "amount"] = "N/A"
    issues = failed(validate_orders(df, CONTRACT))
    assert any(i["check"] == "type" and i["column"] == "amount" for i in issues)


def test_stale_data_breaks_freshness():
    df = healthy_df()
    df["updated_at"] = _iso(24 * 60)
    issues = failed(validate_orders(df, CONTRACT))
    assert any(i["check"] == "freshness" for i in issues)


def test_missing_required_column_does_not_raise():
    df = healthy_df().drop(columns=["amount"])
    issues = failed(validate_orders(df, CONTRACT))
    assert any(i["check"] == "required_column" and i["column"] == "amount" for i in issues)


def test_critical_failure_routes_to_block():
    df = healthy_df()
    df.loc[1, "order_id"] = 1
    issues = failed(validate_orders(df, CONTRACT))
    unique_issue = next(i for i in issues if i["check"] == "unique")
    assert unique_issue["severity"] == "critical"
    assert unique_issue["action"] == "block"
