"""Headline cleaning + near-duplicate removal (V1: normalised-title match)."""
from __future__ import annotations

import re

import pandas as pd

_WS = re.compile(r"\s+")
_NONALNUM = re.compile(r"[^a-z0-9 ]+")


def clean_headlines(df: pd.DataFrame) -> pd.DataFrame:
    """Strip, normalise whitespace, drop empty titles."""
    if df is None or df.empty:
        return df.copy() if df is not None else pd.DataFrame()
    out = df.copy()
    out["title"] = (
        out["title"].fillna("").astype(str).map(lambda t: _WS.sub(" ", t).strip())
    )
    out = out[out["title"] != ""].reset_index(drop=True)
    return out


def _normalise(title: str) -> str:
    return _WS.sub(" ", _NONALNUM.sub(" ", title.lower())).strip()


def deduplicate(df: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    """Drop near-duplicate titles (normalised match). Returns (deduped, duplicate_rate)."""
    if df is None or df.empty:
        return (df.copy() if df is not None else pd.DataFrame()), 0.0
    out = df.copy()
    total = len(out)
    out["_norm"] = out["title"].astype(str).map(_normalise)
    deduped = out.drop_duplicates(subset="_norm", keep="first").drop(columns="_norm")
    kept = len(deduped)
    duplicate_rate = (total - kept) / total if total else 0.0
    return deduped.reset_index(drop=True), float(duplicate_rate)
