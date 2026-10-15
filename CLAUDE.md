# ZoneShift: Build Instructions for Claude Code

You are building **ZoneShift**, a portfolio analytics engineering + causal inference project for Sreekaran Reddy Ramasahayam. Read this whole file before writing any code. Follow the phases in order and stop at every phase gate.

> **Override (from the user, 2026-10-14):** Claude writes and updates code only. The user does ALL git operations (init, add, commit, push). Never run git commands. Wherever this file says "commit", instead stop and suggest a commit message for the user.
>
> **Environment notes:** project root is this folder (`/Users/sreekaran1704/Documents/Zoneshift`). Python 3.12 venv at `.venv` (created with `uv`, since only 3.13 was installed system-wide). Install packages with `uv pip install --python .venv/bin/python ...`.

## 1. The project in one paragraph

On January 5, 2025, New York City began congestion pricing for vehicles entering Manhattan's Central Business District (CBD, south of 60th Street). Taxi trips there pay a per-trip fee (shown in the TLC trip records as `cbd_congestion_fee` from 2025 onward). ZoneShift ingests real NYC TLC trip records, models them with dbt, tests data quality, and estimates how trip volume, fares, speed, and tipping changed in CBD zones relative to comparable non-CBD zones using difference-in-differences. It then adds a dashboard, Airflow orchestration, a Snowflake deployment, and a LangGraph text-to-SQL agent with a measured accuracy score.

## 2. Non-negotiable rules

### 2.1 Zero cost
- Use only free, open-source tools or free tiers: Python, DuckDB, dbt Core (dbt-duckdb, later dbt-snowflake), Airflow, statsmodels/linearmodels, Groq free tier, Snowflake 30-day free trial.
- **Never** sign up for anything, enter payment details, or enable a paid feature. When a step needs an account (Snowflake trial, Groq API key), STOP and ask the user to do it, then continue once they paste the credentials into `.env`.
- Never commit secrets. `.env` goes in `.gitignore`; provide `.env.example`.
- Before downloading data, check free disk space (`df -h ~`) and tell the user the estimated download size. Core scope is roughly 2 to 3 GB of Parquet.

### 2.2 Honesty (this goes on a resume)
- Every number in the README, dashboard, or summaries must come from an actual run. Write all key metrics to `results/metrics.json` from code, and have the README quote that file. Never type a metric by hand.
- If a result is null or statistically insignificant, report it as such. Do not tune the specification until something becomes significant. Pre-register the main specification in `analysis/PREREGISTRATION.md` BEFORE running the main model.
- Keep language neutral. Congestion pricing is politically contested: describe measured effects and caveats only, no opinions about the policy.
- The trip data is vendor-submitted and not verified by TLC. State this in the README.

### 2.3 Engineering
- Machine: Apple Silicon Mac (arm64). Python 3.12 virtual environment. Pin versions in `requirements.txt`.
- (Git is handled by the user; see override above.)
- Write idempotent scripts (safe to re-run; skip files already downloaded and validated).
- Keep raw data out of git (`data/` in `.gitignore`).

### 2.4 Phase gates
At the end of each phase: run all checks, suggest a commit message, then STOP and print a short summary for the user (what was built, the key numbers from `results/metrics.json`, anything that failed or needs their decision). Wait for "continue" before the next phase.

## 3. Data sources

| Data | URL pattern |
|---|---|
| Yellow taxi trips | `https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_YYYY-MM.parquet` |
| Green taxi trips | `https://d37ci6vzurychx.cloudfront.net/trip-data/green_tripdata_YYYY-MM.parquet` |
| High-volume FHV (Uber/Lyft), optional | `https://d37ci6vzurychx.cloudfront.net/trip-data/fhvhv_tripdata_YYYY-MM.parquet` |
| Taxi zone lookup | `https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv` |
| Taxi zone shapefile (for maps) | `https://d37ci6vzurychx.cloudfront.net/misc/taxi_zones.zip` |
| MTA CBD taxi zones (treatment definition) | `https://data.ny.gov/api/views/yfdc-w5jh/rows.csv?accessType=DOWNLOAD` |

Data dictionaries: https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page. Verify the URLs respond before bulk downloading; if any have moved, find the current link on that page and tell the user.

**Core scope:** yellow + green, January 2024 through December 2025 (12 months pre, 12 months post). FHVHV is optional and large (hundreds of MB per month); only add it in an optional phase, and use a deterministic sample if it is added.

**Known schema traps:** column names vary in case across months (e.g. `Airport_fee` vs `airport_fee`), types drift (e.g. `passenger_count` int vs double), and `cbd_congestion_fee` exists only from 2025. Read with DuckDB `read_parquet(..., union_by_name=true)`, lowercase all column names, and cast explicitly in staging.

The MTA CBD file has columns `Taxi Zone` (LocationID) and `Polygon` (WKT); 38 zones as of 2026-10-14.

