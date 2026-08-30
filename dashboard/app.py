"""Incident dashboard.

Built around one question - "do I need to do something right now?" - so the
layout goes: routed decision first, then error budget, then the evidence that
justifies it. Anything that does not change a decision is below the fold.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "latest_metrics.json"
GX_REPORT = ROOT / "reports" / "gx_validation_result.json"
HISTORY = ROOT / "data" / "history" / "metrics_history.csv"
QUARANTINE = ROOT / "data" / "quarantine" / "orders_quarantined.csv"

OWNERS = {"orders": "commerce-data", "kb_documents": "support-ai"}
RUNBOOK = "docs/LAB_GUIDE.md#phase-6--mystery-incident"

ACTION_STYLE = {
    "block": ("🔴", "Pipeline blocked - bad data is not being promoted"),
    "quarantine": ("🟠", "Bad rows parked, clean rows promoted"),
    "warn": ("🟡", "Reported, not blocking"),
    "allow": ("🟢", "All contract checks passed"),
}

st.set_page_config(page_title="Data Reliability Lab", layout="wide")
st.title("Data Reliability - Incident View")

if not REPORT.exists():
    st.warning("Run `make baseline` first to generate reports/latest_metrics.json")
    st.stop()

report = json.loads(REPORT.read_text(encoding="utf-8"))
slo = report["contract_slo"]
anomaly = report["row_count_anomaly"]
quarantine = report.get("quarantine", {})

# ---------------------------------------------------------------- decision
action = report.get("pipeline_action", "allow")
icon, blurb = ACTION_STYLE.get(action, ("⚪", ""))
st.subheader(f"{icon} Pipeline decision: `{action}`  -  {blurb}")

c1, c2, c3, c4 = st.columns(4)
c1.metric(
    "Error budget left",
    f"{slo['remaining_error_budget_fraction']:.0%}",
    delta=f"burn {slo['burn_rate']:.1f}x",
    delta_color="inverse",
)
c2.metric("SLO target", f"{slo['target']:.1%}", f"{slo['bad_events']}/{slo['total_events']} critical")
c3.metric("Freshness", f"{report['freshness_minutes']:.1f} min")
c4.metric(
    "Quarantined rows",
    quarantine.get("quarantined_rows", 0),
    delta=f"{quarantine.get('quarantined_fraction', 0):.2%} of batch" if quarantine.get("quarantined_rows") else None,
    delta_color="inverse",
)

# ------------------------------------------------------------- burn windows
st.subheader("Burn-rate windows")
st.caption(
    "A page requires BOTH windows over threshold: the long window proves the problem is "
    "real, the short window proves it is still happening. Thresholds 14.4 / 6.0 / 1.0 "
    "(SRE Workbook)."
)
burn = slo["burn_rate"]
bc1, bc2 = st.columns(2)
bc1.metric("Short window (this run)", f"{burn:.1f}x")
bc2.metric("Long window", "n/a", help="Needs a burn-rate history store; single-run lab.")
if burn >= 14.4:
    st.error("Short-window burn is in fast-burn territory. Confirm the long window before paging.")
elif burn >= 1.0:
    st.warning("Budget is eroding. Ticket, not a page, unless the long window agrees.")

# ---------------------------------------------------------------- failures
left, right = st.columns(2)
with left:
    st.subheader("Contract failures - orders")
    failures = report.get("contract_failures", [])
    if failures:
        st.dataframe(pd.DataFrame(failures), width="stretch", hide_index=True)
    else:
        st.success("No contract failures.")
with right:
    st.subheader("Contract failures - knowledge base")
    kb_failures = report.get("kb_contract_failures", [])
    if kb_failures:
        st.dataframe(pd.DataFrame(kb_failures), width="stretch", hide_index=True)
    else:
        st.success("No KB contract failures.")

if GX_REPORT.exists():
    gx = json.loads(GX_REPORT.read_text(encoding="utf-8"))
    st.caption(
        f"Great Expectations checkpoint: {gx['expectations_evaluated'] - gx['failed_expectations']}"
        f"/{gx['expectations_evaluated']} passed, routed `{gx['routed_action']}`"
    )

# ---------------------------------------------------------------- anomaly
st.subheader("Row-count anomaly")
a1, a2, a3 = st.columns(3)
a1.metric("Verdict", "ANOMALY" if anomaly["is_anomaly"] else "ok")
a2.metric("Direction", anomaly.get("direction", "?"))
a3.metric("Score", f"{anomaly['score']:.2f}", anomaly["method"])
st.caption(anomaly["reason"])

history = pd.read_csv(HISTORY)
history["segment"] = history["day_of_week"].map(lambda d: "weekend" if d >= 5 else "weekday")
st.line_chart(
    history.pivot_table(index="date", columns="segment", values="row_count"),
    height=220,
)
st.caption(
    "Weekday and weekend plotted separately: they are different populations. "
    "Comparing across them is what makes a detector alert every Saturday."
)

# ---------------------------------------------------------------- quarantine
if QUARANTINE.exists() and quarantine.get("quarantined_rows"):
    st.subheader("Quarantined rows")
    st.caption(f"Rules triggered: {', '.join(quarantine.get('rules_triggered', []))}")
    st.dataframe(pd.read_csv(QUARANTINE).head(50), width="stretch", hide_index=True)

# ---------------------------------------------------------------- blast radius
st.subheader("Blast radius")
st.code("stg_orders -> " + " -> ".join(report["sample_blast_radius_from_stg_orders"]))

# ---------------------------------------------------------------- ownership
st.subheader("Ownership & runbook")
st.table(
    pd.DataFrame(
        [
            {"dataset": "orders", "owner": OWNERS["orders"], "runbook": RUNBOOK,
             "status": action},
            {"dataset": "kb_documents", "owner": OWNERS["kb_documents"], "runbook": RUNBOOK,
             "status": report.get("kb_pipeline_action", "allow")},
        ]
    )
)
st.caption(f"Report generated at {report['timestamp']}")
