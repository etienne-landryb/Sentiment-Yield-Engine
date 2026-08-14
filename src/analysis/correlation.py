"""Sentiment × market correlation — the headline analytical layer.

Contemporaneous scatter stats, lead/lag cross-correlation with the approximate
±1.96/√n band, and the peak-|corr| lag. README § Methodology, lead/lag convention:
  lag > 0  → sentiment leads market:  corr(sentiment_t, return_{t+lag})
  lag < 0  → market leads sentiment
The band is approximate and unreliable under autocorrelation (stated in the UI).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def _align(sent: pd.Series, mkt: pd.Series) -> pd.DataFrame:
    """Inner-join two date-indexed series, dropping non-overlapping/NaN rows."""
    df = pd.DataFrame({"sent": sent, "mkt": mkt})
    return df.dropna()


def scatter_stats(sent: pd.Series, mkt: pd.Series) -> dict:
    """Pearson, Spearman, n, and OLS slope/intercept for sentiment vs market."""
    df = _align(sent, mkt)
    n = len(df)
    empty = {
        "pearson": np.nan,
        "spearman": np.nan,
        "n": n,
        "slope": np.nan,
        "intercept": np.nan,
    }
    if n < 3:
        return empty
    x, y = df["sent"].to_numpy(), df["mkt"].to_numpy()
    if np.std(x) == 0 or np.std(y) == 0:
        return empty
    pearson = float(np.corrcoef(x, y)[0, 1])
    spearman = float(stats.spearmanr(x, y).statistic)
    slope, intercept = np.polyfit(x, y, 1)
    return {
        "pearson": pearson,
        "spearman": spearman,
        "n": n,
        "slope": float(slope),
        "intercept": float(intercept),
    }


def lead_lag(sent: pd.Series, mkt: pd.Series, max_lag: int = 5):
    """Cross-correlation over ±max_lag.

    Returns (cc, band, n) where cc is a DataFrame[lag, corr], band = 1.96/√n,
    and n is the number of overlapping observations at lag 0.
    """
    df = _align(sent, mkt)
    n = len(df)
    band = float(1.96 / np.sqrt(n)) if n > 0 else np.nan

    lags, corrs = [], []
    for lag in range(-max_lag, max_lag + 1):
        # corr(sentiment_t, market_{t+lag})  ==  corr(sent, mkt.shift(-lag))
        shifted = df["mkt"].shift(-lag)
        pair = pd.DataFrame({"s": df["sent"], "m": shifted}).dropna()
        if len(pair) >= 3 and pair["s"].std() > 0 and pair["m"].std() > 0:
            corrs.append(float(np.corrcoef(pair["s"], pair["m"])[0, 1]))
        else:
            corrs.append(np.nan)
        lags.append(lag)

    cc = pd.DataFrame({"lag": lags, "corr": corrs})
    return cc, band, n


def best_lag(cc: pd.DataFrame) -> dict:
    """The lag of peak |corr| (ties → smallest |lag|). {lag, corr}."""
    if cc is None or cc.empty or cc["corr"].isna().all():
        return {"lag": 0, "corr": np.nan}
    valid = cc.dropna(subset=["corr"]).copy()
    valid["abscorr"] = valid["corr"].abs()
    valid["ablag"] = valid["lag"].abs()
    row = valid.sort_values(["abscorr", "ablag"], ascending=[False, True]).iloc[0]
    return {"lag": int(row["lag"]), "corr": float(row["corr"])}
