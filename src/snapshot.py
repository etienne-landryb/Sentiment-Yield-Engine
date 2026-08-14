"""Stored snapshot the app reads instead of hitting GDELT/markets live.

Three tidy tables (one parquet each under data/snapshot/):
  sentiment : [country_id, date, gdelt_tone, article_count]   # daily, from timelinetone
  market    : [country_id, instrument_label, date, value]     # daily returns / yield change
  meta      : [country_id, series, last_date, refreshed_at]   # what's current per series

Country/instrument DEFINITIONS still live in config/regions.yaml (single source of
truth); the snapshot holds only time series. The scheduled backfill/refresh jobs
write it; the app reads it. Missing/empty snapshot → the app falls back to demo.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = ROOT / "data" / "snapshot"

SENTIMENT_COLS = ["country_id", "date", "gdelt_tone", "article_count"]
MARKET_COLS = ["country_id", "instrument_label", "date", "value"]
THEMES_COLS = ["country_id", "theme", "count"]
META_COLS = ["country_id", "series", "last_date", "refreshed_at"]

_FILES = {"sentiment": "sentiment.parquet", "market": "market.parquet",
          "themes": "themes.parquet", "meta": "meta.parquet"}
_COLS = {"sentiment": SENTIMENT_COLS, "market": MARKET_COLS,
         "themes": THEMES_COLS, "meta": META_COLS}


def _path(table: str) -> Path:
    return SNAPSHOT_DIR / _FILES[table]


def has_snapshot() -> bool:
    """True if a non-empty sentiment table exists on disk."""
    p = _path("sentiment")
    if not p.exists():
        return False
    try:
        return not pd.read_parquet(p).empty
    except Exception:
        return False


def load_snapshot() -> dict | None:
    """Read all three tables into a dict, or None if there's no usable snapshot."""
    if not has_snapshot():
        return None
    out = {}
    for table, fname in _FILES.items():
        p = SNAPSHOT_DIR / fname
        if p.exists():
            df = pd.read_parquet(p)
            if "date" in df:
                df["date"] = pd.to_datetime(df["date"]).dt.date
            out[table] = df
        else:
            out[table] = pd.DataFrame(columns=_COLS[table])
    return out


def upsert(existing: pd.DataFrame, new: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Replace rows in `existing` whose key tuples appear in `new`, then append `new`."""
    if new is None or new.empty:
        return existing
    if existing is None or existing.empty:
        return new.reset_index(drop=True)
    merged = pd.concat([existing, new], ignore_index=True)
    return merged.drop_duplicates(subset=keys, keep="last").reset_index(drop=True)


def write_snapshot(sentiment: pd.DataFrame, market: pd.DataFrame, meta: pd.DataFrame,
                   themes: pd.DataFrame | None = None) -> None:
    """Persist the tables to data/snapshot/*.parquet (themes optional)."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    tables = {"sentiment": sentiment, "market": market, "themes": themes, "meta": meta}
    for table, df in tables.items():
        cols = _COLS[table]
        out = (df if df is not None else pd.DataFrame(columns=cols)).copy()
        for c in cols:
            if c not in out:
                out[c] = pd.NA
        out[cols].to_parquet(_path(table), index=False)


def build_meta(sentiment: pd.DataFrame, market: pd.DataFrame) -> pd.DataFrame:
    """Derive the meta table (last_date + refreshed_at) from the series tables."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    if sentiment is not None and not sentiment.empty:
        for cid, g in sentiment.groupby("country_id"):
            rows.append({"country_id": cid, "series": "sentiment",
                         "last_date": pd.to_datetime(g["date"]).max().date(), "refreshed_at": now})
    if market is not None and not market.empty:
        for (cid, lbl), g in market.groupby(["country_id", "instrument_label"]):
            rows.append({"country_id": cid, "series": lbl,
                         "last_date": pd.to_datetime(g["date"]).max().date(), "refreshed_at": now})
    return pd.DataFrame(rows, columns=META_COLS)


def last_date_for(meta: pd.DataFrame, country_id: str, series: str):
    """Return the stored last_date for a country/series, or None."""
    if meta is None or meta.empty:
        return None
    m = meta[(meta["country_id"] == country_id) & (meta["series"] == series)]
    if m.empty:
        return None
    return pd.to_datetime(m.iloc[0]["last_date"]).date()