## 4. Target repo structure

```
zoneshift/
  CLAUDE.md
  README.md
  requirements.txt
  .env.example
  .gitignore
  Makefile                      # make ingest / make dbt / make analysis / make all
  ingestion/
    download.py                 # month-range downloader with retries + checksum/size validation
    load_duckdb.py              # registers raw Parquet into DuckDB raw schema
  data/                         # gitignored: raw/, zoneshift.duckdb
  dbt/zoneshift/
    dbt_project.yml
    profiles.yml.example        # duckdb target (dev) + snowflake target (prod)
    models/
      staging/                  # stg_yellow_trips, stg_green_trips, stg_taxi_zones, stg_cbd_zones
      intermediate/             # int_trips_unioned, int_trips_cleaned (with exclusion flags)
      marts/                    # dim_zone, dim_date, fct_trips (incremental), agg_zone_day, agg_zone_hour
    tests/                      # singular tests
    macros/
  analysis/
    PREREGISTRATION.md
    did.py                      # main DiD + event study + robustness
    figures/
  results/
    metrics.json
    did_results.csv
  dashboard/                    # exports for BI tool
  orchestration/airflow/        # DAG + docker-compose or standalone notes
  agent/                        # LangGraph text-to-SQL agent
    eval/gold_questions.yaml
    eval/run_eval.py
  docs/
    data_quality_report.md
    architecture.md
```

## 5. Phases

### Phase 0: Setup (small)
1. Create the structure above, venv, `requirements.txt` (duckdb, dbt-duckdb, pandas, pyarrow, requests, statsmodels, linearmodels, matplotlib, pyyaml, python-dotenv).
2. Verify the data URLs return HTTP 200. Check disk space. Report both.
3. **GATE.**

### Phase 1: Ingestion
1. `download.py --start 2024-01 --end 2025-12 --types yellow,green` with retries, skip-if-exists, and validation (file opens in DuckDB, row count > 0). Log row counts per file to `results/ingestion_log.csv`.
2. Download zone lookup, CBD zone list, and shapefile.
3. `load_duckdb.py` creates `data/zoneshift.duckdb` with a `raw` schema (views over Parquet are fine to save disk).
4. Record total raw rows per type in `results/metrics.json`. **GATE.**

### Phase 2: dbt models + data quality
1. dbt-duckdb profile. Sources with descriptions.
2. Staging: lowercase, cast, rename to consistent names across yellow/green, add `service_type`.
3. Intermediate: union, compute `trip_minutes`, `avg_mph`, `tip_pct` (card payments only, since cash tips are not recorded), and exclusion flags: non-positive distance, negative fare, dropoff before pickup, trip over 3 hours, speed over 80 mph, pickup outside the analysis window, unknown zones (264/265).
4. Treatment flag: `pickup_in_cbd` and `dropoff_in_cbd` joined from the MTA CBD zone list. Do not hand-code zone IDs.
5. Marts: `dim_zone` (borough, zone, is_cbd, is_border_zone = non-CBD Manhattan zones adjacent to 60th St, derived from the shapefile adjacency, not guessed), `dim_date` (holidays, weekday, post_policy flag with cutoff 2025-01-05), `fct_trips` (incremental), `agg_zone_day`, `agg_zone_hour`.
6. Tests: generic (not_null, unique, relationships, accepted_values) plus singular tests (no negative fares in clean set, `cbd_congestion_fee` null or zero before 2025-01-05, sensible fee values after). Add a source freshness check.
7. `dbt build` must pass. Write `docs/data_quality_report.md` from code: rows in, rows excluded by each flag, % retained. Save the test count and pass count to metrics.json. **GATE.**

### Phase 3: Causal analysis
1. BEFORE modeling, write `analysis/PREREGISTRATION.md`: unit = pickup zone x day; treated = CBD zones; control = non-CBD zones, with border zones excluded from the main spec (spillover risk); outcomes = trip count (log), median fare excluding the CBD fee, average speed, card tip %; model = two-way fixed effects (zone FE + date FE), SEs clustered by zone; window = 2024-01 to 2025-12.
2. Diagnostics: plot treated vs control trends; event study by week relative to 2025-01-05 with pre-period leads (test that the leads are jointly zero).
3. Main DiD for each outcome. Save coefficients, CIs, p-values, N to `results/did_results.csv` and the headline numbers to metrics.json.
4. Robustness: placebo cutoff (2024-07-01 using only 2024 data); include border zones; yellow only; drop holiday weeks. Report all of them, including any that disagree.
5. Figures to `analysis/figures/` (event study plots, trend plots).
6. A plain-English summary in the README, with limitations: spillover, other concurrent changes, vendor-reported data, FHV not in the core scope. **GATE.**

