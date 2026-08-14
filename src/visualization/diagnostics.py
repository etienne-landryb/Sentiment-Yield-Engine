"""Data-quality gauge, source-concentration chart, sentiment-split figures."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from src.analysis.diversity import source_stats
from src.visualization.theme import NEG, NEU, POS, apply


def fig_quality_gauge(score: float) -> go.Figure:
    """0–100 data-quality gauge (a diagnostic, NOT a confidence interval)."""
    score = float(score) if score == score else 0.0
    color = NEG if score < 40 else ("#EECA3B" if score < 70 else POS)
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=score,
            number={"suffix": " / 100"},
            gauge={
                "axis": {"range": [0, 100]},
                "bar": {"color": color},
                "steps": [
                    {"range": [0, 40], "color": "rgba(228,87,86,0.15)"},
                    {"range": [40, 70], "color": "rgba(238,202,59,0.15)"},
                    {"range": [70, 100], "color": "rgba(84,162,75,0.15)"},
                ],
            },
        )
    )
    return apply(fig, height=240, title="Data-quality score")


def fig_source_concentration(articles: pd.DataFrame, top: int = 10) -> go.Figure:
    """Top sources by share, annotated with the HHI concentration index."""
    fig = go.Figure()
    if articles is None or articles.empty or "domain" not in articles:
        return apply(fig, title="No sources")
    stats = source_stats(articles, top=top)
    counts = articles["domain"].value_counts().head(top)
    total = articles["domain"].value_counts().sum()
    shares = (counts / total)[::-1]
    fig.add_trace(
        go.Bar(x=shares.values, y=shares.index, orientation="h", marker_color="#72B7B2",
               hovertemplate="%{y}: %{x:.1%}<extra></extra>")
    )
    fig.update_xaxes(title="share of articles", tickformat=".0%")
    # HHI carried as an in-plot annotation (title is removed centrally, Tier 1.1).
    fig.add_annotation(
        xref="paper", yref="paper", x=0.98, y=0.04, xanchor="right", yanchor="bottom",
        showarrow=False, text=f"HHI = {stats['hhi']:.2f}  ·  {stats['source_count']} sources",
        font=dict(size=11, color="#72B7B2"),
    )
    return apply(fig, hover="closest")


def fig_sentiment_split(analytical: pd.DataFrame) -> go.Figure:
    """Stacked positive / neutral / negative share over time."""
    fig = go.Figure()
    if analytical is None or analytical.empty:
        return apply(fig, title="No data")
    x = pd.to_datetime(analytical["date"])
    for name, col, color in [
        ("positive", "sentiment_positive_share", POS),
        ("neutral", "sentiment_neutral_share", NEU),
        ("negative", "sentiment_negative_share", NEG),
    ]:
        fig.add_trace(go.Scatter(x=x, y=analytical[col], name=name, stackgroup="one",
                                 line=dict(width=0.5, color=color)))
    fig.update_yaxes(title="share", range=[0, 1], tickformat=".0%")
    return apply(fig, title="Sentiment split (positive / neutral / negative)")
