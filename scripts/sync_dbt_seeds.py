#!/usr/bin/env python3
"""Sync incoming CSVs into dbt seeds, enforcing contract quarantine on the way.

The original version was a plain copy, which quietly defeated quarantine:
`make baseline` would park the bad rows, then `make dbt` would copy the raw
incoming file straight over the clean partition and rebuild the mart from the
dirty data. Quarantine that depends on the order you happen to run two make
targets in is not quarantine.

Enforcing the split here makes the guarantee unconditional: whatever reaches
dbt seeds has already had its block/quarantine-level rule violations removed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.contract_validator import load_contract, quarantine_rows

INCOMING = ROOT / "data" / "incoming"
SEEDS = ROOT / "dbt_project" / "seeds"
QUARANTINE = ROOT / "data" / "quarantine"

# Datasets that have a contract get filtered; the rest are copied as-is.
CONTRACTS = {"orders.csv": ROOT / "contracts" / "orders_contract.yaml"}


def main() -> None:
    SEEDS.mkdir(parents=True, exist_ok=True)

    for name in ["orders.csv", "customers.csv"]:
        df = pd.read_csv(INCOMING / name)
        contract_path = CONTRACTS.get(name)

        if contract_path is None:
            df.to_csv(SEEDS / name, index=False)
            print(f"{name}: {len(df)} rows (no contract, copied as-is)")
            continue

        clean, quarantined, manifest = quarantine_rows(df, load_contract(contract_path))
        clean.to_csv(SEEDS / name, index=False)

        if not quarantined.empty:
            QUARANTINE.mkdir(parents=True, exist_ok=True)
            stem = Path(name).stem
            quarantined.to_csv(QUARANTINE / f"{stem}_quarantined.csv", index=False)
            (QUARANTINE / f"{stem}_manifest.json").write_text(
                json.dumps(manifest, indent=2, default=str), encoding="utf-8"
            )
            print(
                f"{name}: {manifest['clean_rows']}/{manifest['total_rows']} rows promoted, "
                f"{manifest['quarantined_rows']} quarantined "
                f"({', '.join(manifest['rules_triggered'])})"
            )
        else:
            print(f"{name}: {len(clean)} rows, nothing quarantined")


if __name__ == "__main__":
    main()
