"""Rolling contemporaneous correlation between sentiment and a market series."""
from __future__ import annotations

import pandas as pd


def rolling_corr(sent: pd.Series, mkt: pd.Series, window: int = 30) -> pd.Series:
    """Rolling Pearson correlation, indexed by date. Non-overlapping days dropped."""
    df = pd.DataFrame({"sent": sent, "mkt": mkt}).dropna()
    if df.empty:
        return pd.Series(dtype=float)
    return (
        df["sent"]
        .rolling(window=window, min_periods=max(5, window // 3))
        .corr(df["mkt"])
    )
