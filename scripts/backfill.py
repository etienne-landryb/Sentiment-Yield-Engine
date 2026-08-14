"""Unified backfill — one run fills the whole snapshot (run out of band).

  1. GDELT tone + themes for all panel countries via BigQuery (one query each).
  2. FRED + Twelve Data per instrument.
  3. meta with per-series last_date.

Writes data/snapshot/{sentiment,market,themes,meta}.parquet. No live artlist GDELT.

Usage:
    python scripts/backfill.py --months 6
    python scripts/backfill.py --months 6 --econ-only
    python scripts/backfill.py --market-only          # refetch only market series
    python scripts/backfill.py --demo                 # synthetic seed (no network)

Requires GOOGLE_APPLICATION_CREDENTIALS (BigQuery) + TWELVE_DATA_API_KEY (indices).
FRED + BigQuery data are keyless (BigQuery still needs the GCP service account).
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import settings, snapshot  # noqa: E402

_SPACING = 0.2  # BigQuery does the heavy lifting; only Twelve Data needs gentle pacing


def _code_to_id() -> dict:
    return {c.get("gdelt", {}).get("source_country"): c["id"]
            for c in settings.countries() if c.get("gdelt", {}).get("source_country")}


def fetch_all_sentiment(start, end, econ_only: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    """BigQuery tone + themes for every configured country → (sentiment, themes)."""
    from src.ingest import gdelt_bq

    if not gdelt_bq.available():
        raise RuntimeError("BigQuery unavailable — set GOOGLE_APPLICATION_CREDENTIALS "
                           "and `pip install google-cloud-bigquery db-dtypes`.")
    code2id = _code_to_id()
    codes = list(code2id)
    print(f"  BigQuery tone for {len(codes)} countries (econ_only={econ_only}) …")
    tone = gdelt_bq.fetch_tone(codes, start, end, econ_only=econ_only)
    tone["country_id"] = tone["country_code"].map(code2id)
    tone = tone.dropna(subset=["country_id"])[snapshot.SENTIMENT_COLS]

    print("  BigQuery themes …")
    themes = gdelt_bq.fetch_themes(codes, start, end)
    themes["country_id"] = themes["country_code"].map(code2id)
    themes = themes.dropna(subset=["country_id"])[snapshot.THEMES_COLS]
    return tone.reset_index(drop=True), themes.reset_index(drop=True)


def fetch_country_market(country: dict, start, end) -> pd.DataFrame:
    """Market fetch per instrument → [country_id, instrument_label, date, value]."""
    from src.finance.market import fetch_series_with_status

    frames = []
    for inst in country.get("instruments", []):
        df, status, reason = fetch_series_with_status(inst, start, end)
        print(f"  mkt {country['id']}/{inst['label']}: {status} rows={len(df)} {reason or ''}")
        if status == "ok" and not df.empty:
            df = df.copy()
            df["country_id"] = country["id"]
            df["instrument_label"] = inst["label"]
            frames.append(df[snapshot.MARKET_COLS])
        time.sleep(_SPACING)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=snapshot.MARKET_COLS)


def fetch_all_market(start, end) -> pd.DataFrame:
    frames = [fetch_country_market(c, start, end) for c in settings.countries()]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=snapshot.MARKET_COLS)


def _seed_from_demo(ids) -> tuple[pd.DataFrame, pd.DataFrame]:
    from src.demo import demo_bundle

    topics = settings.load_topics()
    s_rows, m_rows = [], []
    for c in settings.countries():
        if ids and c["id"] not in ids:
            continue
        b = demo_bundle(c, topics, 180)
        adf = b["analytical"]
        s = adf[["date", "gdelt_tone_mean", "article_count"]].rename(columns={"gdelt_tone_mean": "gdelt_tone"})
        s["country_id"] = c["id"]
        s_rows.append(s[snapshot.SENTIMENT_COLS])
        for label, e in b["instruments"].items():
            ser = e["series"].copy()
            ser["country_id"] = c["id"]
            ser["instrument_label"] = label
            m_rows.append(ser[snapshot.MARKET_COLS])
    return (pd.concat(s_rows, ignore_index=True) if s_rows else pd.DataFrame(columns=snapshot.SENTIMENT_COLS),
            pd.concat(m_rows, ignore_index=True) if m_rows else pd.DataFrame(columns=snapshot.MARKET_COLS))


def run(months: int, ids: list[str] | None, demo: bool, econ_only: bool, market_only: bool) -> None:
    end = date.today()
    start = end - timedelta(days=int(months * 30.5))

    themes = None
    if demo:
        print("Seeding snapshot from synthetic demo data (no network)…")
        sentiment, market = _seed_from_demo(ids)
    elif market_only:
        snap = snapshot.load_snapshot()
        if snap is None:
            print("--market-only but no existing snapshot; run a full backfill first.")
            sys.exit(2)
        print("Refetching market only; keeping stored sentiment + themes …")
        sentiment, themes = snap["sentiment"], snap.get("themes")
        market = fetch_all_market(start, end)
    else:
        sentiment, themes = fetch_all_sentiment(start, end, econ_only)
        market = fetch_all_market(start, end)

    meta = snapshot.build_meta(sentiment, market)
    snapshot.write_snapshot(sentiment, market, meta, themes)
    print(f"\nWrote snapshot -> {snapshot.SNAPSHOT_DIR}")
    print(f"  sentiment: {len(sentiment)} rows, "
          f"{sentiment['country_id'].nunique() if not sentiment.empty else 0} countries")
    print(f"  market:    {len(market)} rows")
    print(f"  themes:    {0 if themes is None else len(themes)} rows")
    print(f"  meta:      {len(meta)} series")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Backfill the sentiment/market/themes snapshot.")
    ap.add_argument("--months", type=int, default=6)
    ap.add_argument("--countries", type=str, default="", help="comma-separated ids (demo seed only)")
    ap.add_argument("--demo", action="store_true", help="seed from synthetic data, no network")
    ap.add_argument("--econ-only", action="store_true", help="restrict tone to economic-themed articles")
    ap.add_argument("--market-only", action="store_true", help="refetch only market series")
    args = ap.parse_args()
    ids = [x.strip() for x in args.countries.split(",") if x.strip()] or None
    run(args.months, ids, args.demo, args.econ_only, args.market_only)
