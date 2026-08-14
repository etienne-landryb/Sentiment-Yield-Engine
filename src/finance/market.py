"""Financial data — per-instrument fetch with status.

Sources (fixed per instrument in config, never swapped at runtime):
  • fred       → FRED via pandas-datareader (keyless). FX (~weekly), US index, US yield.
  • twelvedata → Twelve Data REST (free key, daily; throttled to ≤8/min).

series_type == "price"  -> daily simple returns   (pct_change)
series_type == "yield"  -> daily LEVEL change      (diff, never a pct return of a yield)

`fetch_series` is polymorphic:
  • fetch_series(instrument_dict, start, end)      → new dispatch (fred | twelvedata)
  • fetch_series(ticker, series_type, start, end)  → legacy yfinance path (back-compat
    + retained solely for the frozen methodology test; not used by the live pipeline)

Every fetch is wrapped: one bad instrument is captured as status, never raised past
the instrument, so a country never fails to build because a sibling series failed.
"""
from __future__ import annotations

import logging
import threading
import time

import numpy as np
import pandas as pd

from src.settings import env

log = logging.getLogger(__name__)

_COLS = ["date", "value"]


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=_COLS)


# ── level → analytical value (returns vs level change) ───────────────────────
def _level_to_value(level: pd.Series, series_type: str) -> pd.DataFrame:
    level = pd.Series(level).dropna().sort_index()
    if level.empty:
        return _empty()
    value = level.diff() if series_type == "yield" else level.pct_change()
    idx = pd.to_datetime(level.index)
    out = pd.DataFrame({"date": idx.date, "value": value.to_numpy()})
    return out.dropna(subset=["value"]).reset_index(drop=True)


# ── FRED (keyless via pandas-datareader) ─────────────────────────────────────
def _fetch_fred(series_id: str, start, end) -> pd.Series:
    from pandas_datareader import data as pdr

    df = pdr.DataReader(series_id, "fred", pd.to_datetime(start), pd.to_datetime(end))
    if df is None or df.empty:
        return pd.Series(dtype=float)
    col = df.iloc[:, 0]
    return pd.Series(col.to_numpy(), index=pd.to_datetime(df.index)).astype(float)


# ── Twelve Data (keyed REST, throttled ≤8/min) ───────────────────────────────
_TD_LOCK = threading.Lock()
_TD_CALLS: list[float] = []
_TD_MAX_PER_MIN = 8


def _td_throttle() -> None:
    """Block until fewer than 8 calls occurred in the trailing 60s window."""
    with _TD_LOCK:
        now = time.monotonic()
        while _TD_CALLS and now - _TD_CALLS[0] > 60:
            _TD_CALLS.pop(0)
        if len(_TD_CALLS) >= _TD_MAX_PER_MIN:
            sleep_for = 60 - (now - _TD_CALLS[0]) + 0.1
            log.info("Twelve Data throttle: sleeping %.1fs", sleep_for)
            time.sleep(max(0.0, sleep_for))
        _TD_CALLS.append(time.monotonic())


def _fetch_twelvedata(symbol: str, start, end) -> pd.Series:
    import requests

    api_key = env("TWELVE_DATA_API_KEY")
    if not api_key:
        raise RuntimeError("TWELVE_DATA_API_KEY not set")

    _td_throttle()
    params = {
        "symbol": symbol,
        "interval": "1day",
        "start_date": pd.to_datetime(start).strftime("%Y-%m-%d"),
        "end_date": pd.to_datetime(end).strftime("%Y-%m-%d"),
        "outputsize": 5000,
        "apikey": api_key,
        "format": "JSON",
    }
    resp = requests.get("https://api.twelvedata.com/time_series", params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and data.get("status") == "error":
        raise RuntimeError(f"Twelve Data error: {data.get('message', 'unknown')}")
    values = (data or {}).get("values", [])
    if not values:
        return pd.Series(dtype=float)
    df = pd.DataFrame(values)
    df["datetime"] = pd.to_datetime(df["datetime"])
    s = pd.Series(df["close"].astype(float).to_numpy(), index=df["datetime"])
    return s.sort_index()


# ── dispatch + status ────────────────────────────────────────────────────────
def _dispatch_level(instrument: dict, start, end) -> pd.Series:
    src, sid = instrument["source"], instrument["source_id"]
    if src == "fred":
        return _fetch_fred(sid, start, end)
    if src == "twelvedata":
        return _fetch_twelvedata(sid, start, end)
    raise ValueError(f"unknown source: {src!r}")


def fetch_series_with_status(instrument: dict, start, end) -> tuple[pd.DataFrame, str, str | None]:
    """Fetch one instrument. Returns (df[date,value], status, reason).

    status ∈ {"ok", "unavailable"}. Never raises.
    """
    try:
        level = _dispatch_level(instrument, start, end)
        if level is None or pd.Series(level).dropna().empty:
            return _empty(), "unavailable", "no data returned"
        df = _level_to_value(level, instrument.get("series_type", "price"))
        if df.empty:
            return df, "unavailable", "insufficient points"
        return df, "ok", None
    except Exception as exc:
        log.warning("fetch failed for %s/%s: %s",
                    instrument.get("source"), instrument.get("source_id"), exc)
        # include the message so Twelve Data's own error text (e.g. "symbol not
        # found", "upgrade plan") surfaces in the diagnostics panel.
        return _empty(), "unavailable", f"{type(exc).__name__}: {str(exc)[:160]}"


# ── legacy yfinance path (back-compat + frozen test only) ────────────────────
def _fetch_yfinance_legacy(ticker: str, series_type: str, start, end) -> pd.DataFrame:
    try:
        import yfinance as yf

        raw = yf.download(ticker, start=pd.to_datetime(start), end=pd.to_datetime(end),
                          progress=False, auto_adjust=True)
        if raw is None or raw.empty:
            return _empty()
        close = raw["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        return _level_to_value(pd.Series(close.to_numpy(), index=pd.to_datetime(close.index)),
                               series_type)
    except Exception as exc:
        log.warning("legacy yfinance fetch failed for %s: %s", ticker, exc)
        return _empty()


def fetch_series(*args, **kwargs) -> pd.DataFrame:
    """Polymorphic. See module docstring for the two accepted call forms."""
    if args and isinstance(args[0], dict):
        instrument, start, end = args[0], args[1], args[2]
        df, _status, _reason = fetch_series_with_status(instrument, start, end)
        return df
    # legacy: (ticker, series_type, start, end)
    ticker, series_type, start, end = args
    return _fetch_yfinance_legacy(ticker, series_type, start, end)


def realized_vol(returns: pd.Series, window: int = 20) -> pd.Series:
    """Rolling realized volatility (std of returns) over `window` days."""
    if returns is None or len(returns) == 0:
        return pd.Series(dtype=float)
    return returns.rolling(window=window, min_periods=max(2, window // 2)).std(ddof=0)
