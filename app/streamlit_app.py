"""Sentiment-Yield Engine — Streamlit UI.

Ground rule: this app imports ONLY `pipeline.build_*` and the `visualization/`
helpers (plus `settings` for config). All data reaches the UI through the
pipeline's output bundle — never ingest/, nlp/, or finance/ directly.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from src import pipeline, settings
from src.visualization import comparison as viz_cmp
from src.visualization import diagnostics as viz_diag
from src.visualization import geography as viz_geo
from src.visualization import market as viz_mkt
from src.visualization import sentiment as viz_sent
from src.visualization import topics as viz_top

st.set_page_config(page_title="Sentiment-Yield Engine", layout="wide")

VIEWS = ["Overview", "Country detail", "Compare & map",
         "Grounded summary", "Methodology"]
TYPE_LABEL = {"fx": "Currency (FX vs USD)", "index": "Equity index", "yield": "Yield"}
REGIME_ICON = {"floating": "🟢", "pegged": "🔵", "dollarized": "🟠", "unlinked": "⚪"}
REGIME_SHORT = {"floating": "Own currency", "pegged": "Pegged", "dollarized": "Dollarized",
                "unlinked": "Sentiment only"}
# UX Pass 3, Gap 3 — above this many selected entities, the overview's headline
# correlation section switches from one-card-per-country to a compact sortable
# table (the card layout is genuinely useful at small scale, unusable at 196).
HEADLINE_CARD_LIMIT = 10

HONESTY_NOTES = [
    "**Sentiment basis** — production sentiment is GDELT **average tone** on a *co-mention* "
    "basis (an article mentioning several countries counts toward each), via BigQuery — not VADER.",
    "**News sampling** — a *convenience sample* of available coverage, not a representative panel.",
    "**Themes** — the word cloud shows standardized GDELT themes (e.g. `ECON_INFLATION`), not article text.",
    "**Source concentration** — many articles ≠ broad coverage; HHI and source counts are shown.",
    "**Topic detection** — keyword groupings; they can misclassify.",
    "**Event detection** — a flag marks an *unusual data movement*, not a real-world cause.",
    "**Correlation** — measures association, **not** causation.",
    "**Lead/lag** — temporal association, not proof of causal precedence.",
    "**Statistical band** — `±1.96/√n` is *approximate* and unreliable under autocorrelation.",
    "**Shared currency** — euro members co-move with one ECB-set EUR/USD; not a country-specific FX effect.",
    "**LLM summaries** — narrate Python-computed facts; they can still err — never 'hallucination-free'.",
    "**Financial interpretation** — exploratory and educational; **not investment advice**.",
]

_CSS = """
<style>
  .block-container { padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1500px; }
  h1, h2, h3 { letter-spacing: -0.01em; }
  h1 { font-weight: 700; }
  div[data-testid="stSegmentedControl"] button { padding: 0.4rem 1.0rem; font-weight: 600; }
  div[data-testid="stSegmentedControl"] { margin-bottom: 0.4rem; }
  div[data-testid="stMetric"] {
    background: rgba(76,120,168,0.05); border: 1px solid rgba(76,120,168,0.18);
    border-radius: 12px; padding: 0.7rem 0.9rem;
  }
  div[data-testid="stMetricValue"] { font-size: 1.4rem; }
  div[data-testid="stAlert"] { border-radius: 12px; }
  .sidebar-footer {
    margin-top: 1rem;
    padding-top: 0.75rem;
    border-top: 1px solid rgba(255,255,255,0.25);
    font-size: 0.72rem;
    font-weight: 700;
    line-height: 1.45;
    color: inherit;
  }
