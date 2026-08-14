"""Orchestration: ingest → analytical dataset → correlation block → CountryBundle.

The UI imports ONLY this module and the visualization helpers — never ingest/, nlp/,
or finance/ directly. build_all(period) dispatches demo vs live on DATA_MODE and
returns dict[country_id, CountryBundle]; both modes return the same shape.

Shared assembly helpers (assemble_analytical, correlation_block, instruments_block)
are used by BOTH the live path here and the demo generator, so the two can never
drift out of shape.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd

from src import settings
from src.analysis.aggregation import daily_sentiment
from src.analysis.correlation import best_lag, lead_lag, scatter_stats
from src.analysis.diversity import hhi
from src.analysis.events import detect_events
from src.analysis.quality import data_quality
from src.analysis.rolling import rolling_corr

log = logging.getLogger(__name__)


# ── period handling ──────────────────────────────────────────────────────────
def _period_bounds(period) -> tuple[date, date]:
    """Accept an int (lookback days) or (start, end); return (start, end)."""
    end = date.today()
    if isinstance(period, (tuple, list)) and len(period) == 2:
        return pd.to_datetime(period[0]).date(), pd.to_datetime(period[1]).date()
    days = int(period) if period else 120
    return end - timedelta(days=days), end


# ── shared assembly (used by live AND demo) ──────────────────────────────────
def _per_day_keywords(titles: list[str], n: int = 8) -> list[str]:
    """Cheap frequency keywords for the analytical row (word cloud uses TF-IDF)."""
    import re
    from collections import Counter

    stop = {
        "the", "and", "for", "with", "from", "that", "this", "are", "was", "has",
        "have", "will", "amid", "over", "into", "says", "after", "new", "its",
    }
    words = [
        w.lower()
        for t in titles
        for w in re.findall(r"[A-Za-z][A-Za-z\-']+", str(t))
        if len(w) > 2 and w.lower() not in stop
    ]
    return [w for w, _ in Counter(words).most_common(n)]


def assemble_analytical(
    articles: pd.DataFrame,
    tone_df: pd.DataFrame,
    *,
    region: str,
    country: str,
    duplicate_rate: float,
    total_headlines: int,
    start: date,
    end: date,
    cfg: dict,
) -> pd.DataFrame:
    """Build the tidy per-(country,date) analytical frame from scored+tagged articles.

    `articles` must already be cleaned, deduped, VADER-scored ('vader') and
    topic-tagged ('topic'), with columns [date, title, url, domain, vader, topic].
    """
    q_cfg = settings.quality_cfg()
    ev_cfg = cfg.get("event", {})

    daily = daily_sentiment(articles)
    if daily.empty:
        return pd.DataFrame()

    # source concentration (HHI) per day
    conc = (
        articles.assign(date=pd.to_datetime(articles["date"]).dt.date)
        .groupby("date")["domain"]
        .apply(hhi)
        .rename("source_concentration")
        .reset_index()
    )
    daily = daily.merge(conc, on="date", how="left")

    # topics per day
    art = articles.copy()
    art["date"] = pd.to_datetime(art["date"]).dt.date
    topic_rows = {}
    for d, grp in art.groupby("date"):
        counts = grp["topic"].value_counts().to_dict()
        tsent = grp.groupby("topic")["vader"].mean().to_dict()
        top = sorted(counts, key=counts.get, reverse=True)[:3]
        topic_rows[d] = {
            "top_topics": top,
            "topic_counts": {k: int(v) for k, v in counts.items()},
            "topic_sentiment": {k: float(v) for k, v in tsent.items()},
            "keywords": _per_day_keywords(grp["title"].tolist()),
        }
    daily["top_topics"] = daily["date"].map(lambda d: topic_rows.get(d, {}).get("top_topics", []))
    daily["topic_counts"] = daily["date"].map(lambda d: topic_rows.get(d, {}).get("topic_counts", {}))
    daily["topic_sentiment"] = daily["date"].map(lambda d: topic_rows.get(d, {}).get("topic_sentiment", {}))
    daily["keywords"] = daily["date"].map(lambda d: topic_rows.get(d, {}).get("keywords", []))

    # events
    daily = detect_events(
        daily, z_thresh=ev_cfg.get("z_thresh", 2.0), window=ev_cfg.get("window", 30)
    )

    # gdelt tone (independent measure) merged in
    if tone_df is not None and not tone_df.empty:
        t = tone_df.copy()
        t["date"] = pd.to_datetime(t["date"]).dt.date
        daily = daily.merge(
            t.rename(columns={"gdelt_tone": "gdelt_tone_mean"}), on="date", how="left"
        )
    if "gdelt_tone_mean" not in daily:
        daily["gdelt_tone_mean"] = np.nan

    # duplicate_rate (period, broadcast) + region/country
    daily["duplicate_rate"] = float(duplicate_rate)
    daily["region"] = region
    daily["country"] = country

    # data-quality (period-level diagnostic, broadcast to each row)
    days_in_window = max((end - start).days, 1)
    dq = data_quality(
        {
            "article_count": int(daily["article_count"].sum()),
            "hhi": float(hhi(articles["domain"])) if "domain" in articles else 0.0,
            "duplicate_rate": float(duplicate_rate),
            "days_with_data": int(daily["date"].nunique()),
            "days_in_window": days_in_window,
            "scored_headlines": int(articles["vader"].notna().sum()),
            "total_headlines": int(total_headlines) or int(len(articles)),
        },
        q_cfg["weights"],
        q_cfg["target"],
    )
    daily["data_quality_score"] = dq

    ordered = [
        "region", "country", "date",
        "article_count", "source_count", "duplicate_rate", "source_concentration",
        "sentiment_mean", "sentiment_median",
        "sentiment_positive_share", "sentiment_neutral_share", "sentiment_negative_share",
        "gdelt_tone_mean",
        "top_topics", "topic_counts", "topic_sentiment", "keywords",
        "event_flag", "event_score", "data_quality_score",
    ]
    for col in ordered:
        if col not in daily:
            daily[col] = np.nan
    return daily[ordered].sort_values("date").reset_index(drop=True)


def correlation_block(sent: pd.Series, mkt: pd.Series, cfg: dict) -> dict:
    """Full correlation dict for one instrument (README lead/lag + band)."""
    c_cfg = cfg.get("correlation", {})
    max_lag = int(c_cfg.get("max_lag", 5))
    window = int(c_cfg.get("rolling_window", 30))

    stats = scatter_stats(sent, mkt)
    cc, band, n = lead_lag(sent, mkt, max_lag=max_lag)
    bl = best_lag(cc)
    roll = rolling_corr(sent, mkt, window=window)

    return {
        "pearson": stats["pearson"],
        "spearman": stats["spearman"],
        "n": n,
        "slope": stats["slope"],
        "intercept": stats["intercept"],
        "rolling": roll,
        "leadlag": cc,
        "band": band,
        "best_lag": bl,
    }


def _sentiment_series(analytical: pd.DataFrame) -> pd.Series:
    if analytical is None or analytical.empty:
        return pd.Series(dtype=float)
    return analytical.set_index(pd.to_datetime(analytical["date"]))["sentiment_mean"]


def _last_updated(series: pd.DataFrame):
    if series is None or series.empty:
        return None
    return pd.to_datetime(series["date"]).max().date()


def ok_instrument(type_: str, meta: dict, series: pd.DataFrame, sent: pd.Series, cfg: dict,
                  status: str = "ok", last_updated=None) -> dict:
    """Assemble an available instrument entry (with its correlation block).

    `status` is "ok" for a fresh fetch or "ok (cached)" when served from last-good.
    """
    if series is not None and not series.empty:
        mkt = series.set_index(pd.to_datetime(series["date"]))["value"]
    else:
        mkt = pd.Series(dtype=float)
    return {
        "type": type_,
        "status": status,
        "meta": meta,
        "series": series,
        "correlation": correlation_block(sent, mkt, cfg),
        "last_updated": last_updated if last_updated is not None else _last_updated(series),
    }


def unavailable_instrument(type_: str, meta: dict, reason: str | None) -> dict:
    """Assemble an unavailable instrument entry — no series/correlation, keeps type."""
    return {
        "type": type_,
        "status": "unavailable",
        "reason": reason or "unavailable",
        "meta": meta,
        "series": None,
        "correlation": None,
        "last_updated": None,
    }


def first_ok_instrument(bundle: dict):
    """Return (label, entry) of the first available instrument, or (None, None)."""
    for label, entry in bundle.get("instruments", {}).items():
        if str(entry.get("status", "")).startswith("ok") and entry.get("correlation"):
            return label, entry
    return None, None


def instruments_block(analytical: pd.DataFrame, instruments_series: dict, cfg: dict) -> dict:
    """Assemble per-instrument entries from already-fetched series (demo/legacy path).

    instruments_series: {label: {"type": str, "meta": {...}, "series": DataFrame}}
    Every entry here is treated as available ("ok").
    """
    sent = _sentiment_series(analytical)
    out = {}
    for label, payload in instruments_series.items():
        type_ = payload.get("type") or payload.get("meta", {}).get("asset_type", "index")
        out[label] = ok_instrument(type_, payload["meta"], payload["series"], sent, cfg)
    return out


# ── live path ────────────────────────────────────────────────────────────────
def build_country(country_cfg, base_query, topic_dict, period) -> dict:
    """Live orchestration for one country. Returns a CountryBundle."""
    from src.finance.market import fetch_series_with_status
    from src.ingest.clean import clean_headlines, deduplicate
    from src.ingest.gdelt import fetch_articles, fetch_timeline_tone
    from src.ingest.rss import fetch_rss
    from src.nlp.sentiment import score
    from src.nlp.topics import tag_topics

    import time as _time

    cfg = settings.analysis_cfg()
    start, end = _period_bounds(period)

    # ingest (with full GDELT trace for diagnostics)
    _t0 = _time.monotonic()
    arts, art_trace = fetch_articles(base_query, country_cfg, start, end)
    rss = fetch_rss(country_cfg.get("rss", []))
    if not rss.empty:
        arts = pd.concat([arts, rss], ignore_index=True)
    tone, tone_trace = fetch_timeline_tone(base_query, country_cfg, start, end)
    t_gdelt = _time.monotonic() - _t0

    # clean / dedup / score / tag
    arts = clean_headlines(arts)
    total_headlines = len(arts)
    arts, dup_rate = deduplicate(arts)
    arts = score(arts)
    arts = tag_topics(arts, topic_dict)

    analytical = assemble_analytical(
        arts,
        tone,
        region=country_cfg["region"],
        country=country_cfg["label"],
        duplicate_rate=dup_rate,
        total_headlines=total_headlines,
        start=start,
        end=end,
        cfg=cfg,
    )

    # instruments — each fetched independently; a failure is a per-instrument
    # status, never an abort. Sentiment (GDELT) is the spine: if it resolved, the
    # country is built regardless of instruments.
    from src import marketcache

    cid = country_cfg["id"]
    sent = _sentiment_series(analytical)
    instruments = {}
    _t1 = _time.monotonic()
    for inst in country_cfg.get("instruments", []):
        label = inst["label"]
        meta = {"source": inst["source"], "source_id": inst["source_id"],
                "series_type": inst["series_type"]}
        df, status, reason = fetch_series_with_status(inst, start, end)
        if status == "ok":
            marketcache.remember(cid, label, df, _last_updated(df))
            instruments[label] = ok_instrument(inst["type"], meta, df, sent, cfg)
        else:
            # failed refresh → serve this instrument's last-good if we have one
            cached = marketcache.recall(cid, label)
            if cached and cached["series"] is not None and not cached["series"].empty:
                instruments[label] = ok_instrument(
                    inst["type"], meta, cached["series"], sent, cfg,
                    status="ok (cached)", last_updated=cached["last_updated"])
            else:
                instruments[label] = unavailable_instrument(inst["type"], meta, reason)
    t_market = _time.monotonic() - _t1

    diag = {
        "country": country_cfg["label"],
        "gdelt_country_code": country_cfg.get("gdelt", {}).get("source_country"),
        "artlist": art_trace,        # {query, http_status, window_statuses, error, attempts, n_windows, windows_ok, n_articles}
        "tone": tone_trace,          # {http_status, error, attempts, n_rows}
        "gdelt_articles_raw": int(total_headlines),
        "articles_kept": int(len(arts)),
        "distinct_days": int(analytical["date"].nunique()) if not analytical.empty else 0,
        "instruments": {
            l: {"source": e.get("meta", {}).get("source"),
                "symbol": e.get("meta", {}).get("source_id"),
                "status": e.get("status"), "reason": e.get("reason"),
                "rows": (0 if e.get("series") is None else int(len(e["series"])))}
            for l, e in instruments.items()
        },
        "timing_s": {"gdelt": round(t_gdelt, 1), "market": round(t_market, 1)},
    }
    log.info("BUILD DIAG %s", diag)  # visible in Streamlit Cloud → Manage app → logs

    return {
        "country_id": country_cfg["id"],
        "label": country_cfg["label"],
        "region": country_cfg["region"],
        "currency": country_cfg.get("currency"),
        "monetary_regime": country_cfg.get("monetary_regime", "floating"),
        "peg_to": country_cfg.get("peg_to"),
        "label_note": country_cfg.get("label_note", "Own currency"),
        "analytical": analytical,
        "articles": arts[["date", "title", "url", "domain", "vader", "topic"]]
        if not arts.empty
        else arts,
        "instruments": instruments,
        "source": "live",
        "diag": diag,
    }


# ── snapshot path (reads data/snapshot; no live fetch on the request path) ────
def _analytical_from_snapshot(sent_rows: pd.DataFrame, region: str, country: str,
                              start, end, cfg: dict) -> pd.DataFrame:
    """Build the schema-complete analytical frame from stored daily GDELT tone.

    In snapshot mode the daily sentiment SIGNAL is GDELT's own tone (from
    timelinetone), normalised to a VADER-comparable range. Per-headline fields
    (shares, topics, keywords, source structure) are absent here — the supplementary
    VADER-on-headlines layer fills those for the recent window (future work). The
    correlation methodology and data-quality FORMULA are unchanged; only the inputs
    differ. Columns match the analytical schema exactly.
    """
    from src.analysis.quality import data_quality

    if sent_rows is None or sent_rows.empty:
        return pd.DataFrame()

    q = settings.quality_cfg()
    ev = cfg.get("event", {})
    df = sent_rows.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df.sort_values("date").reset_index(drop=True)

    tone = df["gdelt_tone"].astype(float)
    # Tone-based daily polarity classification (README § Methodology, snapshot path):
    # tone > +0.5 positive, < −0.5 negative, else neutral. Per-day one-hot (no
    # per-article distribution from the tone timeline), so the three shares sum to 1.
    pos = (tone > 0.5).astype(float)
    neg = (tone < -0.5).astype(float)
    neu = (1.0 - pos - neg).clip(lower=0.0)
    daily = pd.DataFrame({
        "region": region,
        "country": country,
        "date": df["date"],
        "article_count": df["article_count"].astype("float") if "article_count" in df else np.nan,
        "source_count": np.nan,
        "duplicate_rate": 0.0,
        "source_concentration": np.nan,
        "sentiment_mean": (tone / 10.0).clip(-1, 1),   # normalise GDELT tone (~±10) → ±1
        "sentiment_median": (tone / 10.0).clip(-1, 1),
        "sentiment_positive_share": pos,
        "sentiment_neutral_share": neu,
        "sentiment_negative_share": neg,
        "gdelt_tone_mean": tone,
        "top_topics": [[] for _ in range(len(df))],
        "topic_counts": [{} for _ in range(len(df))],
        "topic_sentiment": [{} for _ in range(len(df))],
        "keywords": [[] for _ in range(len(df))],
    })

    daily = detect_events(daily, z_thresh=ev.get("z_thresh", 2.0), window=ev.get("window", 30))

    days_in_window = max((pd.to_datetime(end) - pd.to_datetime(start)).days, 1)
    # Snapshot mode (tone-only) has NO per-article data, so 3 of the formula's 5
    # inputs (source diversity, duplicate cleanliness, scoring success) genuinely
    # can't be measured here. Feeding them values that saturate their component to
    # 1.0 (as if perfectly diverse/deduped/scored) would silently inflate the score
    # to look like a full 5-dimension measurement when only volume + coverage are
    # real. Instead: hhi=1.0 -> diversity=0, duplicate_rate=1.0 -> duplicate=0, and
    # scored=0/total=1 -> scoring=0 — "no signal measured" gets 0 credit, the same
    # convention data_quality() already uses for a missing/zero denominator
    # elsewhere. The formula and its weights are UNCHANGED (README methodology);
    # only these snapshot-specific inputs are honest about what wasn't measured.
    dq = data_quality(
        {"article_count": float(np.nansum(daily["article_count"])),
         "hhi": 1.0, "duplicate_rate": 1.0,
         "days_with_data": int(daily["date"].nunique()), "days_in_window": days_in_window,
         "scored_headlines": 0, "total_headlines": 1},
        q["weights"], q["target"])
    daily["data_quality_score"] = dq

    ordered = [
        "region", "country", "date", "article_count", "source_count", "duplicate_rate",
        "source_concentration", "sentiment_mean", "sentiment_median",
        "sentiment_positive_share", "sentiment_neutral_share", "sentiment_negative_share",
        "gdelt_tone_mean", "top_topics", "topic_counts", "topic_sentiment", "keywords",
        "event_flag", "event_score", "data_quality_score",
    ]
    return daily[ordered]


def build_country_from_snapshot(country_cfg: dict, snap: dict, period) -> dict:
    """Assemble a CountryBundle from the stored snapshot — no live fetch.

    Slices the sentiment + market rows for this country/period, then runs the SAME
    assembly/correlation code as the live path.
    """
    cfg = settings.analysis_cfg()
    cid = country_cfg["id"]
    start, end = _period_bounds(period)

    sdf = snap.get("sentiment", pd.DataFrame())
    mask = (sdf["country_id"] == cid) if not sdf.empty else pd.Series(dtype=bool)
    sent_rows = sdf[mask].copy() if not sdf.empty else sdf
    if not sent_rows.empty:
        sent_rows["date"] = pd.to_datetime(sent_rows["date"]).dt.date
        sent_rows = sent_rows[(sent_rows["date"] >= start) & (sent_rows["date"] <= end)]

    analytical = _analytical_from_snapshot(sent_rows, country_cfg["region"],
                                           country_cfg["label"], start, end, cfg)
    sent = _sentiment_series(analytical)

    mdf = snap.get("market", pd.DataFrame())
    instruments = {}
    for inst in country_cfg.get("instruments", []):
        label = inst["label"]
        meta = {"source": inst["source"], "source_id": inst["source_id"],
                "series_type": inst["series_type"]}
        rows = mdf[(mdf["country_id"] == cid) & (mdf["instrument_label"] == label)] if not mdf.empty else mdf
        if rows is not None and not rows.empty:
            series = rows[["date", "value"]].copy()
            series["date"] = pd.to_datetime(series["date"]).dt.date
            series = series[(series["date"] >= start) & (series["date"] <= end)].sort_values("date").reset_index(drop=True)
            instruments[label] = ok_instrument(inst["type"], meta, series, sent, cfg)
        else:
            instruments[label] = unavailable_instrument(inst["type"], meta, "not in snapshot")

    refreshed = None
    meta_tbl = snap.get("meta", pd.DataFrame())
    if meta_tbl is not None and not meta_tbl.empty:
        r = meta_tbl[(meta_tbl["country_id"] == cid) & (meta_tbl["series"] == "sentiment")]
        if not r.empty:
            refreshed = str(r.iloc[0]["refreshed_at"])

    tdf = snap.get("themes", pd.DataFrame())
    themes = (tdf[tdf["country_id"] == cid][["theme", "count"]].reset_index(drop=True)
              if tdf is not None and not tdf.empty else pd.DataFrame(columns=["theme", "count"]))

    return {
        "country_id": cid,
        "label": country_cfg["label"],
        "region": country_cfg["region"],
        "currency": country_cfg.get("currency"),
        "monetary_regime": country_cfg.get("monetary_regime", "floating"),
        "peg_to": country_cfg.get("peg_to"),
        "label_note": country_cfg.get("label_note", "Own currency"),
        "analytical": analytical,
        "articles": pd.DataFrame(columns=["date", "title", "url", "domain", "vader", "topic"]),
        "themes": themes,
        "instruments": instruments,
        "source": "snapshot",
        "diag": {"country": country_cfg["label"], "source": "snapshot",
                 "sentiment_rows": int(len(sent_rows)) if sent_rows is not None else 0,
                 "distinct_days": int(analytical["date"].nunique()) if not analytical.empty else 0,
                 "refreshed_at": refreshed,
                 "instruments": {l: {"symbol": e.get("meta", {}).get("source_id"),
                                     "status": e.get("status"), "reason": e.get("reason"),
                                     "rows": (0 if e.get("series") is None else int(len(e["series"])))}
                                 for l, e in instruments.items()}},
    }


# ── dispatch ─────────────────────────────────────────────────────────────────
def build_all(period=120) -> dict:
    """Return {country_id: CountryBundle} for every configured country.

    Dispatches on DATA_MODE: demo | snapshot | live. Snapshot mode reads
    data/snapshot; if it's missing/empty the whole run falls back to demo.
    """
    base_query = settings.base_query()
    topic_dict = settings.load_topics()
    mode = settings.data_mode()

    snap = None
    if mode == "snapshot":
        from src import snapshot
        snap = snapshot.load_snapshot()
        if snap is None:
            log.warning("DATA_MODE=snapshot but no snapshot found — falling back to demo.")

    bundles = {}
    for c in settings.countries():
        try:
            if mode == "live":
                bundles[c["id"]] = build_country(c, base_query, topic_dict, period)
            elif mode == "snapshot" and snap is not None:
                bundles[c["id"]] = build_country_from_snapshot(c, snap, period)
            else:
                from src.demo import demo_bundle  # lazy import avoids a cycle
                bundles[c["id"]] = demo_bundle(c, topic_dict, period)
        except Exception as exc:  # one bad country never kills the run
            log.exception("Failed to build bundle for %s: %s", c.get("id"), exc)
            continue
    return bundles


# ── shared-currency aggregates (euro area) — kept OUT of build_all so the ────
#    contract/tests (build_all == configured countries) are unchanged. ─────────
def _weighted_blend(cols_by_member: dict, weights: dict) -> pd.Series:
    """Row-wise GDP-weighted mean across members, renormalising over present ones."""
    df = pd.DataFrame(cols_by_member)
    w = pd.Series(weights).reindex(df.columns).fillna(0.0)
    wmat = df.notna().mul(w, axis=1)
    denom = wmat.sum(axis=1).replace(0, np.nan)
    wmat = wmat.div(denom, axis=0)
    return df.mul(wmat).sum(axis=1)


def build_aggregate(agg_cfg: dict, bundles: dict, period) -> dict | None:
    """Build one shared-currency aggregate (e.g. euro area) from member bundles.

    Sentiment is a GDP-weighted blend of member sentiment; the FX instrument is the
    shared currency pair (reused from a member's already-fetched series when present,
    else fetched live). Returns a CountryBundle-shaped dict, or None if no members.
    """
    cfg = settings.analysis_cfg()
    blend = agg_cfg.get("sentiment", {})
    members = [m for m in blend.get("members", []) if m in bundles]
    if not members:
        return None

    weights = {m: float((settings.country_by_id(m) or {}).get("gdp", 1.0)) for m in members}
    frames = {m: bundles[m]["analytical"].set_index(pd.to_datetime(bundles[m]["analytical"]["date"]))
              for m in members}

    def col(name):
        return _weighted_blend({m: frames[m][name] for m in members}, weights)

    blended = pd.DataFrame({
        "sentiment_mean": col("sentiment_mean"),
        "sentiment_median": col("sentiment_median"),
        "sentiment_positive_share": col("sentiment_positive_share"),
        "sentiment_neutral_share": col("sentiment_neutral_share"),
        "sentiment_negative_share": col("sentiment_negative_share"),
        "gdelt_tone_mean": col("gdelt_tone_mean"),
        "source_concentration": col("source_concentration"),
        "duplicate_rate": col("duplicate_rate"),
    })
    # renormalise the three shares so they sum to 1 (blend can drift a hair)
    shares = ["sentiment_positive_share", "sentiment_neutral_share", "sentiment_negative_share"]
    ssum = blended[shares].sum(axis=1).replace(0, np.nan)
    for s in shares:
        blended[s] = blended[s] / ssum
    # counts are summed across members
    blended["article_count"] = pd.DataFrame({m: frames[m]["article_count"] for m in members}).sum(axis=1)
    blended["source_count"] = pd.DataFrame({m: frames[m]["source_count"] for m in members}).sum(axis=1)

    # topic counts summed; topic sentiment recomputed count-weighted; keywords unioned
    from collections import Counter
    tcounts, tsent, kw = {}, {}, {}
    for d in blended.index:
        cc, sw, ww = Counter(), Counter(), Counter()
        kws = []
        for m in members:
            if d not in frames[m].index:
                continue
            row = frames[m].loc[d]
            mc = row["topic_counts"] if isinstance(row["topic_counts"], dict) else {}
            ms = row["topic_sentiment"] if isinstance(row["topic_sentiment"], dict) else {}
            for k, v in mc.items():
                cc[k] += v
                sw[k] += ms.get(k, 0.0) * v
                ww[k] += v
            if isinstance(row["keywords"], list):
                kws += row["keywords"]
        tcounts[d] = dict(cc)
        tsent[d] = {k: (sw[k] / ww[k]) for k in ww if ww[k]}
        kw[d] = [w for w, _ in Counter(kws).most_common(8)]
    blended["topic_counts"] = blended.index.map(tcounts)
    blended["topic_sentiment"] = blended.index.map(tsent)
    blended["keywords"] = blended.index.map(kw)
    blended["top_topics"] = blended["topic_counts"].map(
        lambda c: sorted(c, key=c.get, reverse=True)[:3] if isinstance(c, dict) else [])

    blended = blended.reset_index().rename(columns={"index": "date"})
    blended["date"] = pd.to_datetime(blended["date"]).dt.date
    blended = blended.sort_values("date").reset_index(drop=True)

    # events on the blended series; region/country/quality
    ev = cfg.get("event", {})
    blended = detect_events(blended, z_thresh=ev.get("z_thresh", 2.0), window=ev.get("window", 30))
    blended["region"] = agg_cfg.get("region")
    blended["country"] = agg_cfg["label"]
    blended["data_quality_score"] = float(np.nanmean(
        [bundles[m]["analytical"]["data_quality_score"].iloc[0] for m in members
         if not bundles[m]["analytical"].empty]))

    ordered = [
        "region", "country", "date", "article_count", "source_count", "duplicate_rate",
        "source_concentration", "sentiment_mean", "sentiment_median",
        "sentiment_positive_share", "sentiment_neutral_share", "sentiment_negative_share",
        "gdelt_tone_mean", "top_topics", "topic_counts", "topic_sentiment", "keywords",
        "event_flag", "event_score", "data_quality_score",
    ]
    analytical = blended[ordered]

    # articles: union of member articles (for word cloud / drill-down / summary)
    arts = [bundles[m]["articles"] for m in members if bundles[m].get("articles") is not None]
    articles = pd.concat(arts, ignore_index=True) if arts else pd.DataFrame()

    # instruments: shared-currency FX — reuse a member's series by source_id if present
    sent = _sentiment_series(analytical)
    instruments = {}
    for inst in agg_cfg.get("instruments", []):
        label, sid = inst["label"], inst["source_id"]
        meta = {"source": inst["source"], "source_id": sid, "series_type": inst["series_type"]}
        series = None
        for m in members:
            for e in bundles[m]["instruments"].values():
                if e.get("meta", {}).get("source_id") == sid and str(e.get("status", "")).startswith("ok"):
                    series = e["series"]
                    break
            if series is not None:
                break
        if series is None and settings.data_mode() == "live":
            from src.finance.market import fetch_series_with_status
            start, end = _period_bounds(period)
            df, status, _reason = fetch_series_with_status(inst, start, end)
            series = df if status == "ok" else None
        if series is not None and not series.empty:
            instruments[label] = ok_instrument(inst["type"], meta, series, sent, cfg)
        else:
            instruments[label] = unavailable_instrument(inst["type"], meta, "no member series")

    return {
        "country_id": agg_cfg["id"],
        "label": agg_cfg["label"],
        "region": agg_cfg.get("region"),
        "currency": agg_cfg.get("currency"),
        "monetary_regime": "floating",
        "peg_to": None,
        "label_note": "Shared-currency bloc — a GDP-weighted blend of member sentiment "
                      "vs the shared currency, not a country-specific series",
        "is_aggregate": True,
        "analytical": analytical,
        "articles": articles,
        "instruments": instruments,
        "source": bundles[members[0]].get("source", "demo"),
    }


def build_aggregates(bundles: dict, period=120) -> dict:
    """Build every configured aggregate from already-built country bundles."""
    out = {}
    for agg in settings.aggregates():
        try:
            b = build_aggregate(agg, bundles, period)
            if b is not None:
                out[agg["id"]] = b
        except Exception as exc:  # an aggregate never breaks the app
            log.exception("Failed to build aggregate %s: %s", agg.get("id"), exc)
    return out


# ── thin wrappers so the UI only ever imports pipeline.build_* + visualization ──
def build_comparison(bundles: dict, ids: list[str]) -> pd.DataFrame:
    """Cross-country comparison table (wraps analysis.comparison)."""
    from src.analysis.comparison import compare_countries

    return compare_countries(bundles, ids)


_MIN_N = 20  # below this the correlation is too thin to characterize → abstain


def _trend_word(sent: pd.Series) -> tuple[str, float]:
    """Deterministic trend label from recent vs prior window means."""
    s = sent.dropna()
    if len(s) < 6:
        return "steady", float(s.iloc[-1]) if len(s) else 0.0
    w = max(3, len(s) // 6)
    recent = float(s.iloc[-w:].mean())
    prior = float(s.iloc[-2 * w:-w].mean())
    delta = recent - prior
    word = "declining" if delta < -0.03 else ("rising" if delta > 0.03 else "steady")
    return word, recent


_SUMMARY_CACHE: dict = {}


def build_summary(bundle: dict, target_date=None) -> dict:
    """Structured-grounding summary (NOT RAG). Numbers are computed here in Python;
    the LLM only narrates. Returns evidence + deterministic facts + the validated
    contract. Cached per (country_id, date).
    """
    from src.nlp.summaries import summarize

    adf = bundle["analytical"]
    empty_payload = {"country": bundle.get("label"), "sentiment": None,
                     "instruments": [], "events": [], "top_topics": [], "headlines": []}
    if adf is None or adf.empty:
        contract = summarize(empty_payload, [], abstained=True)
        return {"evidence": empty_payload, "facts": [], **contract}

    # focal day: most recent flagged event, else the last day
    if target_date is None:
        flagged = adf[adf["event_flag"]]
        row = flagged.iloc[-1] if not flagged.empty else adf.iloc[-1]
    else:
        m = adf[pd.to_datetime(adf["date"]) == pd.to_datetime(target_date)]
        row = m.iloc[0] if not m.empty else adf.iloc[-1]
    d = row["date"]

    cache_key = f"{bundle.get('country_id')}:{d}"
    if cache_key in _SUMMARY_CACHE:
        return _SUMMARY_CACHE[cache_key]

    sent_series = adf.set_index(pd.to_datetime(adf["date"]))["sentiment_mean"]
    trend, latest_mean = _trend_word(sent_series)
    latest_mean = round(latest_mean, 3)

    # per-instrument computed facts (significance = |r| > band)
    inst_facts, inst_payload, abstained = [], [], False
    for label, entry in bundle.get("instruments", {}).items():
        if not str(entry.get("status", "")).startswith("ok") or not entry.get("correlation"):
            continue
        c = entry["correlation"]
        bl = c["best_lag"]
        lag, corr, n, band = bl["lag"], round(float(bl["corr"]), 2), int(c["n"]), round(float(c["band"]), 2)
        significant = abs(corr) > band
        inst_payload.append({"label": label, "best_lag": lag, "best_lag_corr": corr,
                             "n": n, "band": band, "significant": significant})
        if n < _MIN_N:
            abstained = True
            inst_facts.append(f"For {label}, the sample is too small (n={n}) to characterize the relationship.")
        else:
            direction = "lead" if lag > 0 else ("lag" if lag < 0 else "co-movement")
            verdict = "beyond" if significant else "within"
            inst_facts.append(
                f"Sentiment vs {label} peaks at a {abs(lag)}-day {direction} (r={corr}), "
                f"{verdict} the approximate ±{band} band (n={n})."
            )

    # events
    ev = adf[adf["event_flag"]]
    events_payload = [{"date": str(r["date"]), "z": round(float(r["event_score"]), 1)}
                      for _, r in ev.sort_values("event_score", ascending=False).head(3).iterrows()]
    event_facts = []
    if not ev.empty:
        maxz = round(float(ev["event_score"].max()), 1)
        event_facts.append(f"{int(len(ev))} unusual sentiment movement(s) were flagged (max |z|={maxz}).")

    # headlines with ids for the focal day
    arts = bundle.get("articles")
    heads = []
    if arts is not None and not arts.empty:
        day_arts = arts[pd.to_datetime(arts["date"]) == pd.to_datetime(d)].head(6)
        heads = [{"id": i + 1, "title": r["title"], "domain": r["domain"]}
                 for i, (_, r) in enumerate(day_arts.iterrows())]

    top_topics = row["top_topics"] if isinstance(row["top_topics"], list) else []
    sentiment_facts = [f"{bundle.get('label')} news sentiment is {trend} over the period "
                       f"(latest mean {latest_mean})."]
    if top_topics:
        sentiment_facts.append("Leading topics: " + ", ".join(map(str, top_topics)) + ".")

    facts = sentiment_facts + inst_facts + event_facts

    evidence = {
        "country": bundle.get("label"),
        "sentiment": {"mean": latest_mean, "trend": trend},
        "instruments": inst_payload,
        "events": events_payload,
        "top_topics": top_topics,
        "headlines": heads,
    }

    contract = summarize(evidence, facts, abstained=abstained)
    result = {"evidence": evidence, "facts": facts, "focal_date": str(d), **contract}
    _SUMMARY_CACHE[cache_key] = result
    return result


if __name__ == "__main__":  # `python -m src.pipeline` — live connector smoke test
    logging.basicConfig(level=logging.INFO)
    import src.settings as s

    print(f"DATA_MODE={s.data_mode()}")
    result = build_all(90)
    for cid, b in result.items():
        adf = b["analytical"]
        print(
            f"{cid}: {len(adf)} days, "
            f"{int(adf['article_count'].sum()) if not adf.empty else 0} articles, "
            f"instruments={list(b['instruments'])}"
        )
