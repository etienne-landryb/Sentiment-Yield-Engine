"""Per-instrument last-good cache (in-process, per app instance).

Keyed `country_id:instrument_label`. On a successful live fetch we remember the
series; on a failed refresh of that one instrument we serve its last-good marked
`ok (cached)`, while everything else refreshes normally. This is the middle tier
of the resilience order:  fresh → per-instrument last-good → demo.

A durable cross-restart snapshot (Supabase / file) is deliberately deferred, so
this store resets when the process restarts — acceptable per the brief.
"""
from __future__ import annotations

import threading

_LOCK = threading.Lock()
_STORE: dict[str, dict] = {}


def key(country_id: str, label: str) -> str:
    return f"{country_id}:{label}"


def remember(country_id: str, label: str, series, last_updated) -> None:
    with _LOCK:
        _STORE[key(country_id, label)] = {"series": series, "last_updated": last_updated}


def recall(country_id: str, label: str) -> dict | None:
    with _LOCK:
        return _STORE.get(key(country_id, label))


def clear() -> None:  # pragma: no cover - test/debug helper
    with _LOCK:
        _STORE.clear()
