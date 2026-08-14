"""Keyword extraction for the word cloud (TF-IDF weights over titles)."""
from __future__ import annotations

import re

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

_TOKEN = re.compile(r"[A-Za-z][A-Za-z\-']+")


def top_keywords(df: pd.DataFrame, n: int = 30) -> list[tuple[str, float]]:
    """Return up to n (term, weight) pairs by summed TF-IDF over the titles.

    Falls back to raw frequency if the corpus is too small for TF-IDF.
    """
    if df is None or df.empty or "title" not in df:
        return []
    titles = df["title"].fillna("").astype(str).tolist()
    titles = [t for t in titles if t.strip()]
    if not titles:
        return []

    try:
        vec = TfidfVectorizer(
            stop_words="english",
            token_pattern=_TOKEN.pattern,
            lowercase=True,
            min_df=1,
            max_features=2000,
        )
        matrix = vec.fit_transform(titles)
        weights = matrix.sum(axis=0).A1
        terms = vec.get_feature_names_out()
        pairs = sorted(zip(terms, weights), key=lambda x: x[1], reverse=True)
        return [(t, float(w)) for t, w in pairs[:n] if w > 0]
    except ValueError:
        # Empty vocabulary (all stop words) — degrade to frequency counts.
        from collections import Counter

        words = [
            w.lower()
            for t in titles
            for w in _TOKEN.findall(t)
            if len(w) > 2
        ]
        return [(w, float(c)) for w, c in Counter(words).most_common(n)]
