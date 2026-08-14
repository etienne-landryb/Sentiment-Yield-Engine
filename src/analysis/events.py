"""Statistical event / anomaly detection on the daily sentiment series.

README § Methodology: rolling 30-day mean/std z-score on sentiment_mean, OR an
article-volume z-score; flag when |z| >= 2 on either. event_score = |z_sentiment|.
A flag means "an unusual movement in the observed data occurred here" — never that
it caused a market move.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _rolling_z(series: pd.Series, window: int) -> pd.Series:
    """Trailing z-score using a rolling mean/std (min_periods lets early days score)."""
    roll = series.rolling(window=window, min_periods=max(5, window // 3))
    mean = roll.mean()
    std = roll.std(ddof=0)
    z = (series - mean) / std.replace(0, np.nan)
    return z.replace([np.inf, -np.inf], np.nan)


def detect_events(
    daily: pd.DataFrame, z_thresh: float = 2.0, window: int = 30
) -> pd.DataFrame:
    """Add [event_flag, event_score] to a daily frame (needs sentiment_mean, article_count)."""
    if daily is None or daily.empty:
        out = daily.copy() if daily is not None else pd.DataFrame()
        out["event_flag"] = pd.Series(dtype=bool)
        out["event_score"] = pd.Series(dtype=float)
        return out

    out = daily.copy().sort_values("date").reset_index(drop=True)
    z_sent = _rolling_z(out["sentiment_mean"].astype(float), window)
    z_vol = (
        _rolling_z(out["article_count"].astype(float), window)
        if "article_count" in out
        else pd.Series(np.nan, index=out.index)
    )

    z_sent_abs = z_sent.abs()
    z_vol_abs = z_vol.abs()

    out["event_score"] = z_sent_abs.fillna(0.0)
    out["event_flag"] = (z_sent_abs >= z_thresh).fillna(False) | (
        z_vol_abs >= z_thresh
    ).fillna(False)
    return out
