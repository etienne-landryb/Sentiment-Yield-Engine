"""Incremental snapshot refresh (daily cron). BigQuery tone for new days + market.

Reads the stored last_date per series, fetches only the gap [last_date+1 … today],
upserts, refreshes themes for the recent window, bumps meta, and writes. If no
snapshot exists it runs a full backfill.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import snapshot  # noqa: E402
from scripts.backfill import fetch_all_market, fetch_all_sentiment, run  # noqa: E402


def _min_last_date(meta: pd.DataFrame, series_filter=None):
    if meta is None or meta.empty:
        return None
    m = meta if series_filter is None else meta[meta["series"].isin(series_filter)]
    if m.empty:
        return None
    return pd.to_datetime(m["last_date"]).min().date()


def main() -> None:
    snap = snapshot.load_snapshot()
    if snap is None:
        print("No snapshot found — running a full 6-month backfill.")
        run(months=6, ids=None, demo=False, econ_only=False, market_only=False)
        return

    sentiment, market, meta = snap["sentiment"], snap["market"], snap["meta"]
    today = date.today()

    last_sent = _min_last_date(meta, ["sentiment"]) or (today - timedelta(days=7))
    start = last_sent + timedelta(days=1)
    if start > today:
        print("Snapshot already current.")
        return

    print(f"Fetching new days {start}..{today} …")
    new_sent, _new_themes = fetch_all_sentiment(start, today, econ_only=False)
    sentiment = snapshot.upsert(sentiment, new_sent, keys=["country_id", "date"])

    new_mkt = fetch_all_market(start, today)
    market = snapshot.upsert(market, new_mkt, keys=["country_id", "instrument_label", "date"])

    # Themes drift slowly and are period-cumulative; keep the stored set on the daily
    # refresh (a full `backfill.py` run rebuilds them).
    themes = snap.get("themes")
    meta = snapshot.build_meta(sentiment, market)
    snapshot.write_snapshot(sentiment, market, meta, themes)
    print(f"Refreshed: {len(sentiment)} sentiment rows, {len(market)} market rows.")


if __name__ == "__main__":
    main()
