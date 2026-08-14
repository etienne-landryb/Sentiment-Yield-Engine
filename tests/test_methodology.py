"""Light-but-real tests pinning the README § Methodology definitions."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.analysis.correlation import best_lag, lead_lag
from src.analysis.diversity import hhi
from src.analysis.quality import data_quality
from src.finance.market import fetch_series
from src.nlp.sentiment import polarity_label


# ── polarity thresholds (±0.05) ──────────────────────────────────────────────
def test_polarity_labels():
    assert polarity_label(0.5) == "positive"
    assert polarity_label(-0.5) == "negative"
    assert polarity_label(0.0) == "neutral"
    # exact boundaries
    assert polarity_label(0.05) == "positive"
    assert polarity_label(-0.05) == "negative"
    assert polarity_label(0.049) == "neutral"


# ── lead/lag: planted lag is recovered; band ≈ 1.96/√n ───────────────────────
def test_lead_lag_recovers_planted_lag():
    rng = np.random.default_rng(0)
    idx = pd.date_range("2024-01-01", periods=120, freq="D")
    sent = pd.Series(rng.normal(size=120), index=idx)
    # market_t depends on sentiment_{t-2}  → sentiment leads by +2
    mkt = sent.shift(2)

    cc, band, n = lead_lag(sent, mkt, max_lag=5)
    assert best_lag(cc)["lag"] == 2
    assert band == pytest.approx(1.96 / np.sqrt(n), rel=1e-6)


# ── HHI ──────────────────────────────────────────────────────────────────────
def test_hhi_single_source_is_one():
    assert hhi(pd.Series(["a"] * 10)) == pytest.approx(1.0)


def test_hhi_n_equal_sources_is_one_over_n():
    for k in (2, 4, 5):
        s = pd.Series([f"src{i}" for i in range(k)] * 3)
        assert hhi(s) == pytest.approx(1.0 / k)


# ── data-quality bounds ──────────────────────────────────────────────────────
_WEIGHTS = {"volume": 0.25, "diversity": 0.20, "duplicate": 0.15, "coverage": 0.20, "scoring": 0.20}


def test_data_quality_all_ones_is_100():
    inputs = {
        "article_count": 40, "hhi": 0.0, "duplicate_rate": 0.0,
        "days_with_data": 30, "days_in_window": 30,
        "scored_headlines": 100, "total_headlines": 100,
    }
    assert data_quality(inputs, _WEIGHTS, target=40) == pytest.approx(100.0)


def test_data_quality_all_zeros_is_0():
    inputs = {
        "article_count": 0, "hhi": 1.0, "duplicate_rate": 1.0,
        "days_with_data": 0, "days_in_window": 30,
        "scored_headlines": 0, "total_headlines": 100,
    }
    assert data_quality(inputs, _WEIGHTS, target=40) == pytest.approx(0.0)


# ── fetch_series: yield → level change (diff), price → return (pct_change) ────
def test_fetch_series_yield_is_level_change(monkeypatch):
    import yfinance

    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    fake = pd.DataFrame({"Close": [4.0, 4.1, 3.9]}, index=idx)
    monkeypatch.setattr(yfinance, "download", lambda *a, **k: fake)

    y = fetch_series("^TNX", "yield", "2024-01-01", "2024-01-04")
    # level change: 4.1-4.0 = +0.10, 3.9-4.1 = -0.20
    assert y["value"].tolist() == pytest.approx([0.10, -0.20])

    p = fetch_series("^GSPC", "price", "2024-01-01", "2024-01-04")
    # simple return: 0.025, -0.0488
    assert p["value"].tolist() == pytest.approx([0.025, (3.9 - 4.1) / 4.1])
    # and the two measures must differ (yield is NOT a pct return)
    assert y["value"].tolist() != pytest.approx(p["value"].tolist())
