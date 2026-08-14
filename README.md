# Sentiment-Yield Engine

### Open Regional News-Sentiment × Financial-Market Observatory

An open, transparent analytical platform that turns country-specific news
headlines into daily regional sentiment indicators and examines - honestly - how
that sentiment relates to local financial markets.

> **The headline question:** when a region's news turns more positive or negative,
> do local market returns tend to move with it, and at what lead/lag?
> Everything else in the app exists to make that question explorable and traceable.

**This is** an educational, evidence-first observatory.
**This is not** a market predictor, a trading system, or investment advice.

The entire stack is open-source software over free/openly-accessible data. The one
hosted dependency (a fast LLM API) is optional and swappable for a local model.

---

## Table of contents

1. [Core thesis](#core-thesis)
2. [What V1 does](#what-v1-does)
3. [Architecture](#architecture)
4. [Data flow](#data-flow)
5. [The analytical data model](#the-analytical-data-model)
6. [Configuration](#configuration)
7. [Methodology — exact definitions](#methodology--exact-definitions)
8. [Key implementation decisions](#key-implementation-decisions)
9. [Technology stack](#technology-stack)
10. [Repository structure](#repository-structure)
11. [Quick start (demo mode)](#quick-start-demo-mode)
12. [Going live](#going-live)
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

## What V1 does

A user selects a **region**, one or more **countries**, a **period**, and one or
more **market instruments**, and the app produces an integrated, drill-downable view:

**Ingestion & sentiment**
- GDELT DOC 2.0 ingestion (+ optional RSS), headline cleaning, near-duplicate handling
- VADER polarity per headline → daily aggregation (mean, positive/neutral/negative split, counts)
- GDELT's own average tone pulled in parallel as a second, independent sentiment measure

**Topics & keywords**
- Keyword/topic-dictionary classification per headline (configurable, deterministic)
- Per-topic mention counts and per-topic sentiment
- Word cloud of the period's news landscape

**Events & investigation**
- Statistical event/anomaly detection on the daily sentiment series (z-score + volume)
- Headline drill-down: every aggregate traces back to the underlying titles + sources

**Data quality & source structure**
- Source-diversity and concentration (HHI) diagnostics
- Composite data-quality score (a diagnostic, not a confidence interval)

**Markets & the correlation layer (the point)**
- yfinance market data → returns (equities/FX) or yield changes (bonds), daily-aligned
- Multiple instruments per country, user-selectable
- Sentiment × return scatter (Pearson, Spearman, regression line, n)
- Rolling correlation (adjustable window)
- Lead/lag cross-correlation with the ±1.96/√n approximate band

**Cross-country**
- Side-by-side comparison mode (sentiment, volume, sources, market)
- Choropleth sentiment map, click-through to a country's detail view

**Grounded explanation**
- Optional LLM summary that receives already-computed evidence and explains it,
  context-only, with inline citations - never generating the quantitative conclusions

**Modes**
- **Demo mode** (synthetic data) runs the entire UI with no keys, network, or DB
- **Live mode** switches on real connectors once verified

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        DATA SOURCES                          │
│   GDELT DOC 2.0 (keyless)      Optional RSS (keyless)        │
└───────────────────────────┬──────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────┐
│                      DATA PROCESSING                         │
│   clean → dedup → VADER → topic-tag → daily aggregate        │
│   event detection · source diversity · data-quality score    │
└───────────────────────────┬──────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────┐
│              FINANCIAL DATA (yfinance, keyless)              │
│   price → returns   |   yield → level change (bps)           │
└───────────────────────────┬──────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────┐
│                     ANALYTICAL ENGINE                        │
│   contemporaneous · rolling · lead/lag correlation           │
│   scatter · cross-country comparison                         │
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
```

Ingestion, NLP, analysis, and visualization stay in separate modules so a new
visualization never requires touching the ingestion pipeline.

---

## Data flow

```
GDELT DOC 2.0 (+ optional RSS)
        │
        ▼
ingest → clean → deduplicate
        │
        ├───────────────► VADER sentiment ──┐
        │                                    │
        ├───────────────► topic tagging      │
        │                                    ▼
        │                            daily aggregation
        │                    (sentiment mean/split, counts,
        │                     topic counts/sentiment, keywords)
        │                                    │
        ├───────────────► event detection ◄──┤
        ├───────────────► source diversity ◄─┤
        ├───────────────► data-quality score ┤
        │                                    ▼
        │                    REGIONAL ANALYTICAL DATASET  ◄── single UI contract
        │                                    │
        │            ┌───────────────────────┼───────────────────────┐
        ▼            ▼                        ▼                       ▼
  yfinance     correlation engine     cross-country compare     LLM summary
 returns/yields (contemp/rolling/lag)   + choropleth map      (grounded, cited)
        └────────────────────────────► Streamlit UI ◄──────────────────┘
```

---

## The analytical data model

The pipeline's job is to produce one tidy analytical dataset per (country, date).
The Streamlit app consumes **this layer only** - never raw ingestion. This is what
lets you add visualizations cheaply.

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

`config/regions.yaml`:

```yaml
# Applied to every country's GDELT pull.
base_query: '(economy OR inflation OR "interest rate" OR "central bank" OR market OR recession OR GDP OR unemployment)'

# Region metadata (labels + map grouping). Add regions here; add countries below.
regions:
  north_america: { label: North America }
  europe:        { label: Europe }
  asia_pacific:  { label: Asia-Pacific }
  united_kingdom:{ label: United Kingdom }

countries:
  - id: united_states
    label: United States
    region: north_america
    gdelt: { source_country: US, source_lang: english }   # GDELT FIPS-style codes — VERIFY live
    rss: [ "https://feeds.a.dj.com/rss/RSSMarketsMain.xml" ]
    instruments:
      - { ticker: "^GSPC",  label: S&P 500,   asset_type: equity_index, series_type: price }
      - { ticker: "^TNX",   label: US 10Y,    asset_type: bond,         series_type: yield }

  - id: germany
    label: Germany
    region: europe
    gdelt: { source_country: GM, source_lang: english }
    rss: []
    instruments:
      - { ticker: "^GDAXI",   label: DAX,     asset_type: equity_index, series_type: price }
      - { ticker: "EURUSD=X", label: EUR/USD, asset_type: fx,           series_type: price }

  - id: japan
    label: Japan
    region: asia_pacific
    gdelt: { source_country: JA, source_lang: english }
    rss: []
    instruments:
      - { ticker: "^N225", label: Nikkei 225, asset_type: equity_index, series_type: price }

  - id: united_kingdom
    label: United Kingdom
    region: united_kingdom
    gdelt: { source_country: UK, source_lang: english }
    rss: []
    instruments:
      - { ticker: "^FTSE", label: FTSE 100, asset_type: equity_index, series_type: price }
```

- `series_type: price` → daily simple returns (`pct_change`).
- `series_type: yield` → daily **level change** (never a percentage return of a yield).
- **Verify every ticker and every GDELT country code against a live call before trusting it.**

---

## Methodology - exact definitions

State these in the UI. Vague aggregates are what get picked apart in interviews.

**Sentiment signal — GDELT tone (production/snapshot path).**
- `sentiment_mean` for a (country, date) = GDELT **average tone** over that day's
  matching articles (from BigQuery `gdelt-bq.gdeltv2.gkg_partitioned`), normalised to
  −1…+1. Country attribution is by V2Locations on a **co-mention** basis — an article
  mentioning several countries contributes to each.
- Daily polarity classification: tone `> +0.5` positive, `< −0.5` negative, else neutral.
- Word cloud = standardized GDELT **themes** (e.g. `ECON_INFLATION`), not article text.
- *Legacy VADER path* (demo + local `DATA_MODE=live`): `sentiment_mean` = mean VADER
  compound over that day's headline titles; polarity `compound ≥ +0.05` positive,
  `≤ −0.05` negative, else neutral. Retired from the production path; retained for demo
  and the frozen methodology test.

**Event / anomaly detection.** On the daily sentiment series `s_t`, maintain a rolling
30-day mean and std, and flag day *t* when **any** of:
- `|z_t| ≥ 2` where `z_t = (s_t − rolling_mean) / rolling_std`, or
- article-volume z-score `≥ 2` (abnormal coverage).
`event_score = |z_t|`. A flag means *"an unusual movement in the observed data
occurred here"* - never *"this caused the market move."*

**Source concentration (HHI).** With source shares `p_i` (fraction of the period's
articles from source *i*): `HHI = Σ p_i²`, reported normalized to 0-1. Higher = more
concentrated (fewer voices). Displayed alongside raw article/source counts.

**Data-quality score (0-100, a diagnostic - NOT a confidence interval).** A weighted
blend of normalized sub-scores, each clipped to [0, 1]:

| Component | Definition | Default weight |
|---|---|---|
| Volume | `min(article_count / target, 1)` | 0.25 |
| Source diversity | `1 − HHI` | 0.20 |
| Duplicate cleanliness | `1 − duplicate_rate` | 0.15 |
| Temporal coverage | `days_with_data / days_in_window` | 0.20 |
| Scoring success | `scored_headlines / total_headlines` | 0.20 |

`score = 100 × Σ(weight × component)`. Weights and `target` live in config.

**Correlation band.** Under the null of no cross-correlation, the sample correlation
is ≈ `N(0, 1/n)`, so the app draws an **approximate** 95% band at `±1.96/√n`. Label it
approximate. It is not a valid significance test under autocorrelation - Newey-West /
Bartlett corrections are future work (see roadmap).

**Lead/lag convention.** `lag > 0` → sentiment leads the market
(`corr(sentiment_t, return_{t+lag})`); `lag < 0` → market leads sentiment; the peak
`|corr|` lag is highlighted, subject to the band above.

---

## Key implementation decisions

These are deliberate calls for V1. Each is overridable, but change them knowingly.

- **LLM = Groq-hosted Llama 3 by default.** The summariser sits behind a thin
  `summarize(evidence) -> str` interface, so a local open-weight model (Ollama /
  llama.cpp) is a drop-in swap. *Why default to Groq:* a deployed public app can't
  serve a 7B+ model on free Streamlit/HF infrastructure; this keeps V1 live-deployable
  while the architecture stays open and model-agnostic. The LLM is explanatory only -
  the quantitative results never depend on it.
- **Topics = keyword/topic dictionaries in V1.** Deterministic, interpretable, and
  trusted precisely *because* they're transparent. Embeddings → BERTopic is a
  documented upgrade path, not a V1 dependency (label drift is a V2 problem).
- **Map = Plotly `choropleth`.** Uses built-in world geometries - no Folium/GeoPandas,
  which frequently break Streamlit Community Cloud's build environment.
- **VADER on titles.** GDELT's API returns headline metadata, not article bodies. The
  UI states this limitation plainly.

---

## Technology stack

**Core:** Python · pandas · NumPy · SciPy · scikit-learn
**News:** GDELT DOC 2.0 API · optional RSS (`feedparser`)
**Sentiment:** `vaderSentiment`
**Topics (V1):** configurable keyword dictionaries (scikit-learn TF-IDF available for keyphrases)
**Financial data:** `yfinance`
**Visualization:** Streamlit · Plotly (charts + choropleth) · `wordcloud`
**LLM (optional):** Groq SDK (default) · local open-weight runtime (swappable)
**Persistence (optional):** PostgreSQL · pgvector · Supabase

Keyless data sources: GDELT, RSS, yfinance. Only the LLM (and optional DB) need secrets.

---

## Repository structure

```
sentiment-yield-engine/
├── app/
│   └── streamlit_app.py          # consumes the analytical layer only
├── config/
│   └── regions.yaml              # countries, regions, instruments (single source of truth)
├── src/
│   ├── ingest/    { gdelt.py, rss.py }
│   ├── nlp/       { sentiment.py, topics.py, keywords.py, summaries.py }
│   ├── finance/   { market.py }
│   ├── analysis/  { aggregation.py, correlation.py, rolling.py,
│   │               events.py, diversity.py, quality.py, comparison.py }
│   ├── visualization/ { sentiment.py, topics.py, market.py, geography.py, comparison.py }
│   ├── pipeline.py               # orchestrates ingest → analytical dataset
│   └── settings.py               # config + env loader, DATA_MODE
├── data/        { raw/, processed/, cache/ }
├── tests/
├── .env.example
├── requirements.txt
├── README.md
└── LICENSE
```

Keep the four layers - ingestion, NLP, analysis, visualization — cleanly separated.

---

## Quick start (demo mode)

```bash
python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app/streamlit_app.py
```

The app starts in **demo mode** (`DATA_MODE = "demo"`) on synthetic data - the full
interface renders with no API keys, network, or database. Use it to build and review
every visualization before wiring live connectors.

---

## Going live

1. `cp .env.example .env` and fill in the values you need (only the LLM/DB are secret).
2. Verify the live connectors end-to-end:
   ```bash
   python -m src.pipeline
   ```
   This is where you confirm GDELT country codes and JSON fields, that every yfinance
   ticker resolves, and that the Groq model id is current.
3. Flip `DATA_MODE = "live"` in `src/settings.py`.

`.env.example`:

```
GROQ_API_KEY=
GROQ_MODEL=llama-3.3-70b-versatile   # verify against Groq's current model list

# Optional persistence
SUPABASE_URL=
SUPABASE_KEY=
DATABASE_URL=
```

---

## Deployment

**Streamlit Community Cloud** - point it at `app/streamlit_app.py`; put secrets in the
app's Secrets panel (mirrors `.env`). GDELT/yfinance need no keys.

**Hugging Face Spaces (Streamlit template)** - same entrypoint; set secrets in Space
settings. Both free tiers comfortably run V1 in live mode (Groq offloads the LLM).

Keep `.env`, `.streamlit/secrets.toml`, and any cached data out of git (`.gitignore`).

---

## Optional persistence (pgvector)

Not required for V1. When you want history, embeddings, and semantic retrieval for the
LLM layer, enable Supabase + pgvector: store articles with embeddings, retrieve top-k
by cosine similarity to feed the grounded summariser. The app must degrade gracefully
and stay fully functional with persistence off.

---

## Honesty notes

Keep these visible in the app - they are the point, not fine print.

- **News sampling** - sentiment comes from a *convenience sample* of available
  headlines, not a statistically representative panel.
- **Text limitation** - VADER runs on *headlines/titles*, not full article bodies.
- **Source concentration** - many articles ≠ broad coverage; diversity and HHI are shown.
- **Topic detection** - topics are analytical groupings and can misclassify.
- **Event detection** - a flag marks an unusual data movement, not a real-world cause.
- **Correlation** - measures association, not causation.
- **Lead/lag** - temporal association, not proof of causal precedence.
- **Statistical band** - `±1.96/√n` is approximate and unreliable under autocorrelation.
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

---

## Roadmap - deliberately deferred

Stated here on purpose: knowing what to leave out is part of the design.

- Embedding-based / BERTopic topic modelling (replacing V1 keyword dictionaries)
- Newey-West / Bartlett-corrected correlation inference
- Interactive word-cloud → headline click-through
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
