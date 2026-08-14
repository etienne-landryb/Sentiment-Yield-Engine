"""Shared palette + the figure styler.

`apply()` now delegates to the one chart template in `_layout.style()` and, per
Tier 1.1, drops any in-figure title — every existing viz call routes through here,
so removing titles is centralized. Callers may still pass `title=...`; it is
accepted for backwards compatibility and intentionally ignored.
"""
from __future__ import annotations

import plotly.graph_objects as go

from src.visualization._layout import style

# Brand-neutral, colour-blind-aware sequence.
PALETTE = [
    "#4C78A8", "#F58518", "#54A24B", "#E45756",
    "#72B7B2", "#EECA3B", "#B279A2", "#FF9DA6",
]
POS = "#54A24B"
NEG = "#E45756"
NEU = "#9AA0A6"
ACCENT = "#4C78A8"


def apply(fig: go.Figure, height: int = 340, *, legend_top: bool = True,
          hover: str | None = "x unified", title: str | None = None,
          **_ignored) -> go.Figure:
    """Style a figure through the shared template. `title` is ignored (Tier 1.1)."""
    return style(fig, height=height, legend_top=legend_top, hover=hover)
