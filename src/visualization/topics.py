"""Topic figures + word cloud."""
from __future__ import annotations

from collections import Counter

import pandas as pd
import plotly.graph_objects as go

from src.nlp.keywords import top_keywords
from src.visualization.theme import NEG, POS, apply


def _period_topic_counts(analytical: pd.DataFrame) -> Counter:
    counts: Counter = Counter()
    for d in analytical.get("topic_counts", []):
        if isinstance(d, dict):
            counts.update(d)
    return counts


def _period_topic_sentiment(analytical: pd.DataFrame) -> dict:
    sums: Counter = Counter()
    weights: Counter = Counter()
    for tc, ts in zip(analytical.get("topic_counts", []), analytical.get("topic_sentiment", [])):
        if isinstance(tc, dict) and isinstance(ts, dict):
            for k, c in tc.items():
                sums[k] += ts.get(k, 0.0) * c
                weights[k] += c
    return {k: sums[k] / weights[k] for k in weights if weights[k]}


def fig_topic_bars(analytical: pd.DataFrame, top: int = 10) -> go.Figure:
    """Mention counts per topic across the period."""
    fig = go.Figure()
    counts = _period_topic_counts(analytical)
    if not counts:
        return apply(fig, title="No topics")
    items = counts.most_common(top)
    labels = [k for k, _ in items][::-1]
    values = [v for _, v in items][::-1]
    fig.add_trace(go.Bar(x=values, y=labels, orientation="h", marker_color="#4C78A8",
                         hovertemplate="%{y}: %{x} mentions<extra></extra>"))
    fig.update_xaxes(title="mentions")
    return apply(fig, hover="closest")


def fig_topic_sentiment(analytical: pd.DataFrame, top: int = 10) -> go.Figure:
    """Average sentiment per topic (green ≥0, red <0)."""
    fig = go.Figure()
    tsent = _period_topic_sentiment(analytical)
    counts = _period_topic_counts(analytical)
    if not tsent:
        return apply(fig, title="No topics")
    ordered = [k for k, _ in counts.most_common(top) if k in tsent][::-1]
    vals = [tsent[k] for k in ordered]
    colors = [POS if v >= 0 else NEG for v in vals]
    fig.add_trace(go.Bar(x=vals, y=ordered, orientation="h", marker_color=colors,
                         hovertemplate="%{y}: %{x:.3f}<extra></extra>"))
    fig.add_vline(x=0, line_color="rgba(128,128,128,0.5)")
    fig.update_xaxes(title="mean sentiment")
    return apply(fig, hover="closest")


def _render_cloud(freqs: dict):
    from wordcloud import WordCloud

    if not freqs:
        return None
    # UX Pass 2, Part 3 — rendered at a higher pixel resolution so it stays sharp
    # when stretched to fill a wide column (use_container_width) instead of
    # upscaling a small bitmap and reading blurry / needing a browser zoom.
    wc = WordCloud(
        width=1200, height=600, background_color=None, mode="RGBA",
        colormap="viridis", prefer_horizontal=0.9,
    ).generate_from_frequencies(freqs)
    return wc.to_image()


def wordcloud_image(articles: pd.DataFrame, n: int = 60):
    """Word cloud from article-title keywords (TF-IDF). Returns a PIL image or None."""
    pairs = top_keywords(articles, n=n)
    return _render_cloud({t: w for t, w in pairs}) if pairs else None


def wordcloud_from_themes(themes: pd.DataFrame, n: int = 60):
    """Word cloud from GDELT theme frequencies (snapshot mode).

    Standardised themes (e.g. ECON_INFLATION) — no stop-word noise, no article text.
    Returns a PIL image or None.
    """
    if themes is None or themes.empty or "theme" not in themes:
        return None
    df = themes.copy()
    # Defensive: GDELT's raw V2Themes entries are "THEME_NAME,charoffset". The
    # BigQuery query (src/ingest/gdelt_bq.py) now strips this at the source, but
    # snapshots written before that fix still carry the offset glued to the theme
    # name (e.g. "TAX_WORLDLANGUAGES_AZERBAIJAN,16") — strip it here too so
    # already-stored data renders correctly without requiring a fresh backfill.
    # The groupby+sum below then correctly re-merges what were spurious
    # theme+offset fragments of the same real theme.
    theme_name = df["theme"].astype(str).str.split(",", n=1).str[0]
    df["label"] = theme_name.str.replace("_", " ").str.title()
    df = df.groupby("label")["count"].sum().sort_values(ascending=False).head(n)
    return _render_cloud(df.to_dict())
