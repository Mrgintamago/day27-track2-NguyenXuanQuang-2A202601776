#!/usr/bin/env python3
"""Great Expectations Core 1.21 validation flow for the orders dataset.

REL-02 upgrade: the starter validated four loose expectations one by one.
This builds the full documented flow instead —

    ExpectationSuite -> ValidationDefinition -> Checkpoint -> Actions

Two design decisions worth defending:

1. The suite is **generated from ``contracts/orders_contract.yaml``**, not
   hand-written. A contract and a GX suite that drift apart is how a pipeline
   ends up green while the data is wrong; here there is one source of truth.
2. Severity is carried into a routing **Action**. GX only tells you
   pass/fail; the operational question is "block, quarantine, or just warn?",
   which is what ``SeverityRoutingAction`` answers and persists to
   ``reports/gx_validation_result.json``.

Exit code is 1 when the routed decision is ``block`` so ``make gx`` can gate a
pipeline instead of merely printing.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import great_expectations as gx
    from great_expectations.checkpoint.actions import ValidationAction
    from great_expectations.data_context.types.base import ProgressBarsConfig
except ImportError as exc:  # friendlier classroom failure
    raise SystemExit("great_expectations is not installed. Run: pip install -r requirements.txt") from exc

from src.contract_validator import DEFAULT_ACTION, SEVERITY_ORDER, load_contract

RESULT_PATH = ROOT / "reports" / "gx_validation_result.json"

# Declared contract type -> pandas dtypes GX should accept for that column.
TYPE_LIST = {
    "integer": ["int64", "int32", "Int64", "Int32"],
    "number": ["float64", "float32", "int64", "int32", "Float64", "Int64"],
}


class SeverityRoutingAction(ValidationAction):
    """Turn a GX result into an operational decision.

    GX answers "did it pass?". On-call needs "what do I do?". This action maps
    every failed expectation back to its contract severity and collapses them
    into one routed action: block > quarantine > warn > allow.
    """

    type: Literal["severity_routing"] = "severity_routing"
    name: str = "severity_routing"
    output_path: str = str(RESULT_PATH)

    def run(self, checkpoint_result, action_context=None) -> dict:
        failures: list[dict[str, Any]] = []
        total = 0

        for validation_result in checkpoint_result.run_results.values():
            for result in validation_result.results:
                total += 1
                if result.success:
                    continue
                config = result.expectation_config
                meta = dict(config.meta or {})
                severity = meta.get("severity", "warning")
                failures.append(
                    {
                        "expectation": config.type,
                        "column": config.kwargs.get("column"),
                        "severity": severity,
                        "action": meta.get("action", DEFAULT_ACTION.get(severity, "warn")),
                        "unexpected_count": (result.result or {}).get("unexpected_count"),
                        "observed": (result.result or {}).get("observed_value"),
                    }
                )

        routed = "allow"
        for candidate in ("block", "quarantine", "warn"):
            if any(f["action"] == candidate for f in failures):
                routed = candidate
                break

        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": bool(checkpoint_result.success),
            "expectations_evaluated": total,
            "failed_expectations": len(failures),
            "critical_failures": sum(1 for f in failures if f["severity"] == "critical"),
            "routed_action": routed,
            "failures": sorted(
                failures,
                key=lambda f: -SEVERITY_ORDER.get(f["severity"], 1),
            ),
        }
        out = Path(self.output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return payload


def build_expectations(contract: dict[str, Any]) -> list[Any]:
    """Compile the YAML contract into GX expectations, severity preserved."""
    expectations: list[Any] = [
        # Table-level: an empty batch is a silent outage, not a pass.
        gx.expectations.ExpectTableRowCountToBeBetween(
            min_value=1, severity="critical", meta={"severity": "critical"}
        )
    ]

    for column, rules in (contract.get("columns") or {}).items():
        rules = rules or {}
        severity = rules.get("severity", "warning")
        # meta carries severity through GX into the routing action; GX's own
        # ``severity`` kwarg does not survive into expectation_config.meta.
        meta = {"severity": severity, "action": DEFAULT_ACTION.get(severity, "warn")}
        common = {"column": column, "severity": severity, "meta": meta}

        expectations.append(gx.expectations.ExpectColumnToExist(**common))

        if rules.get("required"):
            expectations.append(gx.expectations.ExpectColumnValuesToNotBeNull(**common))

        if rules.get("unique"):
            expectations.append(gx.expectations.ExpectColumnValuesToBeUnique(**common))

        if rules.get("accepted_values") is not None:
            expectations.append(
                gx.expectations.ExpectColumnValuesToBeInSet(
                    value_set=list(rules["accepted_values"]), **common
                )
            )

        if "min" in rules or "max" in rules:
            expectations.append(
                gx.expectations.ExpectColumnValuesToBeBetween(
                    min_value=rules.get("min"), max_value=rules.get("max"), **common
                )
            )

        type_list = TYPE_LIST.get(str(rules.get("type", "")).lower())
        if type_list:
            expectations.append(
                gx.expectations.ExpectColumnValuesToBeInTypeList(
                    type_list=type_list, **common
                )
            )

    return expectations


def main() -> None:
    df = pd.read_csv(ROOT / "data" / "incoming" / "orders.csv")
    contract = load_contract(ROOT / "contracts" / "orders_contract.yaml")

    context = gx.get_context()
    # The per-metric tqdm bar drowns the actual verdict in `make gx` / CI logs.
    # GX_PROGRESS_BARS=1 brings it back when debugging a slow suite.
    if os.environ.get("GX_PROGRESS_BARS") != "1":
        context.variables.progress_bars = ProgressBarsConfig(globally=False)

    data_source = context.data_sources.add_pandas("orders_pandas")
    asset = data_source.add_dataframe_asset(name="orders_dataframe")
    batch_definition = asset.add_batch_definition_whole_dataframe("whole_orders")

    suite = context.suites.add(
        gx.ExpectationSuite(
            name="orders_contract_suite",
            expectations=build_expectations(contract),
            meta={"contract": contract.get("dataset"), "owner": contract.get("owner")},
        )
    )

    validation_definition = context.validation_definitions.add(
        gx.ValidationDefinition(
            name="orders_contract_validation",
            data=batch_definition,
            suite=suite,
        )
    )

    checkpoint = context.checkpoints.add(
        gx.Checkpoint(
            name="orders_contract_checkpoint",
            validation_definitions=[validation_definition],
            actions=[SeverityRoutingAction()],
            result_format="SUMMARY",
        )
    )

    checkpoint_result = checkpoint.run(batch_parameters={"dataframe": df})
    summary = json.loads(RESULT_PATH.read_text(encoding="utf-8"))

    print("=== GX CHECKPOINT: orders_contract_checkpoint ===")
    print(f"suite               : {suite.name} ({len(suite.expectations)} expectations)")
    print(f"rows validated      : {len(df)}")
    print(f"expectations passed : {summary['expectations_evaluated'] - summary['failed_expectations']}"
          f"/{summary['expectations_evaluated']}")
    print(f"critical failures   : {summary['critical_failures']}")
    print(f"routed action       : {summary['routed_action']}")
    print(f"result written      : {RESULT_PATH.relative_to(ROOT)}")

    if summary["failures"]:
        print("\nfailed expectations:")
        for f in summary["failures"]:
            print(
                f"  [{f['severity']:8}] {f['expectation']:38} {str(f['column']):12}"
                f" action={f['action']:10} unexpected={f['unexpected_count']}"
            )

    print("\nGX result:", "PASS" if checkpoint_result.success else "FAIL")
    if summary["routed_action"] == "block":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
