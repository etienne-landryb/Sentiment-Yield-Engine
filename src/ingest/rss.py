"""Optional RSS ingestion (keyless). One bad feed never kills a run."""
from __future__ import annotations

import logging
from urllib.parse import urlparse

import feedparser
import pandas as pd

log = logging.getLogger(__name__)


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


def fetch_rss(feed_urls: list[str]) -> pd.DataFrame:
    """Fetch a list of RSS feeds -> [date, title, url, domain]."""
    cols = ["date", "title", "url", "domain"]
    rows = []
    for feed_url in feed_urls or []:
        try:
            parsed = feedparser.parse(feed_url)
            for e in parsed.entries:
                dt = None
                if getattr(e, "published_parsed", None):
                    dt = pd.Timestamp(*e.published_parsed[:6]).date()
                title = getattr(e, "title", "")
                link = getattr(e, "link", "")
                rows.append(
                    {
                        "date": dt,
                        "title": title,
                        "url": link,
                        "domain": _domain(link) or _domain(feed_url),
                    }
                )
        except Exception as exc:
            log.warning("RSS feed failed (%s): %s", feed_url, exc)
            continue
    df = pd.DataFrame(rows, columns=cols)
    return df.dropna(subset=["date"]).reset_index(drop=True) if not df.empty else df
