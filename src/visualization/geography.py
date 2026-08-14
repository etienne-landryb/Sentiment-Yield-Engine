"""Choropleth sentiment map — plotly.express only (no Folium / GeoPandas)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from src import settings
from src.visualization.theme import apply


def fig_choropleth(bundles: dict, ids: list[str]) -> go.Figure:
    """World choropleth of period-mean sentiment, keyed by each country's iso3."""
    rows = []
    for cid in ids:
        b = bundles.get(cid)
        cfg = settings.country_by_id(cid) or {}
        iso3 = cfg.get("iso3")
        if not b or b["analytical"].empty or not iso3:
            continue
        rows.append(
            {
                "iso3": iso3,
                "country": b["label"],
                "sentiment": float(np.nanmean(b["analytical"]["sentiment_mean"])),
            }
        )
    if not rows:
        return apply(go.Figure(), title="No mapped countries")

    df = pd.DataFrame(rows)
    fig = px.choropleth(
        df,
        locations="iso3",
        locationmode="ISO-3",                      # Tier 1.3: match geometry by ISO-3
        color="sentiment",
        hover_name="country",
        color_continuous_scale="RdYlGn",
        color_continuous_midpoint=0,               # centre the diverging scale at 0
        custom_data=["country"],
    )
    fig.update_traces(hovertemplate="%{customdata[0]}<br>sentiment %{z:.3f}<extra></extra>")
    # No fitbounds — it zoomed onto empty canvas. Fixed world projection instead.
    fig.update_geos(scope="world", projection_type="natural earth", visible=True,
                    showframe=False, showcoastlines=False, bgcolor="rgba(0,0,0,0)")
    fig.update_layout(coloraxis_colorbar=dict(title="sentiment"))
    return apply(fig, height=420)


def fig_metric_map(rows: list[dict], colorbar_label: str = "value",
                   scale: str = "RdYlGn") -> go.Figure:
    """Generic choropleth from [{iso3, country, value, regime_note?}] rows.

    Rows with a null iso3 (e.g. aggregate blocs) are skipped — the caller annotates
    shared-currency blocs separately. `regime_note`, if present, is surfaced in the
    hover (§5 — the monetary regime is a feature, not an apology, shown everywhere).
    """
    rows = [r for r in rows if r.get("iso3") and r.get("value") == r.get("value")]
    if not rows:
        return apply(go.Figure(), title="No mapped entities")
    df = pd.DataFrame(rows)
    if "regime_note" not in df:
        df["regime_note"] = ""
    span = max(0.05, float(df["value"].abs().max()))
    fig = px.choropleth(
        df, locations="iso3", locationmode="ISO-3", color="value",
        hover_name="country", color_continuous_scale=scale,
        range_color=(-span, span), custom_data=["country", "regime_note"],
    )
    fig.update_traces(
        hovertemplate="%{customdata[0]}<br>%{z:.3f}<br>%{customdata[1]}<extra></extra>")
    # UX Pass 2, Part 2 — px.choropleth only colors the rows it's given; without an
    # explicit land/ocean/coastline base every other country renders as blank canvas
    # (the "no Earth" bug). showland/showocean/showcoastlines restore a full world
    # basemap — colored countries stand out against a neutral grey backdrop instead
    # of floating shapes on nothing.
    fig.update_geos(
        scope="world", projection_type="natural earth", visible=True, showframe=False,
        showcountries=True, countrycolor="rgba(150,150,150,0.5)",
        showland=True, landcolor="rgb(235,235,235)",
        showocean=True, oceancolor="rgb(247,249,251)",
        showcoastlines=True, coastlinecolor="rgba(120,120,120,0.6)",
    )
    fig.update_layout(coloraxis_colorbar=dict(title=colorbar_label))
    return apply(fig, height=520)
