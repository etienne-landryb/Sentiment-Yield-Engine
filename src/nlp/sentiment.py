"""VADER polarity on headline titles (README § Key decisions: VADER on titles)."""
from __future__ import annotations

import pandas as pd
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from src.settings import analysis_cfg

_ANALYZER = SentimentIntensityAnalyzer()
_THRESH = float(analysis_cfg().get("polarity_threshold", 0.05))


def score(df: pd.DataFrame, text_col: str = "title") -> pd.DataFrame:
    """Add a 'vader' compound column (−1..+1) computed on the title column."""
    out = df.copy()
    if out.empty:
        out["vader"] = pd.Series(dtype=float)
        return out
    out["vader"] = (
        out[text_col]
        .fillna("")
        .astype(str)
        .apply(lambda t: _ANALYZER.polarity_scores(t)["compound"])
    )
    return out


def polarity_label(compound: float, thresh: float = _THRESH) -> str:
    """positive if compound ≥ +thresh, negative if ≤ −thresh, else neutral."""
    if compound is None:
        return "neutral"
    if compound >= thresh:
        return "positive"
    if compound <= -thresh:
        return "negative"
    return "neutral"
