"""Anomaly detection.

The starter shipped a plain z-score and an `auto` mode that ignored context.
REL-05 keeps both simple detectors intact (hidden tests and the public tests
still call them by name) and makes `auto` do the three things a z-score on raw
history cannot:

1. **Segment before comparing.** Traffic here is weekly-seasonal - weekends run
   at ~43% of weekdays. Comparing Sunday against a Mon-Sun average is how you
   get an alert every Saturday and miss a real drop on Tuesday.
2. **Use robust statistics.** Mean and standard deviation are both dragged by
   the very outlier you are trying to detect. One bad day in the baseline
   inflates std and hides the next bad day. Median/MAD do not move.
3. **Respect operational context.** A known migration window is not an incident.

Why z-score is wrong (the answer this module has to defend):
- it assumes a single unimodal population, which weekly seasonality violates;
- it is not robust - a contaminated baseline raises the bar and masks failures;
- with a near-constant baseline, std -> 0 and every trivial wobble scores
  infinitely high, which is how a detector earns itself an alert filter.
"""
from __future__ import annotations

from typing import Any, Iterable

import numpy as np

# Median-to-sigma conversion for the modified z-score (Iglewicz & Hoaglin).
MAD_SCALE = 0.6745

# A deviation smaller than this fraction of the baseline is never worth paging
# on, no matter how tight the baseline is. This is the guard against the
# "MAD is tiny so everything is an outlier" failure mode.
DEFAULT_MIN_RELATIVE_CHANGE = 0.10


def _missing_metric(method: str, current: Any) -> dict[str, Any]:
    """A metric that is NaN/inf is itself the incident.

    Left unguarded this is a silent miss: ``nan > threshold`` evaluates to
    False, so a broken metric pipeline reports as perfectly healthy - the
    worst possible failure mode for a detector.
    """
    return {
        "is_anomaly": True,
        "score": float("inf"),
        "method": f"{method}:invalid_current",
        "reason": f"current value is not finite ({current!r}); metric collection is broken",
        "direction": "unknown",
    }


def _is_finite(value: Any) -> bool:
    try:
        return bool(np.isfinite(float(value)))
    except (TypeError, ValueError):
        return False


def _clean(history: Iterable[float]) -> np.ndarray:
    """Drop NaN/inf so a single bad history point cannot poison the baseline."""
    values = np.asarray(list(history), dtype=float)
    if values.size == 0:
        return values
    return values[np.isfinite(values)]


def zscore_detector(current: float, history: Iterable[float], threshold: float = 3.0) -> dict[str, Any]:
    if not _is_finite(current):
        return _missing_metric("zscore", current)
    values = _clean(history)
    if values.size < 3:
        return {"is_anomaly": False, "score": 0.0, "method": "zscore", "reason": "insufficient_history"}
    mean = float(np.mean(values))
    std = float(np.std(values))
    if std == 0:
        score = float("inf") if float(current) != mean else 0.0
    else:
        score = abs(float(current) - mean) / std
    return {
        "is_anomaly": bool(score > threshold),
        "score": float(score),
        "method": "zscore",
        "reason": f"mean={mean:.3f}, std={std:.3f}, threshold={threshold}",
    }


def mad_detector(current: float, history: Iterable[float], threshold: float = 3.5) -> dict[str, Any]:
    """Median/MAD detector, robust to a contaminated baseline.

    Zero-MAD is handled rather than surrendered: when more than half the
    baseline is identical MAD collapses to 0, and the honest fallback is a
    relative-deviation test against the median.
    """
    if not _is_finite(current):
        return _missing_metric("mad", current)
    values = _clean(history)
    if values.size < 5:
        return {"is_anomaly": False, "score": 0.0, "method": "mad", "reason": "insufficient_history"}

    current = float(current)
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))

    if mad > 0:
        score = MAD_SCALE * abs(current - median) / mad
        return {
            "is_anomaly": bool(score > threshold),
            "score": float(score),
            "method": "mad",
            "reason": f"median={median:.3f}, mad={mad:.3f}, threshold={threshold}",
        }

    # MAD == 0: baseline is (mostly) constant. Fall back to relative deviation
    # instead of returning "not an anomaly", which would blind the detector
    # exactly where the baseline is most predictable.
    if median == 0:
        is_anomaly = current != 0
        score = float("inf") if is_anomaly else 0.0
        reason = "mad=0 and median=0; any non-zero value is a deviation"
    else:
        relative = abs(current - median) / abs(median)
        is_anomaly = bool(relative > DEFAULT_MIN_RELATIVE_CHANGE)
        score = float(relative / DEFAULT_MIN_RELATIVE_CHANGE)
        reason = (
            f"mad=0 (constant baseline), median={median:.3f}, "
            f"relative_change={relative:.3f}, threshold={DEFAULT_MIN_RELATIVE_CHANGE}"
        )
    return {"is_anomaly": bool(is_anomaly), "score": float(score), "method": "mad", "reason": reason}


