"""GDELT DOC 2.0 ingestion (keyless).

Two modes:
  - artlist      -> [date, title, url, domain]  (VADER runs on titles)
  - timelinetone -> [date, gdelt_tone]          (GDELT's own average tone)

Query string is built as:  base_query + " sourcecountry:XX sourcelang:english".
Every call goes through `_gdelt_get`, which serialises + spaces out calls (GDELT
throttles bursts), retries 429/5xx with backoff, and — crucially for diagnosing the
live failure mode — RETURNS the http status + error message rather than swallowing
them. The fetchers surface a small `trace` dict alongside the frame so the app can
show whether GDELT is 429-ing, timing out, serving a non-JSON body, or returning an
empty 200.
"""
from __future__ import annotations

import logging
import random
import threading
import time
from datetime import date, datetime, timedelta

import pandas as pd
import requests

log = logging.getLogger(__name__)

DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"
_TIMEOUT = 30

# Throttle + retry. Tune _MIN_INTERVAL down if your host tolerates it.
_GDELT_LOCK = threading.Lock()
_LAST_CALL = [0.0]
_MIN_INTERVAL = 3.0
_RETRIES = 3

# Windowed sampling: a FEW sub-windows so the throttled cold build stays bounded.
_WINDOW_DAYS = 30
_MAX_WINDOWS = 3


def _fmt(dt) -> str:
    """GDELT wants YYYYMMDDHHMMSS."""
    if isinstance(dt, datetime):
        return dt.strftime("%Y%m%d%H%M%S")
    if isinstance(dt, date):
        return dt.strftime("%Y%m%d") + "000000"
    return str(dt)


def _build_query(base_query: str, country_cfg: dict) -> str:
    g = country_cfg.get("gdelt", {})
    sc = g.get("source_country")
    sl = g.get("source_lang", "english")
    parts = [base_query]
    if sc:
        parts.append(f"sourcecountry:{sc}")
    if sl:
        parts.append(f"sourcelang:{sl}")
    return " ".join(parts)


def _throttle() -> None:
    """Space calls at least _MIN_INTERVAL apart across the whole build."""
    with _GDELT_LOCK:
        wait = _MIN_INTERVAL - (time.monotonic() - _LAST_CALL[0])
        if wait > 0:
            time.sleep(wait)
        _LAST_CALL[0] = time.monotonic()


def _gdelt_get(params: dict):
    """Throttled + retried GET.

    Returns (json_or_None, http_status, error_or_None, attempts). Distinguishes
    429/5xx, timeouts, and 200-with-non-JSON bodies so the failure mode is known.
    """
    last_status, last_err = None, None
    for attempt in range(_RETRIES):
        _throttle()
        try:
            resp = requests.get(DOC_API, params=params, timeout=_TIMEOUT)
            last_status = resp.status_code
            if resp.status_code == 429 or resp.status_code >= 500:
                last_err = f"HTTP {resp.status_code}"
                raise requests.HTTPError(last_err)
            resp.raise_for_status()
            try:  # GDELT sometimes returns 200 with an HTML/error body
                return resp.json(), resp.status_code, None, attempt + 1
            except Exception:
                last_err = f"non-JSON body ({resp.text[:120]!r})"
                raise ValueError(last_err)
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {str(exc)[:140]}"
            time.sleep((2 ** attempt) + random.uniform(0, 0.5))
    return None, last_status, last_err, _RETRIES


def _windows(start, end):
    """Split [start, end] into up to _MAX_WINDOWS sub-ranges of ~_WINDOW_DAYS."""
    s = pd.to_datetime(start)
    e = pd.to_datetime(end)
    total = max((e - s).days, 1)
    n = min(_MAX_WINDOWS, max(1, (total + _WINDOW_DAYS - 1) // _WINDOW_DAYS))
    step = total / n
    for i in range(n):
        ws = s + timedelta(days=step * i)
        we = s + timedelta(days=step * (i + 1)) if i < n - 1 else e
        yield ws, we


def _parse_articles(data) -> pd.DataFrame:
    cols = ["date", "title", "url", "domain"]
    articles = data.get("articles", []) if isinstance(data, dict) else []
    rows = []
    for a in articles:
        dt = pd.to_datetime(a.get("seendate"), errors="coerce")
        rows.append({
            "date": dt.date() if pd.notna(dt) else None,
            "title": a.get("title", ""),
            "url": a.get("url", ""),
            "domain": a.get("domain", ""),
        })
    df = pd.DataFrame(rows, columns=cols)
    return df.dropna(subset=["date"]).reset_index(drop=True)


def fetch_articles(base_query: str, country_cfg: dict, start, end, maxrecords: int = 250):
    """DOC 2.0 artlist, sampled across windows. Returns (df[date,title,url,domain], trace)."""
    cols = ["date", "title", "url", "domain"]
    query = _build_query(base_query, country_cfg)
    frames, statuses, attempts_total, windows_ok, last_err = [], [], 0, 0, None
    for ws, we in _windows(start, end):
        params = {"query": query, "mode": "artlist", "format": "json",
                  "maxrecords": int(maxrecords), "startdatetime": _fmt(ws),
                  "enddatetime": _fmt(we), "sort": "datedesc"}
        data, status, err, attempts = _gdelt_get(params)
        statuses.append(status)
        attempts_total += attempts
        if data is not None:
            frames.append(_parse_articles(data))
            windows_ok += 1
        elif err:
            last_err = err

    if frames:
        out = pd.concat(frames, ignore_index=True)
        if not out.empty and "url" in out:
            out = out.drop_duplicates(subset="url", keep="first").reset_index(drop=True)
    else:
        out = pd.DataFrame(columns=cols)

    trace = {"query": query, "http_status": statuses[-1] if statuses else None,
             "window_statuses": statuses, "error": last_err, "attempts": attempts_total,
             "n_windows": len(statuses), "windows_ok": windows_ok, "n_articles": int(len(out))}
    if not out.empty:
        log.info("GDELT artlist %s: %d articles across %d/%d windows",
                 country_cfg.get("id"), len(out), windows_ok, len(statuses))
    else:
        log.warning("GDELT artlist empty for %s (status=%s err=%s)",
                    country_cfg.get("id"), trace["http_status"], last_err)
    return out, trace


def fetch_timeline_tone(base_query: str, country_cfg: dict, start, end):
    """DOC 2.0 timelinetone mode. Returns (df[date,gdelt_tone], trace)."""
    cols = ["date", "gdelt_tone"]
    query = _build_query(base_query, country_cfg)
    params = {"query": query, "mode": "timelinetone", "format": "json",
              "startdatetime": _fmt(start), "enddatetime": _fmt(end)}
    data, status, err, attempts = _gdelt_get(params)

    rows = []
    if data is not None:
        for block in (data.get("timeline", []) if isinstance(data, dict) else []):
            for point in block.get("data", []):
                dt = pd.to_datetime(point.get("date"), errors="coerce")
                rows.append({"date": dt.date() if pd.notna(dt) else None,
                             "gdelt_tone": point.get("value")})
    df = pd.DataFrame(rows, columns=cols)
    df = df.dropna(subset=["date"]).reset_index(drop=True) if not df.empty else df

    trace = {"http_status": status, "error": err, "attempts": attempts, "n_rows": int(len(df))}
    if df.empty:
        log.warning("GDELT timelinetone empty for %s (status=%s err=%s)",
                    country_cfg.get("id"), status, err)
    return df, trace
