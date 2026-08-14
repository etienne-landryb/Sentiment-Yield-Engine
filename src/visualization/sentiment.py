"""Sentiment figures: cross-region lines, per-country timeline w/ event markers."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from src.visualization.theme import ACCENT, NEG, PALETTE, apply


def fig_cross_region_sentiment(bundles: dict, ids: list[str]) -> go.Figure:
    """One sentiment_mean line per selected country — the headline overview."""
    fig = go.Figure()
    for i, cid in enumerate(ids):
        b = bundles.get(cid)
        if not b or b["analytical"].empty:
            continue
        adf = b["analytical"]
        fig.add_trace(
            go.Scatter(
                x=pd.to_datetime(adf["date"]),
                y=adf["sentiment_mean"],
                mode="lines",
                name=b["label"],
                line=dict(color=PALETTE[i % len(PALETTE)], width=2),
            )
        )
    fig.add_hline(y=0, line_dash="dot", line_color="rgba(128,128,128,0.5)")
    fig.update_yaxes(title="Mean VADER compound (−1…+1)")
    return apply(fig, height=380, title="Daily news sentiment by country")


def fig_sentiment_timeline(analytical: pd.DataFrame, label: str = "") -> go.Figure:
    """A single country's sentiment line with event markers (README event rule)."""
    fig = go.Figure()
    if analytical is None or analytical.empty:
        return apply(fig, title="No data")
    x = pd.to_datetime(analytical["date"])
    fig.add_trace(
        go.Scatter(
            x=x, y=analytical["sentiment_mean"], mode="lines",
            name="Sentiment", line=dict(color=ACCENT, width=2),
        )
    )
    ev = analytical[analytical["event_flag"]]
    if not ev.empty:
        fig.add_trace(
            go.Scatter(
                x=pd.to_datetime(ev["date"]),
                y=ev["sentiment_mean"],
                mode="markers",
                name="Event (|z|≥2)",
                marker=dict(color=NEG, size=11, symbol="diamond",
                            line=dict(color="white", width=1)),
                customdata=ev["event_score"],
                hovertemplate="%{x|%Y-%m-%d}<br>sentiment %{y:.3f}"
                              "<br>|z|=%{customdata:.2f}<extra>event</extra>",
            )
        )
    fig.add_hline(y=0, line_dash="dot", line_color="rgba(128,128,128,0.5)")
    fig.update_yaxes(title="Mean VADER compound")
    return apply(fig, title=f"Sentiment & detected events — {label}".strip(" —"))


def fig_vader_vs_gdelt(analytical: pd.DataFrame, label: str = "") -> go.Figure:
    """VADER (titles) vs GDELT's own tone — two independent sentiment measures."""
    fig = go.Figure()
    if analytical is None or analytical.empty:
        return apply(fig, title="No data")
    x = pd.to_datetime(analytical["date"])
    fig.add_trace(go.Scatter(x=x, y=analytical["sentiment_mean"], name="VADER (titles)",
                             line=dict(color=ACCENT, width=2)))
    if analytical["gdelt_tone_mean"].notna().any():
        fig.add_trace(go.Scatter(x=x, y=analytical["gdelt_tone_mean"], name="GDELT tone",
                                 yaxis="y2", line=dict(color=PALETTE[1], width=2)))
        fig.update_layout(yaxis2=dict(title="GDELT tone", overlaying="y",
                                      side="right", showgrid=False))
    fig.update_layout(yaxis_title="VADER compound")  # primary axis only
    return apply(fig)
