"""Demo-mode contract: full CountryBundle shape + the planted 2-day lead.

The panel is intentionally heterogeneous (config/regions.yaml, 197 countries):
most carry a real financial instrument, but a genuine subset are `unlinked`
(sentiment-only, `instruments: []`) — that's the honest, by-design outcome of
the monetary-regime classification, not a gap to work around. These tests use
the same `first_ok_instrument` helper the pipeline/app use to find a working
instrument when one exists, and explicitly assert the empty case is handled
gracefully (present, typed, no crash) rather than silently skipping it.
"""
from __future__ import annotations

from src import settings
from src.pipeline import build_all, first_ok_instrument

ANALYTICAL_COLS = {
    "region", "country", "date", "article_count", "source_count", "duplicate_rate",
    "source_concentration", "sentiment_mean", "sentiment_median",
    "sentiment_positive_share", "sentiment_neutral_share", "sentiment_negative_share",
    "gdelt_tone_mean", "top_topics", "topic_counts", "topic_sentiment", "keywords",
    "event_flag", "event_score", "data_quality_score",
}


def _assert_instruments_graceful(b: dict, label: str | None, entry: dict | None) -> None:
    """No instrument found: instruments must still be present, dict-typed, and
    contain nothing usable — never missing, never the wrong type, never a KeyError."""
    assert "instruments" in b
    instruments = b["instruments"]
    assert isinstance(instruments, dict)
    assert entry is None and label is None
    assert not any(str(e.get("status", "")).startswith("ok") for e in instruments.values())


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
        # correlation block present and complete WHEN a working instrument exists;
        # otherwise confirm the empty case is handled gracefully, not skipped.
        label, entry = first_ok_instrument(b)
        if entry is not None:
            corr = entry["correlation"]
            for k in ("pearson", "spearman", "n", "slope", "intercept", "rolling", "leadlag", "band", "best_lag"):
                assert k in corr
        else:
            _assert_instruments_graceful(b, label, entry)


def test_demo_planted_lag_is_plus_two():
    bundles = build_all(120)
    checked_with_instrument = 0
    for b in bundles.values():
        label, entry = first_ok_instrument(b)
        if entry is not None:
            assert entry["correlation"]["best_lag"]["lag"] == 2
            checked_with_instrument += 1
        else:
            _assert_instruments_graceful(b, label, entry)
    # sanity: the planted-lag assertion above must have actually run for at least
    # one country, so this test can't pass vacuously if every bundle were empty.
    assert checked_with_instrument > 0
