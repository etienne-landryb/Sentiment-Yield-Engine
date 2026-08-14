"""Cross-country comparison table built from assembled bundles."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _first_ok_of_type(instruments: dict, want_type: str | None = None):
    """Return (label, correlation) of the first ok instrument (optionally by type)."""
    for lbl, e in instruments.items():
        if not str(e.get("status", "ok")).startswith("ok") or not e.get("correlation"):
            continue
        if want_type is None or e.get("type") == want_type:
            return lbl, e["correlation"]
    return None, None


def compare_countries(bundles: dict, ids: list[str]) -> pd.DataFrame:
    """One summary row per selected entity.

    Reports the spine (first available instrument) plus FX and index correlations
    separately, so the FX layer and the index layer can be compared independently
    (mixed availability across countries is normal).
    """
    rows = []
    for cid in ids:
        b = bundles.get(cid)
        if b is None:
            continue
        adf = b["analytical"]
        instruments = b.get("instruments", {})
        first_label, corr = _first_ok_of_type(instruments)
        corr = corr or {}
        fx_label, fx_corr = _first_ok_of_type(instruments, "fx")
        ix_label, ix_corr = _first_ok_of_type(instruments, "index")

        # UX Pass 2, Part 1 — never a fabricated value for a market-less row; label
        # it honestly rather than a bare dash when the regime explains why.
        if first_label:
            market_display = first_label
        elif b.get("monetary_regime") in ("unlinked", "dollarized"):
            market_display = "sentiment only"
        else:
            market_display = "—"

        rows.append(
            {
                "country_id": cid,
                "country": b["label"],
                "region": b["region"],
                "is_aggregate": bool(b.get("is_aggregate")),
                "monetary_regime": b.get("monetary_regime", "floating"),
                "label_note": b.get("label_note", "Own currency"),
                "sentiment_mean": float(np.nanmean(adf["sentiment_mean"])) if not adf.empty else np.nan,
                "articles": int(adf["article_count"].sum()) if not adf.empty else 0,
                "sources": int(adf["source_count"].max())
                if not adf.empty and adf["source_count"].notna().any() else 0,
                "events": int(adf["event_flag"].sum()) if "event_flag" in adf and not adf.empty else 0,
                "avg_quality": float(np.nanmean(adf["data_quality_score"]))
                if "data_quality_score" in adf and not adf.empty else np.nan,
                "market": market_display,
                "pearson": corr.get("pearson", np.nan),
                "best_lag": (corr.get("best_lag") or {}).get("lag", np.nan),
                "fx_r": (fx_corr or {}).get("pearson", np.nan) if fx_corr else np.nan,
                "fx_lag": ((fx_corr or {}).get("best_lag") or {}).get("lag", np.nan) if fx_corr else np.nan,
                "index_r": (ix_corr or {}).get("pearson", np.nan) if ix_corr else np.nan,
                "index_lag": ((ix_corr or {}).get("best_lag") or {}).get("lag", np.nan) if ix_corr else np.nan,
            }
        )
    return pd.DataFrame(rows)
