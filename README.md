# Sentiment-Yield Engine

### Open Global News-Sentiment × Financial-Market Observatory

An open, transparent analytical platform that turns country-specific news
headlines into daily regional sentiment indicators and examines - honestly - how
that sentiment relates to local financial markets.

> **The headline question:** when a country's news turns more positive or negative,
> do local market returns tend to move with it, and at what lead/lag?
> Everything else in the app exists to make that question explorable and traceable.

**This is** an educational, evidence-first observatory.
**This is not** a market predictor, a trading system, or investment advice.

The entire stack is open-source software over free/openly-accessible data. The one
hosted dependency (a fast LLM API) is optional and swappable for a local model.

---

## Table of contents

1. [Core thesis](#core-thesis)
2. [What it does](#what-it-does)
3. [Architecture](#architecture)
4. [Data flow](#data-flow)
5. [The analytical data model](#the-analytical-data-model)
6. [Configuration](#configuration)
7. [Methodology — exact definitions](#methodology--exact-definitions)
8. [Key implementation decisions](#key-implementation-decisions)
9. [Technology stack](#technology-stack)
10. [Repository structure](#repository-structure)
11. [Quick start (demo mode)](#quick-start-demo-mode)
12. [Refreshing the snapshot](#refreshing-the-snapshot)
13. [Deployment](#deployment)
14. [Optional persistence (pgvector)](#optional-persistence-pgvector)
15. [Honesty notes](#honesty-notes)
16. [Methodological principles](#methodological-principles)
17. [Roadmap — deliberately deferred](#roadmap--deliberately-deferred)
18. [Disclaimer](#disclaimer)

---

## Core thesis

Traditional dashboards start from prices. This one starts from information:

```
News & headlines → sentiment → topics/events → markets → statistical relationship
```

The differentiating signal is the **sentiment × market correlation layer**
(contemporaneous, rolling, and lead/lag, with an honest uncertainty band). Every
other feature - topics, word cloud, events, source diversity, the map — is context
that makes that correlation interpretable and traceable back to real headlines. Keep
the correlation result the headline of the UI; do not let the breadth bury it.

---

## What it does

A user selects a **region**, one or more **countries**, a **period**, and one or
more **market instruments**, and the app produces an integrated, drill-downable view.
The deployed app runs in **snapshot mode** — reading a pre-backfilled, scheduled-refresh
dataset rather than calling any live API on the request path (see
[Architecture](#architecture)). Some features have real data available in every mode;
a few depend on per-article data that snapshot mode doesn't store, and degrade
honestly rather than silently.

**Ingestion & sentiment**
- GDELT's own daily average tone per country, sourced via Google BigQuery
  (`gdelt-bq.gdeltv2.gkg_partitioned`) — the production/snapshot signal
- VADER polarity per headline is a *legacy* path, retained for demo mode and the
  frozen methodology test; not the production signal

**Topics & word cloud**
- Word cloud of the period's news landscape from GDELT's own standardized **themes**
  (e.g. `MANMADE_DISASTER_TRAIN_COLLISION`), date-aware — it responds to the period
  selector, not a fixed whole-snapshot total
- Per-topic mention counts and per-topic sentiment:
  - **Demo mode** — keyword/topic-dictionary classification per synthetic headline
  - **Snapshot mode** — the same date-aware GDELT theme data as the word cloud;
    "sentiment" per theme is a **daily co-occurrence proxy** (the country's own
    daily tone on the days that theme was mentioned, mention-count-weighted), not
    per-headline sentiment — snapshot mode has no article-level text to compute that

**Events & investigation**
- Statistical event/anomaly detection on the daily sentiment series (z-score + volume)
- Headline drill-down where per-article data exists (demo mode); snapshot mode
  traces to the theme/day level instead, since individual headlines aren't stored

**Data quality & source structure**
- Composite data-quality score (a diagnostic, not a confidence interval) — computed
  honestly in every mode; snapshot mode's inputs it can't measure (source diversity,
  duplicate cleanliness, scoring success) get 0 credit rather than a fabricated 1.0
- Source-diversity/concentration (HHI) needs per-article domain data — available in
  demo mode; in snapshot mode the chart is replaced by a plain explanation rather
  than an empty axis (real per-domain snapshot data is a documented roadmap item)

**Markets & the correlation layer (the point)**
- FRED (FX, US index/yield) + Twelve Data (national equity indices) → returns
  (equities/FX) or yield changes (bonds), daily-aligned. yfinance is fully retired
  from the live/production path
- Multiple instruments per country, user-selectable; every panel entry is classified
  `floating` / `pegged` / `dollarized` / `unlinked` by real, documented monetary links
  — never a reserve-currency stand-in
- Sentiment × return scatter (Pearson, Spearman, regression line, n)
- Rolling correlation (adjustable window)
- Lead/lag cross-correlation with the ±1.96/√n approximate band

**Cross-country**
- Side-by-side comparison mode (sentiment, volume, sources, market)
- Choropleth sentiment map, click-through to a country's detail view
- ~197 countries: 193 UN member states + Hong Kong, Macau, Taiwan (major financial
  centers) and Kosovo (real government, no ISO-3 code). The panel spans a full
  spectrum by design — full sentiment+FX+index, FX-only, index-only, pegged-currency,
  dollarized, and sentiment-only countries all coexist, and the UI renders every
  state gracefully rather than assuming complete data

**Grounded explanation**
- Optional LLM summary that receives already-computed evidence and explains it,
  context-only, with inline citations - never generating the quantitative conclusions

**Modes** (`DATA_MODE` in `src/settings.py` / env)
- **`demo`** (synthetic data) runs the entire UI with no keys, network, or DB — also
  the default for a local run unless `DATA_MODE` is set explicitly
- **`snapshot`** (deployed default) reads `data/snapshot/*.parquet`, refreshed out of
  band on a schedule — no live fetch on the user request path
- **`live`** exists in code (direct GDELT/FRED/Twelve Data calls) and is verified
  locally, but is not what's deployed — live GDELT's plain web API rate-limits
  aggressively, which is exactly why the BigQuery/snapshot path exists

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        DATA SOURCES                          │
│   GDELT via BigQuery          FRED           Twelve Data     │
│   (gkg_partitioned,        (FX, US index/  (national equity  │
│    keyless + GCP SA key)     yield, keyless)  indices, key)  │
└───────────────────────────┬──────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────┐
│         OUT-OF-BAND BACKFILL (scripts/backfill.py,            │
│         scheduled via GitHub Actions daily cron)              │
│   tone → sentiment.parquet     themes → themes.parquet        │
│   (date-aware, top-K/day)      market → market.parquet        │
└───────────────────────────┬──────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────┐
│              data/snapshot/*.parquet (the snapshot)           │
│   The deployed app reads ONLY this — no live call on the      │
│   user request path in DATA_MODE=snapshot.                    │
└───────────────────────────┬──────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────┐
│                     ANALYTICAL ENGINE                        │
│   contemporaneous · rolling · lead/lag correlation           │
│   event detection · data-quality score · scatter             │
│   cross-country comparison                                   │
└───────────────────────────┬──────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────┐
│           OPTIONAL LLM (Groq default · local swappable)     │
│   grounded, cited, evidence-only summaries                   │
└───────────────────────────┬──────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────┐
│                       PRESENTATION                          │
│   Streamlit · Plotly (charts + choropleth) · wordcloud       │
└──────────────────────────────────────────────────────────────┘
   Optional persistence: PostgreSQL + pgvector (Supabase)
   DATA_MODE=demo bypasses everything above the analytical engine
   with synthetic data; DATA_MODE=live calls sources directly,
   synchronously, on the request path (not deployed).
```

Ingestion, NLP, analysis, and visualization stay in separate modules so a new
visualization never requires touching the ingestion pipeline. The UI
(`app/streamlit_app.py`) calls only `pipeline.build_*` — never `ingest/`, `nlp/`,
or `finance/` directly.

---

## Data flow

The deployed (`snapshot`) path has two independent flows: an **offline backfill**
that populates the snapshot, and the **app's read path** that only ever consumes it.

```
OFFLINE, SCHEDULED (scripts/backfill.py / refresh.py):

GDELT (BigQuery)  ──► tone ──────────────┐
                   └─► themes (date-aware)┤
FRED / Twelve Data ─► market series ──────┤
                                           ▼
                          data/snapshot/{sentiment,market,themes,meta}.parquet


APP REQUEST PATH (DATA_MODE=snapshot):

data/snapshot/*.parquet
        │
        ▼
pipeline.build_country_from_snapshot()  ◄── period-sliced per country
        │
        ├───────────────► event detection
        ├───────────────► data-quality score (honest 0-credit for what
        │                  snapshot mode can't measure)
        │                                    ▼
        │                    REGIONAL ANALYTICAL DATASET  ◄── single UI contract
        │                                    │
        │            ┌───────────────────────┼───────────────────────┐
        ▼            ▼                        ▼                       ▼
   market series  correlation engine   cross-country compare     LLM summary
  (from snapshot)  (contemp/rolling/lag) + choropleth map       (grounded, cited)
        └────────────────────────────► Streamlit UI ◄──────────────────┘
```

`DATA_MODE=demo` and `DATA_MODE=live` bypass the snapshot files entirely — demo
generates synthetic data through the same analytical-assembly code, live calls
GDELT/FRED/Twelve Data directly and synchronously.

---

## The analytical data model

The pipeline's job is to produce one tidy analytical dataset per (country, date).
The Streamlit app consumes **this layer only** - never raw ingestion. This is what
lets you add visualizations cheaply. Column meaning is mode-aware in a couple of
places — see [Methodology](#methodology--exact-definitions) for exactly how
`topic_counts`/`topic_sentiment` and `source_concentration` differ between demo and
snapshot mode.

```
region                       market_instrument
country                      market_return
date                         market_yield_change
                             market_volatility
article_count
source_count                 sentiment_mean
duplicate_rate               sentiment_median
source_concentration (HHI)   sentiment_positive_share
                             sentiment_neutral_share
top_topics                   sentiment_negative_share
topic_counts
topic_sentiment              event_flag
keywords                     event_score
                             data_quality_score
gdelt_tone_mean
```

---

## Configuration

Adding a country or instrument is **a config edit, never a code change**. Countries
are declared flat and tagged with a region (the region drives grouping and the map).
`config/regions.yaml` is the single source of truth for ~197 countries; below is one
real entry, trimmed to shape:

```yaml
# Applied to every country's GDELT pull.
base_query: '(economy OR inflation OR "interest rate" OR "central bank" OR market OR recession OR GDP OR unemployment)'

# Data-source cadences (drives the two-speed cache + freshness labels).
sources:
  fred: {cadence: weekly}
  twelvedata: {cadence: daily}
  gdelt: {cadence: daily}

regions:
  europe: {label: Europe}
  # ... north_america, asia_pacific, latin_america, africa_mideast

countries:
  - id: belgium
    label: Belgium
    region: europe
    currency: EUR
    monetary_regime: floating        # floating | pegged | dollarized | unlinked
    peg_to:
    label_note: Own currency
    gdelt:
      source_country: BE             # GDELT FIPS-style code — VERIFY live
      source_lang: english
    instruments:
      - type: fx
        label: EUR/USD
        source: fred                 # fred | twelvedata — pinned, never a runtime fallback
        source_id: DEXUSEU
        series_type: price
      - type: index
        label: Belgium index (EWK)
        source: twelvedata
        source_id: EWK
        series_type: price
    iso3: BEL
```

- `series_type: price` → daily simple returns (`pct_change`).
- `series_type: yield` → daily **level change** (never a percentage return of a yield).
- `source` is fixed per instrument, never a runtime fallback chain — a stale cached
  value is preferred over silently switching data provider.
- `monetary_regime: pegged` uses the **anchor currency's own** FRED series (e.g. the
  CFA franc pegs to EUR at a fixed, documented rate — no separate series needed).
  `dollarized` countries carry no FX instrument at all. Never assign a reserve-currency
  stand-in without a real, documented, citable monetary link.
- **Verify every source_id and every GDELT country code against a live call before
  trusting it.**

---

## Methodology - exact definitions

State these in the UI. Vague aggregates are what get picked apart in interviews.

**Sentiment signal — GDELT tone (production/snapshot path).**
- `sentiment_mean` for a (country, date) = GDELT **average tone** over that day's
  matching articles (from BigQuery `gdelt-bq.gdeltv2.gkg_partitioned`), normalised to
  −1…+1. Country attribution is by V2Locations on a **co-mention** basis — an article
  mentioning several countries contributes to each.
- Daily polarity classification: tone `> +0.5` positive, `< −0.5` negative, else neutral.
- Word cloud = standardized GDELT **themes** (e.g. `ECON_INFLATION`), not article text,
  and date-aware: top-20 themes per (country, day), sliced to the selected period —
  not a fixed whole-snapshot total.
- *Legacy VADER path* (demo + local `DATA_MODE=live`): `sentiment_mean` = mean VADER
  compound over that day's headline titles; polarity `compound ≥ +0.05` positive,
  `≤ −0.05` negative, else neutral. Retired from the production path; retained for demo
  and the frozen methodology test.

**Per-topic mention counts and sentiment.**
- *Demo mode:* keyword/topic-dictionary classification per synthetic headline, with
  real per-headline VADER sentiment averaged per topic.
- *Snapshot mode:* mention counts are the same date-aware GDELT theme counts behind
  the word cloud. Per-theme "sentiment" is a **co-occurrence proxy**: the country's
  own daily `sentiment_mean` on each day a theme was mentioned, averaged across those
  days weighted by that day's mention count. This is deliberately *not* presented as
  per-article sentiment — snapshot mode stores no article-level text, so there is no
  honest way to compute that directly. It answers "was the country's overall tone
  positive or negative on the days this theme was prominent," not "how do articles
  mentioning this theme individually read."

**Event / anomaly detection.** On the daily sentiment series `s_t`, maintain a rolling
30-day mean and std, and flag day *t* when **any** of:
- `|z_t| ≥ 2` where `z_t = (s_t − rolling_mean) / rolling_std`, or
- article-volume z-score `≥ 2` (abnormal coverage).
`event_score = |z_t|`. A flag means *"an unusual movement in the observed data
occurred here"* - never *"this caused the market move."*

**Source concentration (HHI).** With source shares `p_i` (fraction of the period's
articles from source *i*): `HHI = Σ p_i²`, reported normalized to 0-1. Higher = more
concentrated (fewer voices). Requires per-article domain data — available in demo
mode; snapshot mode doesn't store it, so the chart is replaced by an explanation
rather than computed on nothing.

**Data-quality score (0-100, a diagnostic - NOT a confidence interval).** A weighted
blend of normalized sub-scores, each clipped to [0, 1]:

| Component | Definition | Default weight |
|---|---|---|
| Volume | `min(article_count / target, 1)` | 0.25 |
| Source diversity | `1 − HHI` | 0.20 |
| Duplicate cleanliness | `1 − duplicate_rate` | 0.15 |
| Temporal coverage | `days_with_data / days_in_window` | 0.20 |
| Scoring success | `scored_headlines / total_headlines` | 0.20 |

`score = 100 × Σ(weight × component)`. Weights and `target` live in config. In
snapshot mode, three of the five inputs (source diversity, duplicate cleanliness,
scoring success) genuinely can't be measured — they get 0 credit for "not measured,"
never a fabricated 1.0 that would inflate the score into looking like a full
5-dimension measurement.

**Correlation band.** Under the null of no cross-correlation, the sample correlation
is ≈ `N(0, 1/n)`, so the app draws an **approximate** 95% band at `±1.96/√n`. Label it
approximate. It is not a valid significance test under autocorrelation - Newey-West /
Bartlett corrections are future work (see roadmap).

**Lead/lag convention.** `lag > 0` → sentiment leads the market
(`corr(sentiment_t, return_{t+lag})`); `lag < 0` → market leads sentiment; the peak
`|corr|` lag is highlighted, subject to the band above.

---

## Key implementation decisions

These are deliberate calls. Each is overridable, but change them knowingly.

- **Snapshot-first, not live-first.** The deployed app reads a scheduled, out-of-band
  backfill (`data/snapshot/*.parquet`) rather than calling GDELT/FRED/Twelve Data on
  the user request path. *Why:* live GDELT's plain web API rate-limits aggressively
  even from a paced local IP; BigQuery reads Google's own mirror instead, and a
  snapshot means the deployed app's latency and reliability don't depend on any
  third-party API being up at request time. The tradeoff is honest: snapshot mode has
  no per-article data, so a few features (source concentration, per-headline topic
  tagging) either fall back to a coarser but real proxy or are hidden with an
  explanation, never faked.
- **LLM = Groq-hosted Llama 3 by default.** The summariser sits behind a thin
  `summarize(evidence) -> str` interface, so a local open-weight model (Ollama /
  llama.cpp) is a drop-in swap. *Why default to Groq:* a deployed public app can't
  serve a 7B+ model on free Streamlit infrastructure; this keeps the app
  live-deployable while the architecture stays open and model-agnostic. The LLM is
  explanatory only - the quantitative results never depend on it.
- **Topics = keyword/topic dictionaries in demo mode; GDELT's own theme taxonomy in
  snapshot mode.** Both are deterministic and interpretable, trusted precisely
  *because* they're transparent. Embeddings → BERTopic is a documented upgrade path,
  not a dependency (label drift is a later problem).
- **Every market instrument is pinned to exactly one data source in config** — never
  a runtime fallback chain between providers. A stale cached value is preferred over
  a different-provider value, which would break reproducibility silently.
- **Map = Plotly `choropleth`.** Uses built-in world geometries - no Folium/GeoPandas,
  which frequently break Streamlit Community Cloud's build environment.
- **VADER on titles (demo/live only).** GDELT's API returns headline metadata, not
  article bodies, even outside the snapshot path. The UI states this limitation
  plainly.

---

## Technology stack

**Core:** Python · pandas · NumPy · SciPy · scikit-learn
**News/sentiment:** GDELT via Google BigQuery (`google-cloud-bigquery`, `db-dtypes`) — production/snapshot;
optional RSS (`feedparser`) and the legacy live GDELT DOC 2.0 path
**Sentiment (legacy/demo):** `vaderSentiment`
**Topics:** GDELT theme taxonomy (snapshot) · configurable keyword dictionaries (demo)
**Financial data:** FRED + Twelve Data (`pandas-datareader`, `requests`) — yfinance is
fully retired from the live/production path, kept only for a frozen legacy test
**Snapshot store:** `pyarrow` (parquet)
**Visualization:** Streamlit · Plotly (charts + choropleth) · `wordcloud`
**LLM (optional):** Groq SDK (default) · local open-weight runtime (swappable)
**Persistence (optional):** PostgreSQL · pgvector · Supabase

Keyless data sources: GDELT (BigQuery needs a GCP service account, not an API key),
FRED, RSS. Twelve Data needs a free API key. Only the LLM, Twelve Data, and optional
DB need secrets.

---

## Repository structure

```
sentiment-yield-engine/
├── app/
│   └── streamlit_app.py          # consumes the analytical layer only
├── config/
│   └── regions.yaml              # ~197 countries, regions, instruments (single source of truth)
├── scripts/
│   ├── backfill.py                # fills data/snapshot/*.parquet (full or --themes-only/--market-only)
│   ├── refresh.py                 # incremental (new-days-only) refresh, run by GitHub Actions daily
│   ├── profile_coverage.py        # panel coverage profiling
│   ├── build_country_lookup.py    # derives the UN-member + exceptions country list, sourced pegs
│   └── merge_regions.py           # merges a generated panel into the live config/regions.yaml
├── src/
│   ├── ingest/    { gdelt_bq.py, gdelt.py, rss.py, clean.py }   # gdelt_bq.py = production; gdelt.py = legacy live path
│   ├── nlp/       { sentiment.py, topics.py, keywords.py, summaries.py }
│   ├── finance/   { market.py }                                  # FRED + Twelve Data
│   ├── analysis/  { aggregation.py, correlation.py, rolling.py,
│   │               events.py, diversity.py, quality.py, comparison.py }
│   ├── visualization/ { sentiment.py, topics.py, market.py, geography.py,
│   │                    comparison.py, diagnostics.py, theme.py, _layout.py }
│   ├── pipeline.py               # orchestrates: demo | snapshot | live → analytical dataset
│   ├── snapshot.py               # reads/writes data/snapshot/*.parquet
│   ├── demo.py                   # synthetic data generator (DATA_MODE=demo)
│   └── settings.py               # config + env loader, DATA_MODE
├── data/        { snapshot/, raw/, processed/, cache/ }
├── .github/workflows/refresh.yml # daily incremental snapshot refresh
├── tests/
├── .env.example
├── requirements.txt
├── README.md
├── CLAUDE.md                     # architecture decisions, known pitfalls, current state
└── LICENSE
```

Keep the layers - ingestion, NLP, analysis, visualization — cleanly separated. The
UI never imports `ingest/`, `nlp/`, or `finance/` directly, only `pipeline.build_*`.

---

## Quick start (demo mode)

```bash
python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app/streamlit_app.py
```

A local run defaults to **demo mode** (`DATA_MODE` unset → `"demo"`) on synthetic
data - the full interface renders with no API keys, network, or database. This is
also the easiest way to review a UI change quickly, since it needs nothing external.
To exercise the real deployed data path locally instead, set `DATA_MODE=snapshot`
before running (needs `data/snapshot/*.parquet` populated — see next section) — the
page will otherwise silently run in demo mode with no error, just a slower load.

---

## Refreshing the snapshot

This is the actual production data-refresh mechanism — the deployed app never
fetches live.

```bash
set GOOGLE_APPLICATION_CREDENTIALS=<path to a GCP service-account key, no quotes>
set TWELVE_DATA_API_KEY=<real key>

python scripts/profile_coverage.py --min-days 120 --min-avg 5 --months 6   # if re-profiling the panel
python scripts/backfill.py --months 6                                       # full: sentiment + market + themes
python scripts/backfill.py --themes-only --months 6                         # themes only, keeps sentiment+market
python scripts/backfill.py --market-only                                    # market only, keeps sentiment+themes

git add data/snapshot config/regions.yaml
git commit -m "..." && git push   # Streamlit Cloud auto-redeploys on push to main
```

A GitHub Actions daily cron (`.github/workflows/refresh.yml`) runs an incremental
(new-days-only) refresh automatically — a manual full backfill is only needed when
re-profiling the panel or changing what's fetched (e.g. adding date-aware themes).

BigQuery cost is driven by the date range scanned, not by country count — the
`country_code IN (...)` filter applies after the partition scan, so querying 197
countries costs about the same as querying 5. Every query carries a hard byte cap
(`maximum_bytes_billed`, tunable via `BQ_MAX_BYTES_BILLED`) as a backstop.

**Going fully live instead** (calling GDELT/FRED/Twelve Data directly on the request
path, bypassing the snapshot) is supported in code via `DATA_MODE=live` but is not
what's deployed, for the reasons in [Key implementation decisions](#key-implementation-decisions).

---

## Deployment

**Streamlit Community Cloud** - point it at `app/streamlit_app.py`; set these in the
app's Secrets panel:

```
DATA_MODE = "snapshot"
TWELVE_DATA_API_KEY = "..."
GROQ_API_KEY = "..."
GROQ_MODEL = "llama-3.3-70b-versatile"
```

`GCP_SA_KEY` (the BigQuery service-account credential) is **not** needed in Streamlit
secrets — snapshot mode never calls BigQuery live. It **is** needed as a GitHub
Actions repository secret, for the scheduled refresh workflow, stored as a secret
string and materialized to a temp file at startup (Streamlit Cloud has no persistent
filesystem for a file-path credential).

Never put a `[theme]` section in `.streamlit/config.toml` — even one with only
`primaryColor`/`font` disables the platform's native System/Light/Dark viewer switch.
Apply brand colors via the CSS-injection block in `app/streamlit_app.py` instead.

Keep `.env`, `.streamlit/secrets.toml`, `gca.json`, and any cached data out of git
(`.gitignore`).

---

## Optional persistence (pgvector)

Not required currently. When you want history, embeddings, and semantic retrieval for
the LLM layer, enable Supabase + pgvector: store articles with embeddings, retrieve
top-k by cosine similarity to feed the grounded summariser. The app must degrade
gracefully and stay fully functional with persistence off.

---

## Honesty notes

Keep these visible in the app - they are the point, not fine print.

- **News sampling** - sentiment comes from a *convenience sample* of available
  headlines/articles, not a statistically representative panel.
- **Text limitation** - the sentiment signal runs on *headlines/tone metadata*, not
  full article bodies, in every mode.
- **Snapshot-mode per-article gaps** - source concentration and per-headline topic
  tagging need article-level data the snapshot doesn't store. Per-topic sentiment in
  snapshot mode is a daily co-occurrence proxy, explicitly not per-article sentiment;
  source concentration is hidden with an explanation rather than shown empty.
- **Source concentration** - many articles ≠ broad coverage; diversity and HHI are
  shown where the underlying per-article data exists.
- **Topic detection** - topics are analytical groupings and can misclassify.
- **Event detection** - a flag marks an unusual data movement, not a real-world cause.
- **Correlation** - measures association, not causation.
- **Lead/lag** - temporal association, not proof of causal precedence.
- **Statistical band** - `±1.96/√n` is approximate and unreliable under autocorrelation.
- **Shared currency** - euro-area countries co-move with one ECB-set EUR/USD rate;
  a per-country chart there is co-movement with a shared currency, not a
  country-specific FX effect.
- **LLM summaries** - an explanatory layer over retrieved evidence; it can still err and
  must **never** be described as hallucination-free.
- **Financial interpretation** - exploratory and educational; not investment advice.

---

## Methodological principles

- **Transparency** - every aggregate traces to its underlying observations.
- **Reproducibility** - deterministic, documented transformations wherever possible.
- **Open tooling** - open-source analytical and visualization stack.
- **Evidence before interpretation** - show the headlines/data before any AI explanation.
- **Association ≠ causation** - correlation and lead/lag never establish causality.
- **No predictive claims by default** - an observatory, not a trading system.
- **Honest degradation over fabricated completeness** - a metric snapshot mode can't
  measure gets 0 credit or an explanation, never a value that pretends it was measured.

---

## Roadmap - deliberately deferred

Stated here on purpose: knowing what to leave out is part of the design.

- Per-article domain data in the snapshot, to enable real source-concentration
  outside demo mode (a new BigQuery field, `SourceCommonName` — feasible, not yet built)
- Embedding-based / BERTopic topic modelling (replacing keyword dictionaries)
- Newey-West / Bartlett-corrected correlation inference
- Interactive word-cloud → theme/day click-through (surface the top theme(s) for a
  flagged event day directly in the UI, instead of a manual cross-reference)
- Historical timeline explorer synchronizing sentiment, events, and markets
- Local open-weight LLM as the default summariser
- pgvector semantic retrieval wired into the LLM layer as standard

---

## Disclaimer

Educational, exploratory research tool. It does not provide financial, investment, or
trading advice, and makes no representation that its data samples are representative or
its relationships causal. Verify all data sources and instruments independently before
relying on any output.

## Author
Etienne Landry Bessala
(etienne.landry.bessala@gmail.com)
