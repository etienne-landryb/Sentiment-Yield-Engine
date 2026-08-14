"""Config + environment loader. The one place that knows where files live.

Everything downstream reads countries/instruments/topics/thresholds through here,
so adding a country or changing a threshold is a YAML edit — never a code change.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

# Repo root = parent of src/. Config lives at <root>/config.
ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"

# Load .env once, if present. In deployed Streamlit, st.secrets populates os.environ
# separately; env() reads os.environ either way.
try:  # dotenv is optional at import time; never let its absence break imports.
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:  # pragma: no cover - defensive
    pass


def env(name: str, default=None):
    """Read an environment variable, falling back to st.secrets when deployed."""
    val = os.environ.get(name)
    if val not in (None, ""):
        return val
    # st.secrets is only meaningful inside a running Streamlit app; guard the import.
    try:
        import streamlit as st  # noqa: WPS433

        if name in st.secrets:
            return st.secrets[name]
    except Exception:  # pragma: no cover - not running under streamlit
        pass
    return default


# DATA_MODE is read as a module attribute AND via a helper so tests can monkeypatch.
def data_mode() -> str:
    return (env("DATA_MODE", "demo") or "demo").strip().lower()


DATA_MODE: str = data_mode()


@lru_cache(maxsize=1)
def load_config() -> dict:
    """Parsed config/regions.yaml."""
    with open(CONFIG_DIR / "regions.yaml", "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@lru_cache(maxsize=1)
def load_topics() -> dict[str, list[str]]:
    """Parsed config/topics.yaml -> {topic_label: [keywords...]}."""
    with open(CONFIG_DIR / "topics.yaml", "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return raw.get("topics", raw)


def base_query() -> str:
    return load_config()["base_query"]


def regions() -> dict[str, dict]:
    return load_config().get("regions", {})


def countries() -> list[dict]:
    return load_config().get("countries", [])


def country_by_id(country_id: str) -> dict | None:
    for c in countries():
        if c["id"] == country_id:
            return c
    return None


def sources() -> dict:
    """Source cadence metadata, e.g. {'fred': {'cadence': 'weekly'}, ...}."""
    return load_config().get("sources", {})


def source_cadence(source: str) -> str:
    return (sources().get(source, {}) or {}).get("cadence", "daily")


def aggregates() -> list[dict]:
    """Shared-currency aggregate entities (e.g. euro area). May be empty."""
    return load_config().get("aggregates", [])


def aggregate_by_id(agg_id: str) -> dict | None:
    for a in aggregates():
        if a["id"] == agg_id:
            return a
    return None


def analysis_cfg() -> dict:
    return load_config().get("analysis", {})


def quality_cfg() -> dict:
    a = analysis_cfg().get("quality", {})
    return {
        "target": a.get("target", 40),
        "weights": a.get(
            "weights",
            {
                "volume": 0.25,
                "diversity": 0.20,
                "duplicate": 0.15,
                "coverage": 0.20,
                "scoring": 0.20,
            },
        ),
    }
