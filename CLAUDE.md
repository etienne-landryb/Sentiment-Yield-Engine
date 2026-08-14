# CLAUDE.md — Sentiment-Yield Engine

Read this fully before making any change. It captures architecture decisions, hard-won lessons, and current state so nothing from this project's history has to be rediscovered.

## What this is

An open, global news-sentiment × financial-market observatory. Headline question: when a country's news sentiment shifts, do local markets move with it, and at what lead/lag? Explicitly an observatory, not a predictor or investment tool. README.md is the methodology source of truth (exact definitions: polarity thresholds, event detection, HHI, data-quality formula, correlation band, lead/lag convention) — do not restate or diverge from it here; update README.md itself if methodology changes.

## Current state (as of this file's writing)

* Deployed live on Streamlit Community Cloud, `DATA_MODE = "snapshot"`.
* Snapshot: 196–197 countries, ~6 months daily sentiment (GDELT via BigQuery), market data (FRED FX/yields + Twelve Data indices), themes (for the word cloud).
* Panel spans a full spectrum by design: full (sentiment+FX+index), FX-only, index-only, pegged-currency, dollarized, and sentiment-only (~115 of 197) — this heterogeneity is intentional and the UI must render every state gracefully, never as blank/broken.
* UX Pass 3 just landed: word-cloud parsing fixed at the BigQuery source, diagnostics panel now mode-aware, headline section scales via `HEADLINE_CARD_LIMIT`, sidebar is a collapsible region→country tree defaulting to the ~82 countries with real market data, theme toggle (System/Light/Dark) confirmed working live, data-quality formula's snapshot-mode caller fixed to give honest (not fabricated-perfect) scores.

## Architecture (do not casually change)