</style>
"""


# ── data loading (cached; ttl for live) ──────────────────────────────────────
@st.cache_data(show_spinner="Building analytical bundles…", ttl=3600)
def load_country_bundles(mode: str, period: int) -> dict:
    """Cached country build. `mode` keys demo/live apart; ttl bounds live freshness."""
    return pipeline.build_all(period)


def _fmt(x, nd=3):
    try:
        if x is None or (isinstance(x, float) and x != x):
            return "—"
        return f"{x:.{nd}f}"
    except Exception:
        return "—"


def ok_instruments(entity: dict) -> dict:
    return {l: e for l, e in entity.get("instruments", {}).items()
            if str(e.get("status", "")).startswith("ok") and e.get("correlation")}


def first_ok(entity: dict):
    for l, e in ok_instruments(entity).items():
        return l, e
    return None, None


def regime_badge(entity: dict) -> str:
    """One-line, honest monetary-regime label — a feature, not an apology (§5)."""
    regime = entity.get("monetary_regime", "floating")
    icon = REGIME_ICON.get(regime, "🟢")
    note = entity.get("label_note", "Own currency")
    return f"{icon} **{note}**"


def capabilities(bundle: dict) -> dict:
    """What this bundle can actually render — the gate every visual checks (UX Pass 2, Part 1)."""
    adf = bundle["analytical"]
    has_sentiment = not adf.empty
    has_market = any(str(e.get("status", "")).startswith("ok")
                     for e in bundle.get("instruments", {}).values())
    return {"sentiment": has_sentiment, "market": has_market}


def no_market_note(entity: dict) -> None:
    """The one-line note every 'needs market' visual shows in place of a blank chart."""
    regime = entity.get("monetary_regime", "floating")
    regime_label = REGIME_SHORT.get(regime, "Own currency")
    st.info(f"No market series currently sourced for {entity['label']} ({regime_label}). "
            "Sentiment analysis below.")


def resolve_mode(mode: str, entities: dict) -> str:
    """Resolve the effective mode from the bundles' own `source` markers, so a
    snapshot-mode run that fell back to demo (missing file) reports honestly."""
    sources = {b.get("source") for b in entities.values()}
    if "snapshot" in sources:
        return "snapshot"
    if mode == "live" and "live" in sources:
        statuses = [e.get("status") for b in entities.values() for e in b.get("instruments", {}).values()]
        return "live (cached)" if any(s == "ok (cached)" for s in statuses) else "live"
    return "demo"


def sentiment_through(entity: dict):
    adf = entity["analytical"]
    return pd.to_datetime(adf["date"]).max().date() if not adf.empty else None


# ── sidebar selection ────────────────────────────────────────────────────────
regions = settings.regions()
all_countries = settings.countries()
region_label = {rid: r["label"] for rid, r in regions.items()}
country_label = {c["id"]: c["label"] for c in all_countries}
country_region = {c["id"]: c["region"] for c in all_countries}
_countries_by_region = {
    rid: [c["id"] for c in all_countries if c["region"] == rid] for rid in region_label
}


def _default_selection() -> set:
    """UX Pass 3, Gap 4 — at 196 countries, defaulting to "everything selected"
    means a 196-way render on first load. Default instead to entities that carry
    at least one real market instrument (the "headline" correlation story has
    something to show for them); the rest are one click away via "Select all"."""
    return {c["id"] for c in all_countries if c.get("instruments")}


def _region_widget_key(rid: str) -> str:
    return f"ms_region_{rid}"


def sidebar_selection():
    with st.sidebar:
        st.header("Controls")

        default_ids = _default_selection()
        for rid in region_label:
            key = _region_widget_key(rid)
            if key not in st.session_state:
                st.session_state[key] = [cid for cid in _countries_by_region[rid] if cid in default_ids]

        top1, top2 = st.columns(2)
        if top1.button("Select all", use_container_width=True):
            for rid in region_label:
                st.session_state[_region_widget_key(rid)] = list(_countries_by_region[rid])
            st.rerun()
        if top2.button("Select none", use_container_width=True):
            for rid in region_label:
                st.session_state[_region_widget_key(rid)] = []
            st.rerun()

        st.caption(f"Default selection: {len(default_ids)} of {len(all_countries)} countries "
                   "with a real market instrument (FX and/or index).")

        picked: list[str] = []
        for rid, label in region_label.items():
            key = _region_widget_key(rid)
            region_ids = _countries_by_region[rid]
            n_selected = len(st.session_state.get(key, []))
            with st.expander(f"{label} ({n_selected}/{len(region_ids)})", expanded=False):
                r1, r2 = st.columns(2)
                if r1.button("All", key=f"all_{rid}", use_container_width=True):
                    st.session_state[key] = list(region_ids)
                    st.rerun()
                if r2.button("None", key=f"none_{rid}", use_container_width=True):
                    st.session_state[key] = []
                    st.rerun()
                # Native multiselect — type-to-search within this region's countries
                # still works exactly as before, just scoped per region now.
                st.multiselect("Countries", region_ids, key=key, label_visibility="collapsed",
                               format_func=country_label.get)
            picked.extend(st.session_state.get(key, []))

        st.divider()
        period = st.pills("Period (days back)", [30, 60, 90, 180], default=90) or 90
    return picked, period


# ── instrument correlation panel (graceful degradation) ──────────────────────
def _instrument_panel(entity, label, entry, keyp):
    corr = entry["correlation"]
    bl = corr["best_lag"]
    band = corr["band"]
    significant = abs(bl["corr"]) > band if band == band else False
    # euro-area co-movement caveat
    if entry["type"] == "fx" and entity.get("currency") == "EUR" and not entity.get("is_aggregate"):
        st.caption("Co-movement with the **shared** euro (ECB/area-driven) — not a country-specific FX effect.")
    m = st.columns(4)
    m[0].metric("Pearson r", _fmt(corr["pearson"], 2))
    m[1].metric("Peak lag", f"{bl['lag']:+d}d", delta=f"r={_fmt(bl['corr'],2)}", delta_color="off")
    m[2].metric("Band ±1.96/√n", _fmt(band, 2))
    m[3].metric("Significant?", "yes" if significant else "no",
                help="|peak r| beyond the approximate band")
    if entry.get("status") == "ok (cached)":
        st.caption(f"Served from last-good cache (through {entry.get('last_updated')})")
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(viz_mkt.fig_sentiment_vs_market(entity["analytical"], entry["series"], label),
                        use_container_width=True, key=f"{keyp}_svm")
    with c2:
        st.plotly_chart(viz_mkt.fig_leadlag(corr["leadlag"], band, bl, label),
                        use_container_width=True, key=f"{keyp}_ll")


# ── views ────────────────────────────────────────────────────────────────────
def render_overview(entities: dict):
    st.subheader("Daily news sentiment by entity")
    st.plotly_chart(viz_sent.fig_cross_region_sentiment(entities, list(entities)),
                    use_container_width=True, key="ov_crossregion")

    st.subheader("The headline: sentiment × market correlation")
    st.caption("First available instrument per entity. `lag>0` → sentiment leads the market.")
    ids = list(entities)
    if len(ids) <= HEADLINE_CARD_LIMIT:
        cols = st.columns(min(4, len(ids)) or 1)
        for i, cid in enumerate(ids):
            b = entities[cid]
            caps = capabilities(b)
            label, entry = first_ok(b)
            with cols[i % len(cols)]:
                if not caps["market"] or not entry:
                    st.metric(b["label"], "—", help="no market data available")
                    st.caption(regime_badge(b))
                    continue
                corr = entry["correlation"]; bl = corr["best_lag"]
                tag = " ·bloc" if b.get("is_aggregate") else ""
                st.metric(f"{b['label']}{tag} · {label}", f"r={_fmt(corr['pearson'],2)}",
                          delta=f"peak lag {bl['lag']} (r={_fmt(bl['corr'],2)})", delta_color="off")
                st.caption(f"n={corr['n']}, band ±{_fmt(corr['band'],2)}")
    else:
        # too many entities for cards to be usable — a compact, sortable table with
        # the map (Compare & map) staying as the primary overview visual at this scale.
        table = pipeline.build_comparison(entities, ids)
        if not table.empty:
            show = table.copy()
            show["Region"] = show["region"].map(region_label).fillna(show["region"])
            show = show.rename(columns={
                "country": "Entity", "sentiment_mean": "Sentiment",
                "market": "Best instrument", "pearson": "r", "best_lag": "Lag"})
            show = show[["Entity", "Region", "Sentiment", "Best instrument", "r", "Lag"]]
            st.dataframe(show.sort_values("Sentiment", ascending=False, na_position="last"),
                        use_container_width=True, hide_index=True, height=420,
                        column_config={
                            "Sentiment": st.column_config.NumberColumn(format="%.3f"),
                            "r": st.column_config.NumberColumn(format="%.2f")})
        st.caption(f"{len(ids)} entities selected — showing a sortable table above the "
                   f"{HEADLINE_CARD_LIMIT}-country card threshold. See Compare & map for the world view.")

    focus = st.selectbox("Show lead/lag detail for", ids, format_func=lambda cid: entities[cid]["label"])
    focus_entity = entities[focus]
    caps = capabilities(focus_entity)
    label, entry = first_ok(focus_entity)
    if caps["market"] and entry:
        corr = entry["correlation"]; bl = corr["best_lag"]
        st.markdown(f"**Lead/lag — {focus_entity['label']} · {label}**")
        st.caption(f"Peak at lag {bl['lag']} (r={_fmt(bl['corr'],2)}) · n={corr['n']} · band ±{_fmt(corr['band'],2)}")
        st.plotly_chart(viz_mkt.fig_leadlag(corr["leadlag"], corr["band"], bl, label),
                        use_container_width=True, key=f"ov_leadlag_{focus}")
    else:
        no_market_note(focus_entity)


def render_country_detail(entities: dict):
    ids = list(entities)
    dcid = st.selectbox("Entity", ids, format_func=lambda cid: entities[cid]["label"], key="detail_entity")
    b = entities[dcid]
    adf = b["analytical"]
    caps = capabilities(b)
    st.markdown(regime_badge(b))

    # Fix 1 — degrade, don't crash, when a country ingested no sentiment (GDELT
    # returned nothing or was rate-limited). Everything downstream needs the
    # sentiment spine, so show a legible notice + instrument availability and stop.
    if adf.empty:
        st.info(f"**{b['label']}** — no news sentiment ingested for this period "
                "(GDELT returned nothing, or the pull was rate-limited). Market series "
                "and correlations need the sentiment spine, so they're unavailable here. "
                "See the Run diagnostics panel for details.")
        for l, e in b.get("instruments", {}).items():
            st.caption(f"· {l} ({e.get('type')}): {e.get('status','unavailable')}"
                       + (f" — {e.get('reason')}" if e.get("reason") else ""))
        return

    m = st.columns(4)
    m[0].metric("Articles", int(adf["article_count"].sum()) if not adf.empty else 0)
    m[1].metric("Sources (max/day)",
                int(adf["source_count"].max()) if not adf.empty and adf["source_count"].notna().any() else 0)
    m[2].metric("Events flagged", int(adf["event_flag"].sum()) if not adf.empty else 0)
    m[3].metric("Data-quality", f"{_fmt(adf['data_quality_score'].iloc[0],1)}/100" if not adf.empty else "—")

    # split-freshness label
    fresh = [f"sentiment through {sentiment_through(b)}"]
    for l, e in b.get("instruments", {}).items():
        if e.get("last_updated"):
            fresh.append(f"{l} through {e['last_updated']}")
    st.caption("Freshness: " + "  ·  ".join(fresh))

    oks = ok_instruments(b)
    unavailable = {l: e for l, e in b.get("instruments", {}).items() if l not in oks}

    if not caps["market"]:
        no_market_note(b)
    else:
        # grouped FX vs index vs yield; one correlation panel per ok instrument
        by_type: dict[str, list] = {}
        for l, e in oks.items():
            by_type.setdefault(e["type"], []).append((l, e))
        for t in ("fx", "index", "yield"):
            for l, e in by_type.get(t, []):
                st.markdown(f"#### {TYPE_LABEL.get(t, t)} — {l}")
                _instrument_panel(b, l, e, keyp=f"d_{dcid}_{l}")
    for l, e in unavailable.items():
        st.warning(f"**{l}** ({TYPE_LABEL.get(e.get('type'), e.get('type'))}) temporarily "
                   f"unavailable — {e.get('reason','')}.")

    # rolling corr + deeper analysis on the first ok instrument
    label, entry = first_ok(b)
    st.markdown("#### Deeper analysis")
    tabs = st.tabs(["Rolling correlation", "Scatter + regression", "VADER vs GDELT tone", "Events", "Sentiment split"])
    rw = settings.analysis_cfg().get("correlation", {}).get("rolling_window", 30)
    with tabs[0]:
        if caps["market"] and entry:
            st.plotly_chart(viz_mkt.fig_rolling_corr(entry["correlation"]["rolling"], rw, label),
                            use_container_width=True, key=f"d_roll_{dcid}")
        else:
            no_market_note(b)
    with tabs[1]:
        if caps["market"] and entry and caps["sentiment"]:
            sent = adf.set_index(pd.to_datetime(adf["date"]))["sentiment_mean"]
            s = entry["series"]; mkt = s.set_index(pd.to_datetime(s["date"]))["value"]
            c = entry["correlation"]
            st.caption(f"r={_fmt(c['pearson'],2)} · ρ={_fmt(c['spearman'],2)} · n={c['n']}")
            st.plotly_chart(viz_mkt.fig_scatter_regression(sent, mkt, c, label),
                            use_container_width=True, key=f"d_scatter_{dcid}")
        else:
            no_market_note(b)
    with tabs[2]:
        if not adf.empty:
            st.plotly_chart(viz_sent.fig_vader_vs_gdelt(adf, b["label"]),
                            use_container_width=True, key=f"d_vg_{dcid}")
        else:
            st.caption("No sentiment data.")
    with tabs[3]:
        if not adf.empty:
            st.plotly_chart(viz_sent.fig_sentiment_timeline(adf, b["label"]),
                            use_container_width=True, key=f"d_tl_{dcid}")
        else:
            st.caption("No sentiment data.")
    with tabs[4]:
        if not adf.empty:
            st.plotly_chart(viz_diag.fig_sentiment_split(adf), use_container_width=True, key=f"d_split_{dcid}")
        else:
            st.caption("No sentiment data.")

    st.divider()
    st.markdown("#### News landscape")
    # UX Pass 2, Part 3 — word cloud gets more than half the row (was a plain 2-way
    # split) and a taller rendered image (topics.py bumped to 1200x600), so it reads
    # as a headline visual rather than a cramped thumbnail.
    left, right = st.columns([3, 2])
    with left:
        themes = b.get("themes")
        if themes is not None and not themes.empty:
            st.caption("Word cloud (GDELT themes)")
            img = viz_top.wordcloud_from_themes(themes)
        else:
            st.caption("Word cloud (TF-IDF over titles)")
            img = viz_top.wordcloud_image(b["articles"])
        if img is not None:
            st.image(img, use_container_width=True)
        else:
            st.info("No keywords/themes for this entity.")
    with right:
        st.caption("Topic mention counts")
        st.plotly_chart(viz_top.fig_topic_bars(adf), use_container_width=True, key=f"d_tbar_{dcid}")
    st.caption("Per-topic sentiment")
    st.plotly_chart(viz_top.fig_topic_sentiment(adf), use_container_width=True, key=f"d_tsent_{dcid}")

    st.markdown("#### Data quality & source structure")
    q1, q2 = st.columns([1, 2])
    with q1:
        st.plotly_chart(viz_diag.fig_quality_gauge(adf["data_quality_score"].iloc[0] if not adf.empty else 0),
                        use_container_width=True, key=f"d_gauge_{dcid}")
    with q2:
        st.plotly_chart(viz_diag.fig_source_concentration(b["articles"]),
                        use_container_width=True, key=f"d_src_{dcid}")

    st.markdown("#### Headline drill-down")
    arts = b["articles"]
    if arts is not None and not arts.empty:
        days = sorted(pd.to_datetime(arts["date"]).dt.date.unique())
        pick = st.select_slider("Day", options=days, value=days[-1]) if len(days) > 1 else days[0]
        day_arts = arts[pd.to_datetime(arts["date"]).dt.date == pick].copy()
        day_arts = day_arts[["title", "domain", "topic", "vader", "url"]].sort_values("vader")
        st.caption(f"{len(day_arts)} headlines on {pick}")
        st.dataframe(day_arts, use_container_width=True, hide_index=True)


def render_compare(entities: dict):
    # UX Pass 2, Part 3 — the map is the strongest visual for a many-country tool;
    # it now leads the view (was below the table) so it registers on first glance.
    st.subheader("Sentiment map")
    layer = st.segmented_control("Map layer", ["Sentiment", "FX correlation", "Index correlation"],
                                 default="Sentiment", key="map_layer") or "Sentiment"
    rows = _map_rows(entities, layer)
    if layer == "Sentiment":
        st.plotly_chart(viz_geo.fig_metric_map(rows, "sentiment"), use_container_width=True, key="cmp_map")
    else:
        want = "fx" if layer.startswith("FX") else "index"
        st.plotly_chart(viz_geo.fig_metric_map(rows, "corr", scale="RdBu"),
                        use_container_width=True, key=f"cmp_map_{want}")
        if want == "fx":
            st.caption("Euro-area members share one EUR/USD (ECB-set) — shown per country but a single currency signal.")

    st.divider()
    st.subheader("Cross-country comparison")
    table = pipeline.build_comparison(entities, list(entities))
    if not table.empty:
        table = table.copy()
        table["Regime"] = table["monetary_regime"].map(
            lambda r: f"{REGIME_ICON.get(r, '🟢')} {REGIME_SHORT.get(r, 'Own currency')}")
        show = table.drop(columns=["country_id", "is_aggregate", "monetary_regime", "label_note"]).rename(columns={
            "country": "Entity", "region": "Region", "sentiment_mean": "Sentiment",
            "articles": "Articles", "sources": "Sources", "events": "Events",
            "avg_quality": "Quality", "market": "Spine", "pearson": "r", "best_lag": "Lag",
            "fx_r": "FX r", "fx_lag": "FX lag", "index_r": "Index r", "index_lag": "Index lag"})
        st.dataframe(show, use_container_width=True, hide_index=True, column_config={
            "Sentiment": st.column_config.NumberColumn(format="%.3f"),
            "r": st.column_config.NumberColumn(format="%.2f"),
            "FX r": st.column_config.NumberColumn(format="%.2f"),
            "Index r": st.column_config.NumberColumn(format="%.2f"),
            "Quality": st.column_config.NumberColumn(format="%.0f")})
        metric = st.selectbox("Compare metric", ["sentiment_mean", "articles", "sources", "events", "fx_r", "index_r"])
        st.plotly_chart(viz_cmp.fig_comparison_bars(table, metric), use_container_width=True, key="cmp_bars")


def _map_rows(entities, layer):
    import numpy as np
    rows = []
    for cid, b in entities.items():
        if b.get("is_aggregate"):
            continue  # blocs annotated separately; not painted per-country
        cfg = settings.country_by_id(cid) or {}
        iso3 = cfg.get("iso3")
        if layer == "Sentiment":
            adf = b["analytical"]
            val = float(np.nanmean(adf["sentiment_mean"])) if not adf.empty else np.nan
        else:
            want = "fx" if layer.startswith("FX") else "index"
            val = np.nan
            for e in b.get("instruments", {}).values():
                if e.get("type") == want and str(e.get("status", "")).startswith("ok") and e.get("correlation"):
                    val = e["correlation"]["pearson"]; break
        rows.append({"iso3": iso3, "country": b["label"], "value": val,
                    "regime_note": b.get("label_note", "Own currency")})
    return rows


def render_summary(entities: dict):
    st.subheader("Grounded explanation (structured, not RAG)")
    st.caption("Every number is computed in Python and passed to the model as fixed facts; "
               "the LLM only narrates. Output is validated — unsupported numbers or citations "
               "fall back to the deterministic facts. Works fully without a key.")
    scid = st.selectbox("Entity", list(entities), format_func=lambda cid: entities[cid]["label"], key="sum_entity")
    result = pipeline.build_summary(entities[scid])
    ev = result["evidence"]

    badge = "grounded (LLM, validated)" if result.get("grounded") else "deterministic (facts only)"
    if result.get("abstained"):
        badge += " · abstained (small sample)"
    st.markdown(f"**Status:** {badge}  ·  focal day {result.get('focal_date','—')}")

    st.markdown("**Computed facts (the ground truth)**")
    for f in result.get("facts", []):
        st.markdown("- " + f)

    st.markdown("**Narrative**")
    st.write(result.get("summary", ""))
    if result.get("caveats"):
        for c in result["caveats"]:
            st.caption(c)
    if result.get("cited_headline_ids"):
        cited = {h["id"]: h for h in ev.get("headlines", [])}
        st.caption("Cited headlines: " + " · ".join(
            f"[{i}] {cited[i]['title']}" for i in result["cited_headline_ids"] if i in cited))

    with st.expander("Structured evidence payload (JSON)", expanded=False):
        st.json(ev)


def render_methodology(_entities: dict):
    st.subheader("Methodology — exact definitions")
    st.markdown(
        "- **Sentiment signal (production/snapshot):** GDELT **average tone** per country-day "
        "(from BigQuery `gkg_partitioned`), normalised to ±1. Daily polarity: tone > +0.5 positive, "
        "< −0.5 negative, else neutral. (Demo/legacy-live paths use VADER ±0.05 on titles.)\n"
        "- **Events:** rolling-30 z-score; flag when `|z_sentiment| ≥ 2` **or** volume `z ≥ 2`. `event_score=|z|`.\n"
        "- **Source concentration (HHI):** `Σ pᵢ²`, normalized 0–1 (higher = fewer voices).\n"
        "- **Data-quality (0–100):** weighted blend of volume, diversity (1−HHI), duplicate "
        "cleanliness, coverage, scoring success — a *diagnostic*, not a confidence interval.\n"
        "- **Correlation band:** approximate 95% band at `±1.96/√n` (unreliable under autocorrelation).\n"
        "- **Lead/lag:** `lag>0` → sentiment leads market `corr(sentiment_t, return_{t+lag})`.\n"
        "- **Market model:** FX-vs-USD (FRED, ~weekly) is the spine; national equity index "
        "(Twelve Data, daily) is a country-specific overlay; US uses its index + 10Y yield."
    )
    st.subheader("Honesty notes (the point, not fine print)")
    for note in HONESTY_NOTES:
        st.markdown("- " + note)


def _diagnostics_rows_live(entities: dict) -> list[dict]:
    """Live/live(cached) mode: the GDELT HTTP trace (artlist/tone status+error)."""
    rows = []
    for cid, b in entities.items():
        d = b.get("diag") or {}
        adf = b.get("analytical")
        arts = b.get("articles")
        art = d.get("artlist") or {}
        tone = d.get("tone") or {}
        kept = d.get("articles_kept",
                     int(len(arts)) if arts is not None and not arts.empty else 0)
        days = d.get("distinct_days",
                     int(pd.to_datetime(adf["date"]).nunique()) if adf is not None and not adf.empty else 0)
        insts = d.get("instruments") or {
            l: {"source": e.get("meta", {}).get("source"), "symbol": e.get("meta", {}).get("source_id"),
                "status": e.get("status"), "reason": e.get("reason"),
                "rows": (0 if e.get("series") is None else int(len(e["series"])))}
            for l, e in b.get("instruments", {}).items()}
        rows.append({
            "entity": b["label"],
            "code": d.get("gdelt_country_code", "—"),
            "artlist_http": art.get("http_status", "—"),
            "artlist_error": art.get("error") or "",
            "articles_kept": kept,
            "distinct_days": days,
            "tone_http": tone.get("http_status", "—"),
            "tone_error": tone.get("error") or "",
            "tone_rows": tone.get("n_rows", "—"),
            "instruments": "; ".join(
                f"{l}[{v.get('symbol')}]:{v.get('status')}({v.get('rows')})"
                + (f"/{v['reason']}" if v.get("reason") else "")
                for l, v in insts.items()),
        })
    return rows


def _diagnostics_rows_snapshot(entities: dict) -> list[dict]:
    """Snapshot/demo mode: nothing was fetched live, so show what the snapshot/bundle
    actually holds — sentiment rows, distinct days, last refresh, instrument
    availability, and the regime label — not a live-fetch trace that never ran."""
    rows = []
    for cid, b in entities.items():
        d = b.get("diag") or {}
        adf = b.get("analytical")
        regime = b.get("monetary_regime", "floating")
        insts = d.get("instruments") or {
            l: {"symbol": e.get("meta", {}).get("source_id"), "status": e.get("status"),
                "reason": e.get("reason"),
                "rows": (0 if e.get("series") is None else int(len(e["series"])))}
            for l, e in b.get("instruments", {}).items()}
        rows.append({
            "entity": b["label"],
            "regime": f"{REGIME_ICON.get(regime, '🟢')} {REGIME_SHORT.get(regime, 'Own currency')}",
            "sentiment_rows": d.get("sentiment_rows",
                                    int(len(adf)) if adf is not None and not adf.empty else 0),
            "distinct_days": d.get("distinct_days",
                                   int(pd.to_datetime(adf["date"]).nunique())
                                   if adf is not None and not adf.empty else 0),
            "last_refresh": d.get("refreshed_at") or "—",
            "instruments": "; ".join(
                f"{l}[{v.get('symbol')}]:{v.get('status')}"
                + (f"/{v['reason']}" if v.get("reason") else "")
                for l, v in insts.items()) or "none",
        })
    return rows


def render_diagnostics(entities: dict, rmode: str):
    """Behind-the-scenes recorder — shape depends on where the data actually came
    from (§Bug 2): live modes show the real GDELT HTTP trace; snapshot/demo modes
    (nothing fetched live) show snapshot-relevant info instead of a wall of dashes.
    The JSON download is always the complete per-entity `diag` artifact.
    """
    import json

    is_live = rmode in ("live", "live (cached)")
    rows = _diagnostics_rows_live(entities) if is_live else _diagnostics_rows_snapshot(entities)
    full = {cid: (b.get("diag") or {"note": "no diag recorded"}) for cid, b in entities.items()}

    label = "full GDELT trace + instrument outcomes" if is_live else "snapshot coverage + instrument outcomes"
    with st.expander(f"🔧 Run diagnostics ({label})"):
        if is_live:
            st.caption("Live builds also log `BUILD DIAG …` to Streamlit Cloud → Manage app → logs. "
                       "`artlist_http`/`tone_http` show the actual GDELT HTTP status (429 = rate-limited, "
                       "200 with 0 articles = query returned nothing).")
        else:
            st.caption("No live GDELT fetch runs in this mode — this reflects what's actually stored "
                       "(snapshot/demo), not a fetch trace. `instruments` shows each series' resolved "
                       "status (ok / unavailable + reason).")
        st.dataframe(rows, use_container_width=True, hide_index=True)
        st.download_button("Download full diagnostics JSON",
                           data=json.dumps(full, indent=2, default=str),
                           file_name="run_diagnostics.json", mime="application/json")


RENDERERS = {VIEWS[0]: render_overview, VIEWS[1]: render_country_detail,
             VIEWS[2]: render_compare, VIEWS[3]: render_summary, VIEWS[4]: render_methodology}


# ── app body ─────────────────────────────────────────────────────────────────
def main():
    st.markdown(_CSS, unsafe_allow_html=True)
    st.title("Sentiment-Yield Engine")
    st.caption(
        "Open regional **news-sentiment × financial-market** observatory. When a region's news "
        "turns more positive or negative, do local markets move with it, and at what lead/lag? "
        "**An observatory — not a predictor, trading system, or investment advice.**")

    mode = settings.data_mode()
    picked, period = sidebar_selection()
    if not picked:
        st.warning("Select at least one country in the sidebar.")
        st.stop()

    countries = load_country_bundles(mode, period)
    picked_countries = {cid: countries[cid] for cid in picked if cid in countries}
    aggregates = pipeline.build_aggregates(picked_countries, period)
    entities = {**picked_countries, **aggregates}
    if not entities:
        st.error("No bundles were built for the current selection.")
        st.stop()

    rmode = resolve_mode(mode, entities)
    with st.sidebar:
        st.divider()
        st.caption(f"Resolved mode: **{rmode}**")
        st.markdown(
            "<div class='sidebar-footer'>"
            "<strong>Built by Etienne Landry B.<br>email: etienne.landry.bessala@gmail.com</strong>"
            "</div>",
            unsafe_allow_html=True,
        )

    # resolved-mode banner (demo-only text hidden when not demo)
    if rmode == "demo":
        st.info("DEMO mode — synthetic data, no keys/network/DB. A 2-day sentiment→market lead "
                "is planted so the lead/lag panel has a real peak.  ·  Correlation ≠ causation; band approximate.")
    elif rmode == "snapshot":
        st.info("SNAPSHOT mode — reading stored `data/snapshot` (backfilled + refreshed daily out of "
                "band); no live GDELT on the request path. The daily sentiment signal here is GDELT's "
                "own tone.  ·  Correlation ≠ causation; the ±1.96/√n band is approximate.")
    elif rmode == "live (cached)":
        st.info("LIVE (cached) — some instruments served from last-good.  ·  Correlation ≠ causation; band approximate.")
    else:
        st.info("LIVE data mode.  ·  Correlation ≠ causation; the ±1.96/√n band is approximate.")

    render_diagnostics(entities, rmode)

    view = st.segmented_control("View", VIEWS, default=VIEWS[0], label_visibility="collapsed") or VIEWS[0]
    st.divider()
    RENDERERS[view](entities)


main()
