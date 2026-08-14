"""GDELT sentiment via BigQuery (gkg_partitioned) — the out-of-band ingestion path.

Replaces bursty live GDELT. Two queries: daily average tone (the sentiment signal)
and per-country theme frequencies (for the word cloud). Used ONLY by scripts/
(backfill/refresh/profiler) — never on the app request path.

COST SAFETY (non-negotiable): every query filters `_PARTITIONDATE`. The table is
date-partitioned; the partition predicate keeps scans tiny and inside the 1 TB/month
free tier. A query without it can scan the whole table — so the partition BETWEEN is
hard-coded into every statement here.

GKG layout assumption (VERIFY with verify_offset() before trusting output): each
`;`-separated entry in V2Locations splits on `#` as Type#FullName#CountryCode#ADM1#…,
so the FIPS 10-4 2-char country code is at SAFE_OFFSET(2). If your inspection shows a
different offset, change _CC_OFFSET below — it is referenced by every query.
"""
from __future__ import annotations

import logging

import pandas as pd

from src.settings import env

log = logging.getLogger(__name__)

TABLE = "gdelt-bq.gdeltv2.gkg_partitioned"
_CC_OFFSET = 2                      # country-code position after SPLIT(loc, '#')
_ECON_THEME_RE = r"ECON_|WB_|EPU_"  # optional economic-theme filter


def available() -> bool:
    """True if the BigQuery client lib + credentials are usable."""
    if not env("GOOGLE_APPLICATION_CREDENTIALS"):
        return False
    try:
        import google.cloud.bigquery  # noqa: F401
        return True
    except Exception:
        return False


def _client():
    from google.cloud import bigquery

    return bigquery.Client()


def _run(sql: str, params: list) -> pd.DataFrame:
    from google.cloud import bigquery

    job = _client().query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params))
    return job.result().to_dataframe(create_bqstorage_client=False)


def _codes_param(codes):
    from google.cloud import bigquery

    return bigquery.ArrayQueryParameter("codes", "STRING", list(codes))


def _date_params(start, end):
    from google.cloud import bigquery

    return [
        bigquery.ScalarQueryParameter("start", "DATE", pd.to_datetime(start).date()),
        bigquery.ScalarQueryParameter("end", "DATE", pd.to_datetime(end).date()),
    ]


def verify_offset(days_back: int = 2) -> pd.DataFrame:
    """Part 1: pull a few raw rows so you can confirm the `#` offset before trusting it."""
    sql = f"""
        SELECT V2Locations, V2Tone, V2Themes
        FROM `{TABLE}`
        WHERE _PARTITIONDATE = DATE_SUB(CURRENT_DATE(), INTERVAL {int(days_back)} DAY)
        LIMIT 5
    """
    return _run(sql, [])


def fetch_tone(codes, start, end, econ_only: bool = False) -> pd.DataFrame:
    """Daily average tone per country → [country_code, date, gdelt_tone, article_count].

    An article mentioning several countries contributes to each (a co-mention measure).
    """
    econ = f"AND REGEXP_CONTAINS(V2Themes, r'{_ECON_THEME_RE}')" if econ_only else ""
    sql = f"""
        WITH per_article AS (
          SELECT
            PARSE_DATE('%Y%m%d', SUBSTR(CAST(DATE AS STRING), 1, 8)) AS date,
            SPLIT(loc, '#')[SAFE_OFFSET({_CC_OFFSET})] AS country_code,
            CAST(SPLIT(V2Tone, ',')[SAFE_OFFSET(0)] AS FLOAT64) AS tone
          FROM `{TABLE}`,
               UNNEST(SPLIT(V2Locations, ';')) AS loc
          WHERE _PARTITIONDATE BETWEEN @start AND @end
            AND V2Locations IS NOT NULL AND V2Tone IS NOT NULL
            {econ}
        )
        SELECT country_code, date, AVG(tone) AS gdelt_tone, COUNT(*) AS article_count
        FROM per_article
        WHERE country_code IN UNNEST(@codes) AND country_code != ''
        GROUP BY country_code, date
        ORDER BY country_code, date
    """
    df = _run(sql, [_codes_param(codes), *_date_params(start, end)])
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def coverage(start, end, econ_only: bool = False) -> pd.DataFrame:
    """Part 2a: sentiment availability for ALL countries → density per country_code."""
    econ = f"AND REGEXP_CONTAINS(V2Themes, r'{_ECON_THEME_RE}')" if econ_only else ""
    sql = f"""
        WITH per_article AS (
          SELECT
            PARSE_DATE('%Y%m%d', SUBSTR(CAST(DATE AS STRING), 1, 8)) AS date,
            SPLIT(loc, '#')[SAFE_OFFSET({_CC_OFFSET})] AS country_code
          FROM `{TABLE}`,
               UNNEST(SPLIT(V2Locations, ';')) AS loc
          WHERE _PARTITIONDATE BETWEEN @start AND @end
            AND V2Locations IS NOT NULL AND V2Tone IS NOT NULL
            {econ}
        ),
        daily AS (
          SELECT country_code, date, COUNT(*) AS n_articles
          FROM per_article
          WHERE country_code IS NOT NULL AND country_code != ''
          GROUP BY country_code, date
        )
        SELECT country_code,
               COUNT(DISTINCT date)      AS distinct_days,
               SUM(n_articles)           AS total_articles,
               ROUND(AVG(n_articles), 1) AS avg_articles_per_day
        FROM daily
        GROUP BY country_code
        ORDER BY distinct_days DESC, total_articles DESC
    """
    return _run(sql, _date_params(start, end))


def fetch_themes(codes, start, end, top: int = 60) -> pd.DataFrame:
    """Per-country theme frequencies for the word cloud → [country_code, theme, count]."""
    sql = f"""
        WITH t AS (
          SELECT
            SPLIT(loc, '#')[SAFE_OFFSET({_CC_OFFSET})] AS country_code,
            theme
          FROM `{TABLE}`,
               UNNEST(SPLIT(V2Locations, ';')) AS loc,
               UNNEST(SPLIT(V2Themes, ';')) AS theme
          WHERE _PARTITIONDATE BETWEEN @start AND @end
            AND V2Locations IS NOT NULL AND V2Themes IS NOT NULL
        )
        SELECT country_code, theme, COUNT(*) AS count
        FROM t
        WHERE country_code IN UNNEST(@codes) AND country_code != '' AND theme != ''
        GROUP BY country_code, theme
        QUALIFY ROW_NUMBER() OVER (PARTITION BY country_code ORDER BY COUNT(*) DESC) <= {int(top)}
        ORDER BY country_code, count DESC
    """
    return _run(sql, [_codes_param(codes), *_date_params(start, end)])
