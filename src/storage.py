"""Optional persistence (Phase 7) — Supabase / pgvector, entirely behind a flag.

Not required for V1. The app is fully functional with persistence OFF: every
function here is a graceful no-op unless SUPABASE_URL/SUPABASE_KEY (or DATABASE_URL)
are configured AND the optional deps are installed. Nothing in the quantitative
pipeline or the UI depends on this module.
"""
from __future__ import annotations

import logging

from src.settings import env

log = logging.getLogger(__name__)


def is_enabled() -> bool:
    """True only when persistence is configured. Everything else no-ops."""
    return bool(env("SUPABASE_URL") and env("SUPABASE_KEY")) or bool(env("DATABASE_URL"))


def _client():
    """Return a Supabase client, or None if unavailable (never raises)."""
    if not is_enabled():
        return None
    try:
        from supabase import create_client

        return create_client(env("SUPABASE_URL"), env("SUPABASE_KEY"))
    except Exception as exc:  # dep missing / bad creds — degrade silently
        log.info("Persistence unavailable: %s", exc)
        return None


def save_articles(country_id: str, articles) -> bool:
    """Best-effort persist of an article-level frame. Returns False when disabled."""
    client = _client()
    if client is None or articles is None or getattr(articles, "empty", True):
        return False
    try:
        rows = articles.assign(country_id=country_id).to_dict(orient="records")
        client.table("articles").upsert(rows).execute()
        return True
    except Exception as exc:
        log.warning("save_articles failed: %s", exc)
        return False


def load_articles(country_id: str):
    """Best-effort read. Returns None when disabled/unavailable."""
    client = _client()
    if client is None:
        return None
    try:
        import pandas as pd

        resp = client.table("articles").select("*").eq("country_id", country_id).execute()
        return pd.DataFrame(resp.data)
    except Exception as exc:
        log.warning("load_articles failed: %s", exc)
        return None
