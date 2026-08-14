"""Deterministic keyword/topic-dictionary classification (V1).

Each headline is tagged with the topic that has the most whole-word keyword hits;
ties break by config order; "Other" if nothing matches. No embeddings, no BERTopic.
"""
from __future__ import annotations

import re
from functools import lru_cache

import pandas as pd


@lru_cache(maxsize=256)
def _compile(keyword: str) -> re.Pattern:
    # Whole-word / phrase match, case-insensitive.
    return re.compile(r"\b" + re.escape(keyword.lower()) + r"\b")


def _best_topic(title: str, topic_dict: dict[str, list[str]]) -> str:
    if not title:
        return "Other"
    text = title.lower()
    best, best_hits = "Other", 0
    for topic, keywords in topic_dict.items():
        hits = sum(1 for kw in keywords if _compile(kw).search(text))
        if hits > best_hits:
            best, best_hits = topic, hits
    return best


def tag_topics(df: pd.DataFrame, topic_dict: dict[str, list[str]]) -> pd.DataFrame:
    """Add a 'topic' column (best keyword-dictionary match; 'Other' if none)."""
    out = df.copy()
    if out.empty:
        out["topic"] = pd.Series(dtype=object)
        return out
    out["topic"] = (
        out["title"].fillna("").astype(str).apply(lambda t: _best_topic(t, topic_dict))
    )
    return out
