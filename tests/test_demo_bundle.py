"""Demo-mode contract: full CountryBundle shape + the planted 2-day lead."""
from __future__ import annotations

from src import settings
from src.pipeline import build_all

ANALYTICAL_COLS = {
    "region", "country", "date", "article_count", "source_count", "duplicate_rate",
    "source_concentration", "sentiment_mean", "sentiment_median",
    "sentiment_positive_share", "sentiment_neutral_share", "sentiment_negative_share",
    "gdelt_tone_mean", "top_topics", "topic_counts", "topic_sentiment", "keywords",
    "event_flag", "event_score", "data_quality_score",
}


def test_demo_builds_all_countries_with_full_shape():
    bundles = build_all(120)
    assert set(bundles) == {c["id"] for c in settings.countries()}
    for b in bundles.values():
        adf = b["analytical"]
        assert not adf.empty
        assert ANALYTICAL_COLS.issubset(set(adf.columns))
        # three shares sum to 1
        s = adf[["sentiment_positive_share", "sentiment_neutral_share", "sentiment_negative_share"]].sum(axis=1)
        assert (s.round(6) == 1.0).all()
        # events fire in demo
        assert adf["event_flag"].sum() >= 1
        # correlation block present and complete
        first = next(iter(b["instruments"]))
        corr = b["instruments"][first]["correlation"]
        for k in ("pearson", "spearman", "n", "slope", "intercept", "rolling", "leadlag", "band", "best_lag"):
            assert k in corr


def test_demo_planted_lag_is_plus_two():
    bundles = build_all(120)
    for b in bundles.values():
        first = next(iter(b["instruments"]))
        assert b["instruments"][first]["correlation"]["best_lag"]["lag"] == 2
