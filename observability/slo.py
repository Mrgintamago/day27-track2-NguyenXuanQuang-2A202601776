"""SLI/SLO, error budget and burn-rate alerting.

Burn rate is what turns "2 checks failed" into "should this wake someone up?".
A burn rate of 1.0 means the budget is being consumed exactly as fast as it is
granted - it lasts the whole window. 4.0 means it will be gone in a quarter of
the window.

The multi-window policy follows the Google SRE Workbook: alert only when a
*short* and a *long* window both burn fast. The long window proves the problem
is real, the short window proves it is still happening. Either one alone is a
pager that people learn to ignore.
"""
from __future__ import annotations

from typing import Any

# Burn-rate thresholds from the SRE Workbook's multi-window table.
# 14.4 exhausts a 30-day budget in ~2 days; 6 in ~5 days; 1 is break-even.
BURN_FAST = 14.4
BURN_MEDIUM = 6.0
BURN_SLOW = 1.0


def calculate_slo(target: float, bad_events: int, total_events: int) -> dict[str, Any]:
    if not 0 < target < 1:
        raise ValueError("target must be between 0 and 1 (exclusive)")
    if bad_events < 0 or total_events < 0 or bad_events > total_events:
        raise ValueError("invalid event counts")

    allowed_bad_rate = 1.0 - target
    if total_events == 0:
        # No traffic is not the same as no errors, but it is definitely not a
        # breach: reporting a burn rate off zero events would be noise.
        return {
            "target": target,
            "actual_bad_rate": 0.0,
            "allowed_bad_rate": allowed_bad_rate,
            "burn_rate": 0.0,
            "remaining_error_budget_fraction": 1.0,
            "breached": False,
            "bad_events": 0,
            "total_events": 0,
        }

    actual_bad_rate = bad_events / total_events
    burn_rate = actual_bad_rate / allowed_bad_rate
    consumed_fraction = min(1.0, burn_rate)
    return {
        "target": target,
        "actual_bad_rate": actual_bad_rate,
        "allowed_bad_rate": allowed_bad_rate,
        "burn_rate": burn_rate,
        "remaining_error_budget_fraction": max(0.0, 1.0 - consumed_fraction),
        "breached": bool(actual_bad_rate > allowed_bad_rate),
        "bad_events": int(bad_events),
        "total_events": int(total_events),
    }


def evaluate_multiwindow_burn(
    *,
    short_window_burn: float,
    long_window_burn: float,
    policy: str = "sre_workbook",
    fast_threshold: float = BURN_FAST,
    medium_threshold: float = BURN_MEDIUM,
) -> dict[str, Any]:
    """Decide page / ticket / none from two burn-rate windows.

    The rule that does the real work is the AND: a page requires *both*
    windows over threshold.

    - short high, long low  -> a transient spike that already recovered.
      Paging here is how a rota gets trained to ignore the pager.
    - short low, long high  -> the incident is over; the budget damage is
      already done. That is a ticket to work in hours, not a 3am page.
    - both high             -> sustained fast burn. Page.
    """
    short = float(short_window_burn)
    long = float(long_window_burn)
    both_over = lambda t: short >= t and long >= t  # noqa: E731

    if both_over(fast_threshold):
        page, severity = True, "critical"
        reason = (
            f"sustained fast burn: short={short:.2f} and long={long:.2f} both >= "
            f"{fast_threshold}; error budget exhausts in hours"
        )
    elif both_over(medium_threshold):
        page, severity = True, "high"
        reason = (
            f"sustained elevated burn: short={short:.2f} and long={long:.2f} both >= "
            f"{medium_threshold}"
        )
    elif long >= BURN_SLOW and short >= BURN_SLOW:
        page, severity = False, "warning"
        reason = (
            f"slow burn: short={short:.2f}, long={long:.2f} - budget is eroding "
            f"but not fast enough to page; open a ticket"
        )
    elif short >= medium_threshold:
        page, severity = False, "info"
        reason = (
            f"transient spike: short={short:.2f} is high but long={long:.2f} is not - "
            f"not sustained, do not page"
        )
    elif long >= medium_threshold:
        page, severity = False, "warning"
        reason = (
            f"burn already stopped: long={long:.2f} carries past damage but "
            f"short={short:.2f} is back to normal - ticket, not a page"
        )
    else:
        page, severity = False, "none"
        reason = f"within budget: short={short:.2f}, long={long:.2f}"

    return {
        "page": bool(page),
        "severity": severity,
        "reason": reason,
        "short_window_burn": short,
        "long_window_burn": long,
        "policy": policy,
        "thresholds": {"fast": fast_threshold, "medium": medium_threshold, "slow": BURN_SLOW},
        "action": "page" if page else ("ticket" if severity in {"warning"} else "none"),
    }
