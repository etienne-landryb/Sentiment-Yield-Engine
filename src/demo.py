"""Synthetic data generator — keeps the whole UI shippable at every phase.

demo_bundle() emits the full CountryBundle shape (identical to live) with NO keys,
network, or DB. Design guarantees, per the build brief:
  • Sentiment: bounded random walk in [-0.9, +0.9], de-meaned.
  • Market:    0.4 * sentiment.shift(2) + noise  → a planted 2-day lead, so the
               lead/lag panel shows a real peak at lag +2.
  • Events:    2–3 injected sentiment shocks so event_flag fires (|z| ≥ 2).
  • Topics:    drawn from config/topics.yaml with uneven weights.
  • Sources:   ~15 synthetic domains, skewed (so HHI/concentration are meaningful).
  • Articles:  20–80/day, synthetic titles carrying topic keywords.
  • Correlation is computed from the generated series with the REAL analysis
    functions (via pipeline helpers) — never faked.
RNG is seeded per country for reproducibility.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src import settings
from src.nlp.topics import tag_topics
from src.pipeline import assemble_analytical, instruments_block

# ~15 synthetic sources with a skewed (Zipf-ish) draw probability.
_SOURCES = [
    "globalwire.example", "marketdaily.example", "econpost.example",
    "thebulletin.example", "capitaltimes.example", "tradewatch.example",
    "financeledger.example", "newsstream.example", "citypress.example",
    "reportbase.example", "signalnews.example", "policybrief.example",
    "yieldreport.example", "macrolens.example", "dailyanchor.example",
]

_CONNECTORS = ["amid", "as", "after", "on", "despite", "over", "signals of"]
_TAILS = [
    "analysts say", "data shows", "markets react", "investors weigh",
    "officials warn", "report finds", "outlook shifts", "concerns grow",
]

# Per-type display scale so demo market moves look plausible. Correlation is
# scale-invariant; this only affects the magnitude shown on the chart. Keyed by the
# instrument `type` ∈ {fx, index, yield}.
_ASSET_SCALE = {
    "index": 0.04,
    "fx": 0.02,
    "yield": 0.25,
}


def _seed_for(country_id: str) -> int:
    return abs(hash(country_id)) % (2**31)


def _random_walk(rng, n, phi=0.6, sigma=0.28, bound=0.9) -> np.ndarray:
    """Bounded, mean-reverting random walk (AR(1)).

    A pure random walk (phi≈1) is so autocorrelated that a planted k-day market
    lead smears across neighbouring lags. Mean reversion (phi<1) gives the series a
    decaying autocorrelation phi^|k|, so the planted 2-day peak stays crisp — while
    the process is still a bounded random walk in [-bound, +bound].
    """
    s = np.zeros(n)
    val = rng.uniform(-0.3, 0.3)
    for i in range(n):
        val = phi * val + rng.normal(0, sigma)
        val = np.clip(val, -bound, bound)
        s[i] = val
    s = s - s.mean()  # de-mean
    return np.clip(s, -bound, bound)


def _make_title(rng, topic: str, keywords: list[str]) -> str:
    kws = rng.choice(keywords, size=min(2, len(keywords)), replace=False)
    kw1 = str(kws[0]).capitalize()
    kw2 = str(kws[-1])
    conn = rng.choice(_CONNECTORS)
    tail = rng.choice(_TAILS)
    return f"{kw1} {conn} {kw2}, {tail}"


def demo_bundle(country_cfg, topic_dict, period=120) -> dict:
    """Generate a full synthetic CountryBundle for one country."""
    rng = np.random.default_rng(_seed_for(country_cfg["id"]))

    n_days = int(period) if period else 120
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n_days)
    n = len(dates)

    # ── planted daily sentiment (random walk) + injected shocks ──────────────
    sentiment = _random_walk(rng, n)
    n_shocks = rng.integers(2, 4)
    shock_idx = rng.choice(np.arange(15, n - 3), size=n_shocks, replace=False)
    for idx in shock_idx:
        sentiment[idx] += rng.choice([-1, 1]) * rng.uniform(0.55, 0.8)
    sentiment = np.clip(sentiment, -0.99, 0.99)

    # ── topic draw weights (uneven, per country) ─────────────────────────────
    topic_names = list(topic_dict.keys())
    weights = rng.dirichlet(np.ones(len(topic_names)) * 0.6)  # skewed

    # ── generate articles ────────────────────────────────────────────────────
    src_probs = np.array([1.0 / (i + 1) for i in range(len(_SOURCES))])
    src_probs = src_probs / src_probs.sum()

    rows = []
    for di, d in enumerate(dates):
        day_sent = sentiment[di]
        count = int(rng.integers(20, 81))
        # more coverage on shock days
        if di in shock_idx:
            count = int(count * 1.6)
        for _ in range(count):
            topic = rng.choice(topic_names, p=weights)
            kws = topic_dict[topic]
            title = _make_title(rng, topic, kws)
            domain = rng.choice(_SOURCES, p=src_probs)
            # per-article VADER around the day's planted sentiment (kept synthetic
            # on purpose so the daily mean matches the planted series exactly enough
            # for the 2-day market lead to be recoverable).
            v = float(np.clip(day_sent + rng.normal(0, 0.18), -1, 1))
            rows.append(
                {
                    "date": d.date(),
                    "title": title,
                    "url": f"https://{domain}/{country_cfg['id']}/{di}",
                    "domain": domain,
                    "vader": v,
                }
            )
    articles = pd.DataFrame(rows)
    articles = tag_topics(articles, topic_dict)  # real tagger over synthetic titles

    # ── assemble analytical frame with the REAL pipeline helper ──────────────
    cfg = settings.analysis_cfg()
    analytical = assemble_analytical(
        articles,
        tone_df=_demo_tone(dates, sentiment, rng),
        region=country_cfg["region"],
        country=country_cfg["label"],
        duplicate_rate=float(rng.uniform(0.03, 0.12)),
        total_headlines=len(articles),
        start=dates[0].date(),
        end=dates[-1].date(),
        cfg=cfg,
    )

    # ── instruments: market = 0.4*sentiment.shift(2) + noise ─────────────────
    daily_sent = (
        analytical.set_index(pd.to_datetime(analytical["date"]))["sentiment_mean"]
        .reindex(dates)
        .to_numpy()
    )
    daily_sent = np.nan_to_num(daily_sent, nan=float(np.nanmean(daily_sent)))

    series_map = {}
    for inst in country_cfg.get("instruments", []):
        scale = _ASSET_SCALE.get(inst.get("type", "index"), 0.04)
        vals = np.full(n, np.nan)
        for t in range(n):
            base = 0.4 * daily_sent[t - 2] if t >= 2 else 0.0
            # driver = 0.4*sentiment.shift(2) + noise; noise tuned so the planted
            # 2-day lead is a clear peak (corr ≈ 0.6) but not artificially perfect.
            driver = base + rng.normal(0, 0.18)
            vals[t] = scale * driver
        series = pd.DataFrame({"date": [d.date() for d in dates], "value": vals})
        series = series.iloc[2:].reset_index(drop=True)  # first 2 undefined lead
        series_map[inst["label"]] = {
            "type": inst.get("type", "index"),
            "meta": {
                "source": inst.get("source"),
                "source_id": inst.get("source_id"),
                "series_type": inst["series_type"],
            },
            "series": series,
        }

    return {
        "country_id": country_cfg["id"],
        "label": country_cfg["label"],
        "region": country_cfg["region"],
        "currency": country_cfg.get("currency"),
        "monetary_regime": country_cfg.get("monetary_regime", "floating"),
        "peg_to": country_cfg.get("peg_to"),
        "label_note": country_cfg.get("label_note", "Own currency"),
        "analytical": analytical,
        "articles": articles[["date", "title", "url", "domain", "vader", "topic"]],
        "instruments": instruments_block(analytical, series_map, cfg),
        "source": "demo",
    }


def _demo_tone(dates, sentiment, rng) -> pd.DataFrame:
    """GDELT-style independent tone: correlated-but-not-identical to our sentiment."""
    tone = sentiment * 10 + rng.normal(0, 2.0, size=len(dates))  # GDELT tone ~ ±10
    return pd.DataFrame({"date": [d.date() for d in dates], "gdelt_tone": tone})
