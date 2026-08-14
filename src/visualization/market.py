"""Market + correlation figures — the headline analytical layer.

Sentiment-vs-market dual axis, lead/lag bars with the ±1.96/√n band, rolling
correlation, and the scatter with an OLS regression line.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from src.visualization.theme import ACCENT, NEG, PALETTE, POS, apply


def fig_sentiment_vs_market(
    analytical: pd.DataFrame, series: pd.DataFrame, market_label: str
) -> go.Figure:
    """Dual-axis: daily sentiment (left) vs the market series (right)."""
    fig = go.Figure()
    if analytical is None or analytical.empty:
        return apply(fig, title="No data")
    fig.add_trace(
        go.Scatter(
            x=pd.to_datetime(analytical["date"]), y=analytical["sentiment_mean"],
            name="Sentiment", line=dict(color=ACCENT, width=2),
        )
    )
    if series is not None and not series.empty:
        fig.add_trace(
            go.Scatter(
                x=pd.to_datetime(series["date"]), y=series["value"],
                name=market_label, yaxis="y2",
                line=dict(color=PALETTE[1], width=2),
            )
        )
        fig.update_layout(
            yaxis2=dict(title=market_label, overlaying="y", side="right", showgrid=False)
        )
    # Set only the primary y-axis title (update_yaxes would overwrite yaxis2 too).
    fig.update_layout(yaxis_title="Sentiment (VADER)")
    return apply(fig)


def fig_leadlag(cc: pd.DataFrame, band: float, best: dict, market_label: str = "") -> go.Figure:
    """Lead/lag cross-correlation bars with the approximate ±1.96/√n band.

    lag>0 → sentiment leads the market; lag<0 → market leads sentiment.
    """
    fig = go.Figure()
    if cc is None or cc.empty:
        return apply(fig, title="No data")
    colors = [POS if l == best.get("lag") else "rgba(76,120,168,0.55)" for l in cc["lag"]]
    fig.add_trace(
        go.Bar(x=cc["lag"], y=cc["corr"], marker_color=colors, name="corr",
               hovertemplate="lag %{x}<br>corr %{y:.3f}<extra></extra>")
    )
    if band is not None and not np.isnan(band):
        # Tier 1.2: explicit text (no stray "new text"), positioned INSIDE the plot.
        fig.add_hline(y=band, line_dash="dash", line_color=NEG,
                      annotation_text="+1.96/√n", annotation_position="top left")
        fig.add_hline(y=-band, line_dash="dash", line_color=NEG,
                      annotation_text="−1.96/√n", annotation_position="bottom left")
    fig.add_vline(x=0, line_color="rgba(128,128,128,0.5)")
    fig.update_xaxes(title="lag (days) — positive = sentiment leads", dtick=1)
    fig.update_yaxes(title="cross-correlation")
    return apply(fig, hover="closest")


def fig_rolling_corr(rolling: pd.Series, window: int, market_label: str = "") -> go.Figure:
    """Rolling contemporaneous correlation over time."""
    fig = go.Figure()
    if rolling is None or rolling.dropna().empty:
        return apply(fig, title="No rolling correlation (insufficient overlap)")
    r = rolling.dropna()
    fig.add_trace(go.Scatter(x=pd.to_datetime(r.index), y=r.values, mode="lines",
                             line=dict(color=ACCENT, width=2), name="rolling r"))
    fig.add_hline(y=0, line_dash="dot", line_color="rgba(128,128,128,0.5)")
    fig.update_yaxes(title="correlation", range=[-1, 1])
    return apply(fig, title=f"Rolling correlation ({window}d) — {market_label}".strip(" —"))


def fig_scatter_regression(
    sent: pd.Series, mkt: pd.Series, stats: dict, market_label: str = ""
) -> go.Figure:
    """Sentiment vs market scatter with the OLS regression line."""
    fig = go.Figure()
    df = pd.DataFrame({"sent": sent, "mkt": mkt}).dropna()
    if df.empty:
        return apply(fig, title="No overlapping data")
    fig.add_trace(
        go.Scatter(x=df["sent"], y=df["mkt"], mode="markers", name="days",
                   marker=dict(color=ACCENT, size=6, opacity=0.6))
    )
    slope, intercept = stats.get("slope"), stats.get("intercept")
    if slope is not None and not np.isnan(slope):
        xs = np.linspace(df["sent"].min(), df["sent"].max(), 50)
        fig.add_trace(go.Scatter(x=xs, y=slope * xs + intercept, mode="lines",
                                 name="OLS fit", line=dict(color=NEG, width=2)))
    fig.update_xaxes(title="Sentiment (VADER)")
    fig.update_yaxes(title=market_label or "Market")
    return apply(fig, hover="closest")
