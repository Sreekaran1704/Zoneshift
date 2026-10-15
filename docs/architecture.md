# Architecture

## Data flow

1. **Download** (`ingestion/download.py`): monthly TLC Parquet files per service type, streamed to
   a `.part` file, kept only when the byte size matches `Content-Length`, then validated by opening
   in DuckDB (row count > 0). Re-runs skip valid files. Per-file rows go to
   `results/ingestion_log.csv`. Reference files: zone lookup, zone shapefile (safe unzip), MTA CBD
   zone list.
2. **Raw layer** (`ingestion/load_duckdb.py`, `data/zoneshift.duckdb`, schema `raw`): trip data
   stays in Parquet behind views (`read_parquet(..., union_by_name, filename, file_row_number)`),
   which absorb column-case and type drift across months. Small reference files become tables.
   `raw.load_metadata` records the data window (first loaded month to the end of the latest), the
   single source of truth for dbt's date window.
3. **dbt** (`dbt/zoneshift/`):
   - *staging*: lowercase names, explicit casts, `service_type`, deterministic `trip_id`
     (`service code * 1e14 + file yyyymm * 1e8 + row number in file`).
   - *intermediate*: yellow + green union; `trip_minutes`, `avg_mph`, card `tip_pct`; CBD flags
     joined from the MTA list; seven exclusion flags; `is_excluded`.
   - *marts*: `dim_zone` (CBD, border zones by polygon adjacency, WGS84 centroids), `dim_date`
     (holidays, post-policy flag, event-study week), `fct_trips` (clean trips, incremental by
     `trip_id`), `agg_zone_day` and `agg_zone_hour` (with `service_type = 'all'` rows so medians
     are computed on combined trips).
   - *tests*: generic (unique, not_null, relationships, accepted_values, composite keys, ranges)
     and singular (no negative fares in the clean set, CBD fee before/after the policy, fee anomaly
     rate gate, CBD list coverage, border zone validity, clean-set row count invariant); source
     freshness on the raw trip views.
4. **Outputs**: `scripts/data_quality_report.py` (DQ report + test counts), `analysis/did.py`
   (pre-registered DiD), `dashboard/export.py` (Parquet for the dashboard), all writing metrics to
   `results/metrics.json`; `analysis/render_readme.py` renders the README's numbers from it.

## Cross-database design

Models use SQL both engines accept plus `adapter.dispatch` macros
(`macros/cross_db.sql`) for the few dialect differences: regex extraction, ISO weekday, weekday
name, date spine, geometry construction and centroid transform. Targets:

| Target | Where | Data | Status |
|---|---|---|---|
| `dev` | DuckDB on the laptop | all loaded months | primary build |
| `fakesnow` | Snowflake emulator (tests/CI) | 2,000-row samples of two months | full `dbt build`; spatial via precomputed fallback |
| `databricks` | Databricks Free Edition, serverless SQL warehouse | deterministic 1% sample | full `dbt build`; results verified identical to DuckDB |
| `prod` (Snowflake) | 30-day trial, optional | prepared files via stage + `COPY INTO` | code and guardrails ready, not yet run |

`ingestion/prepare_warehouse_files.py` rewrites each month with one unified schema plus `filename`
and `file_row_number`, so every warehouse computes the same `trip_id` and loads by column name.

## Orchestration

Airflow 3.3.2 (Docker, LocalExecutor) runs `zoneshift_monthly`: detect newly published months
(or a backfill range), download, validate, load, `dbt build`, DQ report, dashboard exports.
Pipeline dependencies live in an isolated venv inside the image; the repo is mounted at the same
absolute path as on the host so the DuckDB raw views resolve in both. See
[`orchestration/airflow/README.md`](../orchestration/airflow/README.md).

## Analysis guardrails

- The DiD specification was committed before any model run; its hash is stored with the results.
- `analysis/did.py` pins its own 2024-2025 window and holiday weeks, so a growing warehouse cannot
  change the pre-registered sample; the panel is sorted before fitting so reruns are identical.
- Late-reported trips: a monthly file can contain a few trips picked up in earlier months (e.g. a
  2025-12-31 pickup in the 2026-01 file). The window is defined on pickup date, so a warehouse that
  has loaded 2026 files includes those trips and one built only from 2024-2025 files does not.
  A fresh-clone `make all` (2024-2025 files only) reproduced the committed DiD with identical
  samples and coefficients within 4e-5 (one exploratory estimate differs in the 3rd decimal).

## Agent

LangGraph graph: load schema (dbt descriptions + DuckDB types) -> generate SQL (Groq) -> guard
(sqlglot: single read-only SELECT on five allowlisted marts, no table functions, enforced LIMIT)
-> execute (read-only DuckDB, external access disabled, timeout) -> repair on error (max 2) ->
answer with the SQL shown. Evaluated by execution accuracy on owner-reviewed gold questions.

## CI

`.github/workflows/ci.yml`: install pinned dependencies, download three real months
(2024-12..2025-02), build the raw schema, `dbt build` on DuckDB, then the fakesnow tests (loader,
key queries, and the full dbt project on the Snowflake dialect).
