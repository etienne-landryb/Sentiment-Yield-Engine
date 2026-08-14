"""Source diversity / concentration diagnostics (README § Methodology: HHI)."""
from __future__ import annotations

import pandas as pd


def hhi(sources: pd.Series) -> float:
    """Herfindahl-Hirschman Index over source shares: HHI = Σ p_i², in [0, 1].

    `sources` is a series of source identifiers (one per article). A single source
    yields 1.0; N equally-sized sources yield 1/N.
    """
    if sources is None or len(sources) == 0:
        return 0.0
    counts = pd.Series(sources).value_counts()
    shares = counts / counts.sum()
    return float((shares**2).sum())


def source_stats(df: pd.DataFrame, col: str = "domain", top: int = 5) -> dict:
    """Return {source_count, hhi, top_shares} for an article-level frame."""
    if df is None or df.empty or col not in df:
        return {"source_count": 0, "hhi": 0.0, "top_shares": {}}
    counts = df[col].value_counts()
    total = counts.sum()
    top_shares = {str(k): float(v / total) for k, v in counts.head(top).items()}
    return {
        "source_count": int(counts.shape[0]),
        "hhi": hhi(df[col]),
        "top_shares": top_shares,
    }
