"""One chart layout template applied to every figure (Tier 4.3).

Consistent font, margins, legend placement, transparent background, and — crucially
(Tier 1.1) — NO in-figure title. Chart identity comes from the Streamlit-level
heading above each chart, so the in-figure title is removed to stop it colliding
with the legend and top axis.
"""
from __future__ import annotations

import plotly.graph_objects as go

FONT = "Inter, system-ui, -apple-system, Segoe UI, sans-serif"
GRID = "rgba(128,128,128,0.14)"


def style(fig: go.Figure, *, height: int = 340, legend_top: bool = True,
          hover: str | None = "x unified") -> go.Figure:
    """Route every figure through this. Kills the title; unifies type & spacing."""
    fig.update_layout(
        # Tier 1.1 — no in-figure title. Use an explicit empty string, NOT None:
        # Streamlit's Plotly theme renders a literal "undefined" for a None title.
        title=dict(text=""),
        height=height,
        margin=dict(t=30, r=20, b=10, l=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, size=12),
        legend=(dict(orientation="h", y=1.08, x=0, title=None,
                     yanchor="bottom", xanchor="left")
                if legend_top else dict(title=None)),
    )
    if hover:
        fig.update_layout(hovermode=hover)
    fig.update_xaxes(showgrid=True, gridcolor=GRID, zeroline=False)
    fig.update_yaxes(showgrid=True, gridcolor=GRID, zeroline=False)
    return fig
