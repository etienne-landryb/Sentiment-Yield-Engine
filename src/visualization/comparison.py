"""Cross-country comparison visuals (the table itself is built in analysis/)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from src.visualization.theme import PALETTE, apply


def fig_comparison_bars(table: pd.DataFrame, metric: str = "sentiment_mean") -> go.Figure:
    """Horizontal, value-sorted bar of one comparison metric across countries.

    Tier 1.5: with only four categories and tiny values, vertical bars ballooned to
    fill the width — a sorted horizontal bar at a fixed, modest height reads cleanly.
    """
    fig = go.Figure()
    if table is None or table.empty or metric not in table:
        return apply(fig, height=220)
    df = table[["country", metric]].dropna().sort_values(metric)
    colors = [PALETTE[i % len(PALETTE)] for i in range(len(df))]
    fig.add_trace(
        go.Bar(x=df[metric], y=df["country"], orientation="h", marker_color=colors,
               hovertemplate="%{y}: %{x:.3f}<extra></extra>")
    )
    fig.update_xaxes(title=metric.replace("_", " "))
    height = max(180, 60 + 46 * len(df))
    return apply(fig, height=height, hover="closest")
