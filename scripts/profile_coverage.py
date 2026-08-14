"""Coverage profiling → the country panel (run once with BigQuery access).

1. Sentiment density for every country (BigQuery, one query) → data/coverage_sentiment.csv
2. Financial availability — TEST-FETCH the instrument(s) implied by each country's
   monetary_regime (own currency for floating; the anchor's series for a pegged
   currency; the local index only for dollarized; nothing for unlinked). Keep only
   what returns data — nothing assumed.
3. Panel = sentiment_ok. Financial availability is no longer a gate: a country with
   real sentiment coverage but no fetchable instrument is a valid, honestly-labeled
   sentiment-only panel member (regime-aware graceful degradation handles it). Emits
   data/panel.csv and a paste-ready config/regions.generated.yaml carrying
   monetary_regime + label_note per country.

Requires GOOGLE_APPLICATION_CREDENTIALS (BigQuery) and TWELVE_DATA_API_KEY (index
test). FRED is keyless. Tune thresholds after seeing coverage_sentiment.csv.

    python scripts/profile_coverage.py --min-days 120 --min-avg 5 --months 6
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ingest import gdelt_bq  # noqa: E402
from src.finance.market import fetch_series_with_status  # noqa: E402

DATA = ROOT / "data"
LOOKUP = ROOT / "config" / "country_lookup.yaml"


def _load_lookup() -> dict:
    with open(LOOKUP, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _test_fred(series_id, start, end) -> bool:
    if not series_id:
        return False
    _df, status, _r = fetch_series_with_status(
        {"source": "fred", "source_id": series_id, "series_type": "price"}, start, end)
    return status == "ok"


def _test_twelvedata(symbol, start, end) -> bool:
    if not symbol:
        return False
    _df, status, _r = fetch_series_with_status(
        {"source": "twelvedata", "source_id": symbol, "series_type": "price"}, start, end)
    return status == "ok"


def _fx_label(c: dict) -> str:
    """Label the FX instrument honestly per its regime (never called for unlinked)."""
    regime = c.get("monetary_regime")
    if regime == "pegged":
        return f"{c['currency']}/{c['peg_to']} (pegged, {c['peg_rate']})"
    return f"{c['currency']}/USD"


def _country_block(c: dict, fx_ok: bool, idx_ok: bool) -> dict:
    """Build a regions.yaml country block, carrying monetary_regime + label_note."""
    instruments = []
    if c.get("us_special"):
        instruments.append({"type": "index", "label": "S&P 500", "source": "fred",
                            "source_id": "SP500", "series_type": "price"})
        instruments.append({"type": "yield", "label": "US 10Y", "source": "fred",
                            "source_id": "DGS10", "series_type": "yield"})
    else:
        if fx_ok and c.get("fred_fx"):
            instruments.append({"type": "fx", "label": _fx_label(c), "source": "fred",
                                "source_id": c["fred_fx"], "series_type": "price"})
        if idx_ok and c.get("td_index"):
            instruments.append({"type": "index", "label": f"{c['label']} index ({c['td_index']})",
                                "source": "twelvedata", "source_id": c["td_index"],
                                "series_type": "price"})
    return {"id": c["id"], "label": c["label"], "region": c["region"],
            "currency": c["currency"], "monetary_regime": c.get("monetary_regime"),
            "peg_to": c.get("peg_to"), "label_note": c.get("label_note"),
            "gdelt": {"source_country": c["code"], "source_lang": "english"},
            "instruments": instruments}


def run(min_days: int, min_avg: float, months: int, econ_only: bool) -> None:
    if not gdelt_bq.available():
        print("BigQuery not available. Set GOOGLE_APPLICATION_CREDENTIALS and "
              "`pip install google-cloud-bigquery db-dtypes`. Aborting.")
        sys.exit(2)

    DATA.mkdir(exist_ok=True)
    end = date.today()
    start = end - timedelta(days=int(months * 30.5))
    lookup = _load_lookup()
    candidates = lookup["countries"]

    print(f"[1/3] BigQuery sentiment coverage {start}..{end} (econ_only={econ_only}) …")
    cov = gdelt_bq.coverage(start, end, econ_only=econ_only)
    cov.to_csv(DATA / "coverage_sentiment.csv", index=False)
    print(f"      wrote data/coverage_sentiment.csv ({len(cov)} country codes)")
    cov_by_code = cov.set_index("country_code") if not cov.empty else pd.DataFrame()

    print(f"[2/3] Testing financial availability for {len(candidates)} candidates "
          f"(regime-aware: only the instrument(s) each regime implies) …")
    rows = []
    for c in candidates:
        code = c["code"]
        s = cov_by_code.loc[code] if code in cov_by_code.index else None
        distinct_days = int(s["distinct_days"]) if s is not None else 0
        avg_articles = float(s["avg_articles_per_day"]) if s is not None else 0.0
        sentiment_ok = distinct_days >= min_days and avg_articles >= min_avg

        regime = c.get("monetary_regime")
        if c.get("us_special"):
            fx_ok, idx_ok = False, _test_fred("SP500", start, end)
        elif regime == "unlinked":
            # nothing to test — no candidate instrument exists for this country
            fx_ok, idx_ok = False, False
        elif regime == "dollarized":
            # no exchange rate exists; only the local index (if any) is testable
            fx_ok, idx_ok = False, _test_twelvedata(c.get("td_index"), start, end)
        else:  # pegged or floating
            fx_ok = _test_fred(c.get("fred_fx"), start, end)
            idx_ok = _test_twelvedata(c.get("td_index"), start, end)
        financial_ok = bool(fx_ok or idx_ok)

        rows.append({"code": code, "id": c["id"], "label": c["label"], "region": c["region"],
                     "monetary_regime": regime, "distinct_days": distinct_days,
                     "avg_articles_per_day": avg_articles, "sentiment_ok": sentiment_ok,
                     "fx_ok": bool(fx_ok), "idx_ok": bool(idx_ok), "financial_ok": financial_ok,
                     # Panel = sentiment_ok. Financial availability no longer gates —
                     # a sentiment-only country is a valid, honestly-labeled outcome.
                     "in_panel": sentiment_ok})
        time.sleep(0.2)  # gentle on Twelve Data

    prof = pd.DataFrame(rows)
    prof.to_csv(DATA / "profile.csv", index=False)
    panel = prof[prof["in_panel"]].copy()
    panel.to_csv(DATA / "panel.csv", index=False)
    n_full = int(((panel["fx_ok"]) & (panel["idx_ok"])).sum())
    n_fx_only = int(((panel["fx_ok"]) & (~panel["idx_ok"])).sum())
    n_idx_only = int(((~panel["fx_ok"]) & (panel["idx_ok"])).sum())
    n_sentiment_only = int((~panel["financial_ok"]).sum())
    print(f"      panel = {len(panel)}/{len(prof)} countries (sentiment_ok). "
          f"Full FX+index: {n_full}, FX-only: {n_fx_only}, index-only: {n_idx_only}, "
          f"sentiment-only: {n_sentiment_only}")

    print("[3/3] Emitting config/regions.generated.yaml …")
    by_id = {c["id"]: c for c in candidates}
    blocks, kept_ids = [], set()
    for _, r in panel.iterrows():
        c = by_id[r["id"]]
        blocks.append(_country_block(c, bool(r["fx_ok"]), bool(r["idx_ok"])))
        kept_ids.add(c["id"])

    euro_members = [m for m in lookup.get("euro_area_members", []) if m in kept_ids]
    doc = {
        "base_query": '(economy OR inflation OR "interest rate" OR "central bank" OR market OR recession OR GDP OR unemployment)',
        "sources": {"fred": {"cadence": "weekly"}, "twelvedata": {"cadence": "daily"},
                    "gdelt": {"cadence": "daily"}},
        "regions": {rid: {"label": lbl} for rid, lbl in lookup["regions"].items()},
        "countries": blocks,
    }
    if euro_members:
        doc["aggregates"] = [{
            "id": "euro_area", "label": "Euro area", "region": "europe", "currency": "EUR",
            "iso3": None, "sentiment": {"blend": "gdp_weighted", "members": euro_members},
            "instruments": [{"type": "fx", "label": "EUR/USD", "source": "fred",
                             "source_id": "DEXUSEU", "series_type": "price"}]}]

    out = ROOT / "config" / "regions.generated.yaml"
    header = (
        "# GENERATED by scripts/profile_coverage.py — the coverage-driven panel.\n"
        "# Review, then copy the analysis block from regions.yaml (it is NOT emitted\n"
        "# here) and replace regions.yaml with this. Add iso3 codes for the map.\n"
        "# Every country carries `monetary_regime` + `label_note` — the UI surfaces\n"
        "# these plainly (own currency / pegged / dollarized / sentiment-only). GDP\n"
        "# weights for the euro-area blend are NOT emitted here (country_lookup.yaml\n"
        "# has no gdp field) — add real per-country GDP figures for a true GDP-weighted\n"
        "# blend, or the pipeline falls back to an equal-weighted blend.\n\n"
    )
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(header)
        yaml.safe_dump(doc, fh, sort_keys=False, allow_unicode=True, width=1000)
    print(f"      wrote {out} ({len(blocks)} countries, euro members: {euro_members})")
    print("\nNext: review coverage_sentiment.csv + panel.csv, tune thresholds if needed, "
          "then fold regions.generated.yaml into config/regions.yaml (keep the `analysis:` block).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Profile GDELT coverage and pick the country panel.")
    ap.add_argument("--min-days", type=int, default=120)
    ap.add_argument("--min-avg", type=float, default=5.0)
    ap.add_argument("--months", type=int, default=6)
    ap.add_argument("--econ-only", action="store_true", help="restrict to economic-themed articles")
    args = ap.parse_args()
    run(args.min_days, args.min_avg, args.months, args.econ_only)
