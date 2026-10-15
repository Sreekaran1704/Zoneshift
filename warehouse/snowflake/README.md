# Snowflake

Everything here runs without a Snowflake account; a live account is only needed for the optional
trial sprint (Phase 6c).

| File | Purpose |
|---|---|
| `00_guardrails.sql` | X-SMALL warehouse (`AUTO_SUSPEND = 60`, `AUTO_RESUME = TRUE`) and a resource monitor that suspends at 90% of 50 credits. Run first on a real account. |
| `01_raw_ddl.sql` | Raw tables mirroring the DuckDB `raw` schema column for column. |
| `02_stage.sql` | Internal stage. |
| `03_copy.sql` | `COPY INTO` from the stage (`MATCH_BY_COLUMN_NAME` for Parquet, CSV for reference data). |
| `key_queries.sql` | Snowflake-dialect analysis queries (named, run by `load.py --key-queries` and the tests). |
| `load.py` | DDL, `PUT` of `data/warehouse_stage/` files, `COPY INTO`, and row-count checks against the manifest. |

Load files come from `make warehouse-files` (`ingestion/prepare_warehouse_files.py`): every
monthly file rewritten with one unified schema plus `filename` and `file_row_number`, so `trip_id`
is identical in DuckDB, Snowflake and Databricks without stage metadata columns.

## Tested on fakesnow

[fakesnow](https://github.com/tekumara/fakesnow) emulates Snowflake on DuckDB. `make test` runs
`tests/snowflake/`:

- **Loader:** DDL, stage `PUT`, `COPY INTO` and row counts on a deterministic sample
  (2,000 rows per file from 2024-12 and 2025-02, before and after the policy start).
- **Key queries:** every query in `key_queries.sql` runs, and results match the same computation
  done independently in DuckDB on the same files.
- **dbt on Snowflake dialect:** fakesnow's server mode works with `dbt-snowflake`, so the whole
  project runs with `dbt build --target fakesnow` (all models and tests). The clean trip set
  must equal the DuckDB build's for the same trips, trip for trip.

What fakesnow cannot cover, stated plainly:

- **Spatial SQL:** fakesnow has no GEOMETRY functions. On the `fakesnow` target only, `dim_zone`
  reads border flags and centroids from `raw.zone_spatial_fallback` (exported from the DuckDB
  build). The Snowflake spatial path (`TO_GEOMETRY`, `ST_DWITHIN`, `ST_TRANSFORM`) is written but
  only verified on a real account.
- **Stage metadata columns** (`METADATA$FILENAME`, `INCLUDE_METADATA`) are not supported by the
  emulator, which is one reason the load files carry `filename` / `file_row_number` themselves.
- Performance, warehouse sizing and credit use.