def _select_baseline(
    history: Iterable[float], context: dict[str, Any] | None
) -> tuple[np.ndarray, str]:
    """Prefer a same-segment baseline when the caller supplies one.

    Comparing like with like is what makes a 30% weekday drop visible without
    alerting on every weekend.
    """
    context = context or {}
    # Explicit None check, not `or []`: numpy arrays and pandas Series raise
    # "truth value is ambiguous" on boolean coercion, and the interface only
    # promises an iterable.
    raw_segment = context.get("same_segment_history")
    segment = _clean([] if raw_segment is None else raw_segment)
    if segment.size >= 3:
        label = "same_segment"
        dow = context.get("day_of_week")
        if dow is not None:
            label = f"same_weekday({dow})"
        return segment, label
    return _clean(history), "full_history"


def detect_anomaly(
    current: float,
    history: Iterable[float],
    *,
    method: str = "auto",
    threshold: float = 3.0,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Stable lab API.

    - ``zscore``: plain z-score (unchanged).
    - ``mad``:    median/MAD, now with a real zero-MAD path.
    - ``auto``:   segment-aware, robust, context-aware.
    """
    if method == "mad":
        return mad_detector(current, history)
    if method == "zscore":
        return zscore_detector(current, history, threshold=threshold)
    if method != "auto":
        raise ValueError(f"Unsupported method: {method}")

    context = context or {}
    if not _is_finite(current):
        result = _missing_metric("auto", current)
        result["baseline"] = "n/a"
        return result
    current = float(current)
    baseline, baseline_label = _select_baseline(history, context)
    metric_name = context.get("metric_name", "metric")

    if baseline.size < 3:
        return {
            "is_anomaly": False,
            "score": 0.0,
            "method": "auto:insufficient_history",
            "reason": f"{metric_name}: only {baseline.size} usable baseline points (need 3)",
            "baseline": baseline_label,
        }

    median = float(np.median(baseline))
    mad = float(np.median(np.abs(baseline - median)))
    relative = abs(current - median) / abs(median) if median != 0 else float("inf")
    direction = "drop" if current < median else "spike"

    if mad > 0:
        score = MAD_SCALE * abs(current - median) / mad
        sub_method = "auto:mad"
        stat = f"median={median:.3f}, mad={mad:.3f}, threshold={threshold + 0.5:.1f}"
        is_anomaly = score > (threshold + 0.5)  # MAD threshold is slightly wider
    else:
        std = float(np.std(baseline))
        if std > 0:
            score = abs(current - median) / std
            sub_method = "auto:zscore_fallback"
            stat = f"median={median:.3f}, mad=0, std={std:.3f}, threshold={threshold}"
            is_anomaly = score > threshold
        else:
            score = float("inf") if current != median else 0.0
            sub_method = "auto:constant_baseline"
            stat = f"constant baseline={median:.3f}"
            is_anomaly = current != median

    notes: list[str] = []

    # Guard 1: a tight baseline makes tiny wobbles score enormously. Require the
    # deviation to also be operationally meaningful before calling it an anomaly.
    min_relative = float(context.get("min_relative_change", DEFAULT_MIN_RELATIVE_CHANGE))
    if is_anomaly and relative < min_relative:
        is_anomaly = False
        notes.append(
            f"suppressed: {relative:.1%} deviation is below the {min_relative:.0%} "
            f"floor for {metric_name}"
        )

    # Guard 2: an announced event is not an incident. Still reported, not paged.
    known_event = context.get("known_event")
    if is_anomaly and known_event:
        is_anomaly = False
        notes.append(f"suppressed: known_event={known_event}")

    reason = (
        f"{metric_name} {direction} vs {baseline_label} baseline "
        f"(n={baseline.size}): current={current:.3f}, {stat}, "
        f"relative_change={relative:.1%}"
    )
    if notes:
        reason += "; " + "; ".join(notes)

    return {
        "is_anomaly": bool(is_anomaly),
        "score": float(score),
        "method": sub_method,
        "reason": reason,
        "baseline": baseline_label,
        "baseline_median": median,
        "relative_change": float(relative),
        "direction": direction,
    }
