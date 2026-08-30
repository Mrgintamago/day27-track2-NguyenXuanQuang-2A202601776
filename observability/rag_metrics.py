"""RAG / knowledge-base drift signals.

The support agent is a data consumer like any other, but its failure mode is
quieter: nothing errors, the answers just get worse. These are cheap proxies
that need no model download.

- **text length shift**: catches truncated ingests, a changed chunker, a
  scraper that started returning boilerplate.
- **embedding norm shift**: catches an embedding-space change - a swapped or
  re-versioned model, a different normalisation, a language switch. Norms are
  precomputed upstream so no model is needed here.
"""
from __future__ import annotations

from typing import Any, Iterable

import numpy as np

from observability.anomaly import detect_anomaly, zscore_detector
from observability.distribution import detect_distribution_shift


def approximate_token_lengths(texts: Iterable[str]) -> list[int]:
    # Deliberately simple proxy; no tokenizer/model download needed.
    return [len(str(t).split()) for t in texts]


def detect_text_length_shift(
    current_texts: Iterable[str],
    baseline_batch_means: Iterable[float],
    *,
    threshold: float = 3.0,
) -> dict[str, Any]:
    lengths = approximate_token_lengths(current_texts)
    current_mean = float(np.mean(lengths)) if lengths else 0.0
    if not lengths:
        return {
            "is_anomaly": True,
            "score": float("inf"),
            "method": "empty_batch",
            "reason": "no documents in batch - the KB feed produced nothing",
            "metric": "mean_text_length",
            "current_mean": 0.0,
        }
    result = zscore_detector(current_mean, baseline_batch_means, threshold=threshold)
    # Keep the z-score verdict, but let the robust detector override it: a
    # single bad KB batch in the baseline is enough to hide the next one.
    robust = detect_anomaly(
        current_mean,
        baseline_batch_means,
        method="auto",
        context={"metric_name": "mean_text_length"},
    )
    result["is_anomaly"] = bool(result["is_anomaly"] or robust["is_anomaly"])
    result["method"] = f"zscore+{robust['method']}"
    result["reason"] = f"{result['reason']}; robust: {robust['reason']}"
    result["metric"] = "mean_text_length"
    result["current_mean"] = current_mean
    return result


def detect_embedding_norm_shift(
    current_norms: Iterable[float], baseline_norms: Iterable[float]
) -> dict[str, Any]:
    """Embedding-space drift from precomputed vector norms.

    A distribution test rather than a mean test on purpose. A model swap
    typically keeps the average norm close while changing the spread - exactly
    the shape change a mean comparison cannot see.
    """
    cur = np.asarray(list(current_norms), dtype=float)
    base = np.asarray(list(baseline_norms), dtype=float)
    cur = cur[np.isfinite(cur)] if cur.size else cur
    base = base[np.isfinite(base)] if base.size else base

    if cur.size == 0 or base.size == 0:
        return {
            "is_anomaly": False,
            "score": 0.0,
            "method": "embedding_norm",
            "reason": "empty_input",
            "metric": "embedding_norm",
        }

    dist = detect_distribution_shift(cur, base)
    # Norms are near 1.0 for a normalised model; a mean move is itself a strong
    # signal, so keep it alongside the distribution test.
    level = detect_anomaly(
        float(np.mean(cur)), base, method="auto", context={"metric_name": "embedding_norm"}
    )
    is_anomaly = bool(dist["is_anomaly"] or level["is_anomaly"])
    return {
        "is_anomaly": is_anomaly,
        "score": float(max(dist["score"], min(level["score"], 1e6))),
        "method": "embedding_norm:psi+ks+robust_level",
        "reason": (
            f"current_mean={float(np.mean(cur)):.4f}, baseline_mean={float(np.mean(base)):.4f}, "
            f"psi={dist['psi']:.3f}, ks={dist['ks']:.3f}; level: {level['reason']}"
        ),
        "metric": "embedding_norm",
        "psi": dist["psi"],
        "ks": dist["ks"],
    }