* Layers stay separate: `ingest/` → `nlp/` → `finance/` → `analysis/` → `visualization/`. The UI (`app/streamlit_app.py`) only calls `pipeline.build_*` — never imports ingest/nlp/finance directly. Preserve this boundary.
* Snapshot-first. The app reads `data/snapshot/*.parquet` (sentiment, market, themes, meta) — it does NOT call GDELT/BigQuery/FRED/Twelve Data live on the user request path. `DATA_MODE` = `demo` | `snapshot` | `live`. Live mode exists in code but is not what's deployed — live GDELT (the plain web API) is unreliable and rate-limits aggressively; don't reintroduce it as the default path.
* Sentiment source: GDELT via Google BigQuery (`gdelt-bq.gdeltv2.gkg_partitioned`), NOT the live GDELT DOC 2.0 API. The web API was abandoned after persistent 429 rate-limiting even from a local/paced IP. BigQuery reads Google's mirror, bypassing that entirely. Every BigQuery query MUST filter `_PARTITIONDATE` (cost/safety) and MUST pass `maximum_bytes_billed` via the shared `_job_config()` helper in `gdelt_bq.py` (currently 160 GB default, tune via `BQ_MAX_BYTES_BILLED` env — this is a backstop, not a budget to approach; a real full-panel tone+themes run costs ~100 GB total, comfortably under it).
* VADER is retired from the production path. GDELT's own tone (`V2Tone`) is THE sentiment signal. Polarity split now thresholds on tone (~±0.5), not VADER ±0.05 — see README for the exact current thresholds.
* Word cloud sources from GDELT `V2Themes`, not article text. Each theme field is `THEME_NAME,charoffset` — always split and take `SAFE_OFFSET(0)` before using the theme name (this was a real bug: unstripped offsets fragmented one theme into many spurious rows AND rendered as literal text in the cloud). Fixed at the BigQuery query level and defensively at read time.
* Market data: FRED (FX + US index/yields) + Twelve Data (national indices). yfinance is fully retired from the live/production path (kept only if a frozen test still references it — check before removing the dependency). Every instrument is pinned to exactly one source in config — never a runtime fallback chain between sources (breaks reproducibility; a stale cached value is preferred over a different-provider value).
* Monetary regime classification (`country_lookup.yaml` / `regions.yaml`): every country is `floating` (own currency, real fetched series), `pegged` (real documented fixed-rate peg — e.g. CFA franc→EUR at 655.957, use the ANCHOR's own FRED series, this is mechanically exact not approximate), `dollarized` (no exchange rate exists — e.g. Ecuador→USD — no FX instrument, index-only or sentiment-only), or `unlinked` (no real series found — sentiment-only). Never assign a reserve-currency stand-in without a real, documented, citable monetary link — under-classifying to `unlinked` is always safer than inventing a peg. The reference list of real pegs/dollarizations lives in `build_country_lookup.py` — extend it only with sourced, verified entries.
* Graceful degradation is load-bearing, not optional. Every visual/section must check what data actually exists (sentiment present? market instrument present? which type?) and render an honest state — never a blank axis, never a crash on missing data. This applies at every layer: per-instrument fetch status, per-country bundle assembly, and every chart/section in the UI.
* Country panel is UN member states (193) + a few justified exceptions (Hong Kong, Macau, Taiwan — major financial centers; Kosovo — real government, no ISO-3 code so it won't render on the choropleth but appears everywhere else). Vatican City was deliberately excluded despite dense GDELT coverage — its volume is overwhelmingly global papal/diplomatic mentions, not Vatican-specific economic signal (a construct-validity call, not a coverage-threshold one).
* Euro-area countries share one EUR/USD series — per-country sentiment-vs-EUR is kept but must be labeled as co-movement with a shared area-wide currency, not a country-specific effect. There's a GDP-weighted `euro_area` aggregate entity as the clean macro pairing.

## Known pitfalls (do not rediscover these)

* Windows `set VAR=value` — never wrap the value in quotes. `set X="C:\path"` stores the literal quote characters as part of the value; Python then looks for a file that literally starts/ends with `"`. This caused hours of `DefaultCredentialsError`/file-not-found confusion earlier in this project. Always `set X=C:\path with spaces` — no quotes, even with spaces in the path.
* Check `TWELVE_DATA_API_KEY` isn't accidentally a Groq key (`gsk_...` prefix) or vice versa — this exact mixup happened once and caused a wall of misleading 401s.
* Don't have the target CSV/parquet open in Excel/WPS/Notepad while a script writes to it — causes `PermissionError: [Errno 13]` on Windows. Close viewers before re-running.
* `git remote add origin` fails with "already exists" if origin is already set — use `git remote set-url origin <url>` to change it, not `add`.
* Git commit identity: local repo config can override global (`git config user.name` with no flag shows the effective value). If commits show the wrong author, check `--local` config isn't shadowing `--global`.
* `gca.json` (the GCP service-account key) must NEVER be committed — it's in `.gitignore` by name and by pattern (`*service-account*.json`, `credentials*.json`). Verified clean via `git log --all --full-history` and a full-history content grep for `BEGIN PRIVATE KEY` — keep it that way. Store the real key outside the repo folder (e.g. `C:\Users\<user>\gcp-key.json`) as a durable habit, not just gitignore.
* BigQuery byte cost is driven by date range scanned, not country count. The `country_code IN (...)` filter applies after the partition scan, so cost is ~flat whether querying 5 countries or 197. If cost ever needs to shrink, shrink the date window — adding countries is free.
* BigQuery needs billing enabled on the project even to stay within the free tier — the 1 TiB/month processing allowance and 10 GB storage allowance both require an active billing account attached, or queries fail outright regardless of usage.
* Streamlit Cloud has no persistent filesystem — `GOOGLE_APPLICATION_CREDENTIALS` as a file path only works locally. If BigQuery is ever needed live from the deployed app (currently it is not — snapshot mode doesn't need it), the credential must be stored as a secret string (`GCP_SA_KEY`) and materialized to a temp file at startup, not read from a path. The GitHub Actions refresh workflow already does exactly this pattern.
* A byte-cap-exceeded error is informative, not just a failure — it means the query needs a higher cap (legitimate — e.g. the themes query genuinely needs ~80GB, more than tone's ~25GB), not necessarily a missing partition filter. Check the actual bytes required (BigQuery reports it) before assuming something is broken.

## Secrets required (Streamlit Cloud secrets panel, snapshot mode)

```
DATA_MODE = "snapshot"
TWELVE_DATA_API_KEY = "..."
GROQ_API_KEY = "..."
GROQ_MODEL = "llama-3.3-70b-versatile"
```

`GCP_SA_KEY` is NOT needed in Streamlit secrets (snapshot mode never calls BigQuery live). It IS needed in GitHub Actions repository secrets, for the scheduled refresh workflow.

## Refreshing the snapshot

```
set GOOGLE_APPLICATION_CREDENTIALS=<path to key, no quotes>
set TWELVE_DATA_API_KEY=<real key>
python scripts/profile_coverage.py --min-days 120 --min-avg 5 --months 6   # if re-profiling the panel
python scripts/backfill.py --months 6                                       # fills data/snapshot/*.parquet
git add data/snapshot config/regions.yaml
git commit -m "..." && git push   # Streamlit Cloud auto-redeploys on push to main
```

A GitHub Actions daily cron does incremental refresh (new days only) automatically — check `.github/workflows/refresh.yml` before assuming a manual refresh is needed.

## Open items / not yet done

* One country (of 197 candidates) didn't resolve into the sentiment table on the last full backfill (196 vs 197) — not yet root-caused, not blocking.
* `EGPT` (Egypt Twelve Data index symbol) 404s — same class of issue as earlier bad symbols (`SP500`, `PGAL`); needs the correct Twelve Data symbol or should fall back to FX-only/sentiment-only for Egypt.
* pandas `FutureWarning` on concat with empty/all-NA frames in `backfill.py` — cosmetic, worth a one-line fix (exclude empty frames before concat) but not urgent.
* pgvector/Supabase persistence layer remains fully deferred/dormant — not needed for current deployment; would only matter for semantic retrieval features, which are explicitly out of scope for the grounded-summary approach already chosen (structured JSON evidence grounding, not RAG — see README's LLM summary section for why).
