"""Distribution drift detection.

The starter compared means. That misses the failure mode that matters most in
practice: a distribution whose *shape* changes while its mean does not. A
pricing bug that splits orders into cheap-and-expensive buckets, a locale
change that bimodalises text length, a truncated ingest that keeps the average
intact - mean ratio scores all of them 1.0 and reports "healthy".

REL-06 uses two complementary signals and takes the stronger one:

- **PSI** (Population Stability Index) over baseline quantile bins. Standard
  practice in credit/ML monitoring: <0.10 stable, 0.10-0.25 moderate shift,
  >0.25 significant shift. It sees mass moving between bins even when the mean
  is unchanged.
- **KS statistic**: the largest gap between the two empirical CDFs. Cheap,
  non-parametric, and sensitive to shifts anywhere in the distribution.

Mean ratio is kept and still reported, because it stays the most legible number
for a human doing triage.
"""
from __future__ import annotations

from typing import Any, Iterable

import numpy as np

PSI_BINS = 10
PSI_MODERATE = 0.10
PSI_SIGNIFICANT = 0.25
KS_THRESHOLD = 0.30
# PSI alone is not allowed to fire: on low-cardinality or small samples it is
# noisy, so it must be corroborated by the CDFs actually having moved.
KS_CORROBORATION = 0.15
# Minimum samples we want behind each PSI bin. Fewer than this and the bin is
# noise, not signal.
MIN_SAMPLES_PER_BIN = 5


def _clean(values: Iterable[float]) -> np.ndarray:
    arr = np.asarray(list(values), dtype=float)
    if arr.size == 0:
        return arr
    return arr[np.isfinite(arr)]


def population_stability_index(current: np.ndarray, baseline: np.ndarray, bins: int = PSI_BINS) -> float:
    """PSI over baseline quantile bins (equal-frequency, not equal-width).

    Two details decide whether PSI is usable or a false-positive generator:

    - **Quantile bins, not equal-width.** Equal-width bins on a skewed metric
      put nearly all mass in one bucket and PSI stops discriminating.
    - **Bin count adapted to the data, and a sample-size-aware floor.** PSI's
      term ``(c-b)*log(c/b)`` explodes when a bin is empty on one side. With a
      fixed tiny epsilon (1e-6) and low-cardinality data, an empty bin alone
      scores PSI in the thousands - two near-identical discrete samples get
      flagged as a significant shift. The floor is therefore a half-count
      continuity correction, ``1/(2n)``, and bin count is capped by the number
      of distinct baseline values and by MIN_SAMPLES_PER_BIN.
    """
    n = int(min(current.size, baseline.size))
    distinct = int(np.unique(baseline).size)
    bins = max(2, min(bins, distinct, n // MIN_SAMPLES_PER_BIN))

    quantiles = np.linspace(0, 100, bins + 1)
    edges = np.unique(np.percentile(baseline, quantiles))
    if edges.size < 2:
        # Constant baseline: PSI is undefined, fall back to "did it move at all".
        return 0.0 if np.allclose(current, baseline[0]) else float("inf")
    edges[0], edges[-1] = -np.inf, np.inf

    base_pct = np.histogram(baseline, bins=edges)[0] / baseline.size
    cur_pct = np.histogram(current, bins=edges)[0] / current.size

    floor = 1.0 / (2.0 * max(n, 1))
    base_pct = np.clip(base_pct, floor, None)
    cur_pct = np.clip(cur_pct, floor, None)
    base_pct /= base_pct.sum()
    cur_pct /= cur_pct.sum()
    return float(np.sum((cur_pct - base_pct) * np.log(cur_pct / base_pct)))


def ks_statistic(current: np.ndarray, baseline: np.ndarray) -> float:
    """Two-sample Kolmogorov-Smirnov statistic: max distance between CDFs."""
    grid = np.sort(np.concatenate([current, baseline]))
    cdf_cur = np.searchsorted(np.sort(current), grid, side="right") / current.size
    cdf_base = np.searchsorted(np.sort(baseline), grid, side="right") / baseline.size
    return float(np.max(np.abs(cdf_cur - cdf_base)))


def detect_distribution_shift(
    current_values: Iterable[float],
    baseline_values: Iterable[float],
    *,
    ratio_threshold: float = 3.0,
    psi_threshold: float = PSI_SIGNIFICANT,
    ks_threshold: float = KS_THRESHOLD,
) -> dict[str, Any]:
    cur = _clean(current_values)
    base = _clean(baseline_values)
    if cur.size == 0 or base.size == 0:
        return {
            "is_anomaly": False,
            "score": 0.0,
            "method": "psi+ks",
            "reason": "empty_input",
            "psi": 0.0,
            "ks": 0.0,
        }

    cur_mean = float(np.mean(cur))
    base_mean = float(np.mean(base))
    if base_mean == 0:
        mean_ratio = float("inf") if cur_mean != 0 else 1.0
    elif cur_mean == 0:
        mean_ratio = float("inf")
    else:
        mean_ratio = max(abs(cur_mean / base_mean), abs(base_mean / cur_mean))

    psi = population_stability_index(cur, base)
    ks = ks_statistic(cur, base)
    triggered_note = ""

    # Firing rule. KS is the trustworthy standalone signal - it is bounded,
    # non-parametric and stable at small n. PSI is more sensitive to a shape
    # change but noisy on discrete or small samples, so it only fires with
    # corroboration that the CDFs genuinely separated. Measured case: two
    # near-identical discrete samples (n=32, 7 distinct values) score
    # PSI=0.32 - above the 0.25 "significant shift" rule of thumb - while
    # KS=0.10 correctly says nothing moved.
    triggered = []
    if ks >= ks_threshold:
        triggered.append(f"KS={ks:.3f}>={ks_threshold}")
    if psi >= psi_threshold and ks >= KS_CORROBORATION:
        triggered.append(f"PSI={psi:.3f}>={psi_threshold} (KS={ks:.3f} corroborates)")
    elif psi >= psi_threshold:
        triggered_note = f"PSI={psi:.3f} high but KS={ks:.3f} does not corroborate; not firing"
    if mean_ratio >= ratio_threshold:
        triggered.append(f"mean_ratio={mean_ratio:.2f}>={ratio_threshold}")

    # Normalise each signal against its own threshold so the score is
    # comparable across detectors: >=1.0 means "this signal fired".
    score = max(
        psi / psi_threshold if psi_threshold and ks >= KS_CORROBORATION else 0.0,
        ks / ks_threshold if ks_threshold else 0.0,
        mean_ratio / ratio_threshold if ratio_threshold else 0.0,
    )

    severity = "stable"
    if psi >= PSI_SIGNIFICANT:
        severity = "significant_shift"
    elif psi >= PSI_MODERATE:
        severity = "moderate_shift"

    return {
        "is_anomaly": bool(triggered),
        "score": float(score),
        "method": "psi+ks",
        "reason": (
            f"baseline_mean={base_mean:.3f}, current_mean={cur_mean:.3f}, "
            f"psi={psi:.3f} ({severity}), ks={ks:.3f}"
            + (
                "; triggered: " + ", ".join(triggered)
                if triggered
                else "; " + (triggered_note if psi >= psi_threshold else "no signal fired")
            )
        ),
        "psi": float(psi),
        "ks": float(ks),
        "mean_ratio": float(mean_ratio),
        "severity": severity,
    }
