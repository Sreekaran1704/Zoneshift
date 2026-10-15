# Databricks (Free Edition)

The always-free cloud deployment: a serverless SQL warehouse in Unity Catalog `workspace`.

```bash
make databricks   # needs DATABRICKS_HOST, DATABRICKS_HTTP_PATH, DATABRICKS_TOKEN in .env
```

| Step | Script | What it does |
|---|---|---|
| Sample | `ingestion/prepare_warehouse_files.py --sample-mod 100` | Deterministic 1% of trips: rows with `file_row_number % 100 = 0` in every monthly file, so every day is covered and the sample is reproducible. Keeps the load inside Free Edition quotas. |
| Load | `load.py` | Uploads files to the volume `/Volumes/workspace/raw/landing/`, creates `workspace.raw.*` with `read_files`, checks row counts, and loads the full-data marts (built locally from every trip) as `workspace.zoneshift_full.*`. |
| Build | `run_dbt.py build` | `dbt build --target databricks` with credentials from `.env` (host normalized, so a pasted browser URL works). Log: `docs/databricks/dbt_build.log`. |
| Verify | `verify.py` | Compares the cloud build with the local DuckDB build on the same sampled trips and writes `docs/databricks/verification.md`. |

Databricks-specific SQL lives in the `databricks__` macros in `dbt/zoneshift/macros/cross_db.sql`
(regex, ISO weekday, date spine, spatial). Spatial SQL (`ST_GEOMFROMWKT`, `ST_DWITHIN`,
`ST_TRANSFORM`) runs natively, so border zones are derived in the cloud, not copied.
