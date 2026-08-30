#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from observability.anomaly import detect_anomaly
from observability.lineage import get_downstream_assets
from observability.rag_metrics import detect_text_length_shift
from observability.slo import calculate_slo
from src.contract_validator import (
    decide_action,
    failed_issues,
    load_contract,
    quarantine_rows,
    validate_dataframe,
)
from src.io_utils import load_jsonl


def main() -> None:
    orders = pd.read_csv(ROOT / "data" / "incoming" / "orders.csv")
    history = pd.read_csv(ROOT / "data" / "history" / "metrics_history.csv")
    contract = load_contract(ROOT / "contracts" / "orders_contract.yaml")
    issues = validate_dataframe(orders, contract)
    failed = failed_issues(issues)
    critical_failed = failed_issues(issues, min_severity="critical")
    pipeline_action = decide_action(issues)

    # REL-16: split off the individually-bad rows instead of gating the batch.
    # One duplicated order_id must not block 600 good rows, and must not reach
    # the mart either.
    # Seeds are filtered by scripts/sync_dbt_seeds.py so the guarantee holds no
    # matter which make target runs first; here we only report the split.
    _clean_orders, quarantined, quarantine_manifest = quarantine_rows(orders, contract)
    if not quarantined.empty:
        qdir = ROOT / "data" / "quarantine"
        qdir.mkdir(parents=True, exist_ok=True)
        quarantined.to_csv(qdir / "orders_quarantined.csv", index=False)

    # REL-05: hand the detector the full history plus the same-weekday segment
    # and let `auto` decide, instead of pre-segmenting on the caller side.
    current_dow = datetime.now().weekday()
    segment = history.loc[history["day_of_week"] == current_dow, "row_count"].tail(8).tolist()
    row_result = detect_anomaly(
        len(orders),
        history["row_count"].tail(28).tolist(),
        method="auto",
        context={
            "metric_name": "row_count",
            "day_of_week": current_dow,
            "same_segment_history": segment,
        },
    )

    updated = pd.to_datetime(orders["updated_at"], utc=True, errors="coerce")
    freshness_minutes = (
        pd.Timestamp(datetime.now(timezone.utc)) - updated.max()
    ).total_seconds() / 60.0

    docs = load_jsonl(ROOT / "data" / "incoming" / "kb_documents.jsonl")
    text_result = detect_text_length_shift(
        [d["content"] for d in docs], history["mean_text_length"].tail(14).tolist()
    )

    # The KB feeds the support agent, so it needs the same contract treatment as
    # orders. The starter validated orders only, which is why `stale_kb` slipped
    # through every layer.
    kb_contract = load_contract(ROOT / "contracts" / "kb_contract.yaml")
    kb_issues = validate_dataframe(pd.DataFrame(docs), kb_contract)
    kb_failed = failed_issues(kb_issues)
    kb_action = decide_action(kb_issues)

    # SLO over every check this run performed, not a single synthetic event.
    #
    # Bad events are *critical* failures only. An SLO is a promise about user
    # impact, and warnings are by definition things we chose not to page on -
    # letting them burn the budget at full weight means one stale KB warning
    # empties a 99.9% budget and the number stops meaning anything.
    # Warnings are tracked separately so they are still visible.
    all_issues = issues + kb_issues
    contract_slo = calculate_slo(
        0.999,
        bad_events=len(failed_issues(all_issues, min_severity="critical")),
        total_events=max(1, len(all_issues)),
    )
    warning_count = len(failed_issues(all_issues)) - len(
        failed_issues(all_issues, min_severity="critical")
    )

    with open(ROOT / "data" / "baseline" / "lineage_graph.json", "r", encoding="utf-8") as f:
        lineage = json.load(f)["dataset_lineage"]
    blast_radius = get_downstream_assets(lineage, "stg_orders")

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "orders_rows": int(len(orders)),
        "failed_contract_checks": len(failed),
        "critical_contract_failures": len(critical_failed),
        "pipeline_action": pipeline_action,
        "quarantine": quarantine_manifest,
        "contract_failures": failed,
        "row_count_anomaly": row_result,
        "freshness_minutes": freshness_minutes,
        "kb_text_length_signal": text_result,
        "kb_failed_contract_checks": len(kb_failed),
        "kb_pipeline_action": kb_action,
        "kb_contract_failures": kb_failed,
        "contract_slo": contract_slo,
        "warning_count": warning_count,
        "sample_blast_radius_from_stg_orders": blast_radius,
    }
    out = ROOT / "reports" / "latest_metrics.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print("=== DATA RELIABILITY BASELINE ===")
    print(f"orders rows              : {len(orders)}")
    print(f"contract failed checks   : {len(failed)}")
    print(f"critical contract fails  : {len(critical_failed)}")
    print(f"pipeline action          : {pipeline_action}")
    if quarantine_manifest["quarantined_rows"]:
        print(
            f"quarantined              : {quarantine_manifest['quarantined_rows']}"
            f"/{quarantine_manifest['total_rows']} rows"
            f" ({quarantine_manifest['quarantined_fraction']:.2%}) ->"
            f" data/quarantine/orders_quarantined.csv"
        )
        print(f"    rules: {', '.join(quarantine_manifest['rules_triggered'])}")
        print(f"    {quarantine_manifest['clean_rows']} clean rows promoted downstream")
    print(
        f"row-count anomaly        : {row_result['is_anomaly']} "
        f"({row_result['method']}, score={row_result['score']:.2f}, "
        f"{row_result.get('direction', '?')} vs {row_result.get('baseline', '?')})"
    )
    print(f"freshness minutes        : {freshness_minutes:.1f}")
    print(f"KB length anomaly        : {text_result['is_anomaly']}")
    print(f"KB contract failed       : {len(kb_failed)} (action: {kb_action})")
    for issue in kb_failed:
        print(f"    - [{issue['severity']}] {issue['check']} {issue['column']}: {issue['details'][:60]}")
    print(
        f"error budget remaining   : {contract_slo['remaining_error_budget_fraction']:.1%}"
        f" (burn_rate={contract_slo['burn_rate']:.1f}, "
        f"{contract_slo['bad_events']} critical / {contract_slo['total_events']} checks, "
        f"{warning_count} warning)"
    )
    print(f"sample blast radius      : {', '.join(blast_radius)}")
    print(f"report                    : {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
