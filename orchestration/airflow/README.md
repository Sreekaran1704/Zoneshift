# Airflow orchestration

`dags/zoneshift_monthly.py` keeps the warehouse current as TLC publishes new months.

## Run it

Requires Docker Desktop (about 4 GB RAM for Airflow). From the repo root:

```bash
make airflow-build   # image: apache/airflow:3.3.2-python3.12 + pipeline venv (/opt/zoneshift-venv)
make airflow-up      # writes orchestration/airflow/.env, migrates the DB, starts the services
```

UI at http://localhost:8080 (local-only default login `airflow` / `airflow`). Stop with
`make airflow-down`.

## Design

- **Official docker-compose, trimmed:** LocalExecutor with postgres, api-server, scheduler and
  dag-processor only (no Celery, Redis, or triggerer).
- **Isolated pipeline venv:** dbt, DuckDB and pandas are installed in `/opt/zoneshift-venv`, so
  their pins never conflict with Airflow's own dependencies. Versions match the host
  `requirements.txt` (DuckDB files must be read by the same or a newer DuckDB).
- **Same-path mount:** the repo is mounted at the same absolute path as on the host
  (`ZONESHIFT_HOME`). The DuckDB `raw` views store absolute Parquet paths, so host and container
  share one database without rewriting paths.
- **Data window from the data:** `ingestion/load_duckdb.py` writes `raw.load_metadata`
  (first loaded month to the end of the latest one), and dbt uses it for `dim_date` and the
  outside-window flag. Loading a month extends the warehouse; the pre-registered DiD stays pinned
  to 2024-2025 in `analysis/did.py`.

## DAG `zoneshift_monthly`

Schedule: 06:00 on the 20th of each month, `catchup=False`, `max_active_runs=1`, 2 retries per task.

| Task | What it does |
|---|---|
| `detect_months` | Reads `results/ingestion_log.csv` for the newest month loaded for every type, then probes the TLC CDN for the following months (stops at the first unpublished one, at the current month, or at `max_months`). Skips the run when nothing is new. With `backfill_start`/`backfill_end` params it uses that range instead. |
| `download` | `ingestion/download.py` for the range (retries, size check, skip-if-valid). |
| `validate` | Every requested type x month is in the ingestion log as downloaded/skipped with rows > 0. |
| `load_duckdb` | Re-registers raw views and the data window. |
| `dbt_build` | `dbt build` (models + tests; `fct_trips` appends only new trip_ids). |
| `data_quality_report` | Regenerates `docs/data_quality_report.md` and DQ metrics. |
| `refresh_dashboard_exports` | Re-exports `dashboard/data/`. |

Backfill example (UI: Trigger DAG with config, or CLI):

```bash
cd orchestration/airflow && docker compose exec airflow-scheduler \
  airflow dags trigger zoneshift_monthly --conf '{"backfill_start": "2026-01", "backfill_end": "2026-03"}'
```

## Run history

Evidence (generated from the task logs and the Airflow CLI): [`docs/airflow_run.md`](../../docs/airflow_run.md).

1. The first (scheduled) run downloaded 2026-01..2026-08 but `dbt_build` was killed by the
   kernel (exit -9, out of memory) on all 3 attempts: dbt built the two median-heavy agg marts in
   parallel with DuckDB allowed 8 GB inside Docker's ~8 GB VM.
2. Fix: the dbt profile reads `ZONESHIFT_DUCKDB_MEMORY`, `ZONESHIFT_DUCKDB_THREADS` and
   `ZONESHIFT_DBT_THREADS` from the environment; the compose file sets 4 GB, 4 threads, and one
   dbt model at a time. Host defaults are unchanged.
3. A backfill run (`2026-01`..`2026-08`) then succeeded end to end, and a normal run correctly
   found nothing newer than 2026-08 and skipped.