### Phase 4: Dashboard
STOP and ask the user which tool: (a) Power BI via a UMKC Microsoft account or a Windows machine, (b) Tableau Public (free, works on Mac), or (c) a Streamlit app (free hosting on Streamlit Community Cloud). Then export the needed marts (`agg_zone_day`, `agg_zone_hour`, `dim_zone`, `dim_date`, `did_results`) to `dashboard/` as CSV/Parquet, and write `dashboard/BUILD_GUIDE.md` with the star-schema relationships, the measures to create (with DAX formulas if Power BI), and suggested pages: Overview KPIs, CBD vs non-CBD trends, zone map, hour-of-day patterns, causal results. If Streamlit is chosen, build the app. **GATE.**

### Phase 5: Airflow orchestration
1. Ask the user whether Docker Desktop is installed. If yes, use the official docker-compose setup with minimal services (LocalExecutor). If not, use `airflow standalone` in a separate venv. Check the current Airflow docs for the supported Python version and install method before installing.
2. DAG `zoneshift_monthly`: monthly schedule, detect the newest published month not yet loaded, download, validate, `dbt build`, refresh the exports. Use retries, catchup=False, and a backfill param.
3. Run it once successfully for the latest available month; save a screenshot path or a log excerpt to `docs/`. **GATE.**

### Phase 6: Cloud warehouses (Snowflake-ready without depending on the 30-day trial)
The Snowflake trial is time-limited, so the project must NOT depend on a live Snowflake account. Do NOT suggest creating repeat trial accounts with new emails. Use this three-part approach:

**6a. Snowflake-dialect development, free forever (no account).**
1. Write all Snowflake-specific SQL (DDL, stage + `COPY INTO` loader, any dialect-specific macros) in `warehouse/snowflake/` and keep dbt models cross-database (use `dbt.` cross-db macros, `adapter.dispatch` where dialects differ).
2. Install `fakesnow` (open-source Snowflake emulator backed by DuckDB). Write pytest tests in `tests/snowflake/` that run the Snowflake loader and key queries against fakesnow. Check the fakesnow docs for its current features; if its server mode works with dbt-snowflake, add a `fakesnow` dbt target, otherwise use it for loader/query tests only and say so in the README.
3. Add a CI workflow (`.github/workflows/ci.yml`, GitHub Actions free tier for public repos) running `dbt build` on DuckDB plus the fakesnow tests.

**6b. Always-free cloud target.**
1. Ask the user to sign up for Databricks Free Edition (free, no time limit, non-commercial use, serverless 2X-Small SQL warehouse). Add a `databricks` target via `dbt-databricks`. Load the marts plus a deterministic sample of `fct_trips` to stay within daily quotas.
2. Run `dbt build --target databricks`. This is the live cloud deployment that stays up after any trial ends.

**6c. Snowflake sprint (optional, 1 to 2 days, only when the user says go).**
1. The user creates the 30-day trial (no credit card) and puts the credentials in `.env`. Immediately create guardrails: an X-SMALL warehouse with `AUTO_SUSPEND = 60`, `AUTO_RESUME = TRUE`, and a resource monitor that suspends at 90% of a 50-credit quota.
2. Because 6a already tested everything, this is a single run: load via the stage + `COPY INTO`, `dbt build --target snowflake`, run the key analysis queries.
3. Capture permanent evidence in `docs/snowflake/`: query history export, credits used, row counts per table, dbt run log, and a list of screenshots for the user to take (Snowsight query profile, warehouse settings). Record the numbers in metrics.json. After the trial ends, the code, tests, and evidence remain in the repo.
**GATE.**

### Phase 7: LangGraph text-to-SQL agent
1. Ask the user for a Groq API key (free tier). Check Groq's current model list and pick a capable free model.
2. Graph: load schema + column descriptions from dbt docs -> generate SQL -> guard (read-only SELECT only, auto LIMIT, allowlisted tables) -> execute on DuckDB -> on error, repair (max 2 retries) -> answer with the SQL shown.
3. Write `agent/eval/gold_questions.yaml` with 40 to 50 questions with gold SQL, spanning easy/medium/hard. Have the user review these before scoring.
4. `run_eval.py` computes execution accuracy (result sets match), by difficulty, with rate-limit backoff. Save to metrics.json. Report the true score, whatever it is.
5. A simple CLI or Streamlit chat page. **GATE.**

### Phase 8: Polish
README with: the question, architecture diagram (Mermaid), how to run (`make all`), key results quoted from metrics.json, figures, limitations, tech stack. `docs/architecture.md`. Make sure a fresh clone + `make all` works. **GATE.**

## 6. Usage-limit discipline
The user has a limited Claude usage budget. Be efficient: avoid printing large dataframes or full logs, inspect data with targeted queries (`LIMIT`, aggregates), and do not re-run long downloads. If you are near the end of a phase and the session may run out, write `NEXT_STEPS.md` describing exactly where to resume.
