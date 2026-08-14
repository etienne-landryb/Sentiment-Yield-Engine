"""Composite data-quality score (0–100) — a diagnostic, NOT a confidence interval.

README § Methodology weighted table, implemented exactly. Each component is clipped
to [0, 1]; score = 100 × Σ(weight × component). Weights + target come from config.
"""
from __future__ import annotations


def _clip01(x: float) -> float:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return 0.0
    if x != x:  # NaN
        return 0.0
    return max(0.0, min(1.0, x))


def data_quality(row_inputs: dict, weights: dict, target: int) -> float:
    """Compute the 0–100 composite from raw diagnostics.

    row_inputs keys:
      article_count, hhi, duplicate_rate, days_with_data, days_in_window,
      scored_headlines, total_headlines
    weights keys: volume, diversity, duplicate, coverage, scoring
    """
    ac = float(row_inputs.get("article_count", 0) or 0)
    target = float(target) if target else 1.0

    days_win = float(row_inputs.get("days_in_window", 0) or 0)
    total = float(row_inputs.get("total_headlines", 0) or 0)

    components = {
        "volume": _clip01(ac / target if target else 0.0),
        "diversity": _clip01(1.0 - float(row_inputs.get("hhi", 0.0) or 0.0)),
        "duplicate": _clip01(1.0 - float(row_inputs.get("duplicate_rate", 0.0) or 0.0)),
        "coverage": _clip01(
            (float(row_inputs.get("days_with_data", 0) or 0) / days_win)
            if days_win
            else 0.0
        ),
        "scoring": _clip01(
            (float(row_inputs.get("scored_headlines", 0) or 0) / total)
            if total
            else 0.0
        ),
    }

    score = 100.0 * sum(weights.get(k, 0.0) * v for k, v in components.items())
    return round(score, 1)
