"""Daily aggregation of scored, topic-tagged headlines -> per-day sentiment frame.

Pure functions: DataFrame in, DataFrame out. No global state.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.nlp.sentiment import polarity_label

DAILY_COLUMNS = [
    "date",
    "sentiment_mean",
    "sentiment_median",
    "sentiment_positive_share",
    "sentiment_neutral_share",
    "sentiment_negative_share",
    "article_count",
    "source_count",
]


def daily_sentiment(scored: pd.DataFrame) -> pd.DataFrame:
    """Aggregate article-level rows to one row per date.

    Expects columns: [date, vader] and optionally [domain]. Returns the columns
    listed in DAILY_COLUMNS (see README § Methodology for the shares/label rule).
    """
    if scored is None or scored.empty:
        return pd.DataFrame(columns=DAILY_COLUMNS)

    df = scored.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["_label"] = df["vader"].apply(polarity_label)

    def _agg(group: pd.DataFrame) -> pd.Series:
        n = len(group)
        labels = group["_label"].value_counts()
        pos = int(labels.get("positive", 0))
        neu = int(labels.get("neutral", 0))
        neg = int(labels.get("negative", 0))
        source_count = group["domain"].nunique() if "domain" in group else np.nan
        return pd.Series(
            {
                "sentiment_mean": group["vader"].mean(),
                "sentiment_median": group["vader"].median(),
                "sentiment_positive_share": pos / n if n else np.nan,
                "sentiment_neutral_share": neu / n if n else np.nan,
                "sentiment_negative_share": neg / n if n else np.nan,
                "article_count": n,
                "source_count": source_count,
            }
        )

    out = df.groupby("date", sort=True).apply(_agg, include_groups=False).reset_index()
    return out[DAILY_COLUMNS]
