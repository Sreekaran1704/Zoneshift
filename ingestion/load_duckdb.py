"""Register raw files into data/zoneshift.duckdb under the `raw` schema.

Trip data stays in Parquet: raw.<type>_tripdata are views over data/raw/<type>/*.parquet
(union_by_name handles column-case and type drift across months; staging lowercases
and casts). Views store absolute paths, so re-run this script after moving the repo.
Small reference files are copied into tables.

Usage:
    python ingestion/load_duckdb.py
"""
import csv

import duckdb

from utils import DB_PATH, RAW_DIR, REF_DIR, RESULTS_DIR, ROOT, update_metrics

TRIP_TYPES = ["yellow", "green", "fhvhv"]


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    con.execute("create schema if not exists raw")

    metrics = {}
    months = []
    for t in TRIP_TYPES:
        files = sorted((RAW_DIR / t).glob(f"{t}_tripdata_*.parquet"))
        if not files:
            continue
        months += [f.stem.rsplit("_", 1)[1] for f in files]
        con.execute(f"""
            create or replace view raw.{t}_tripdata as
            select * from read_parquet('{RAW_DIR / t}/{t}_tripdata_*.parquet',
                                       union_by_name = true, filename = true,
                                       file_row_number = true)
        """)
        rows = con.execute(f"select count(*) from raw.{t}_tripdata").fetchone()[0]
        metrics[f"raw_rows_{t}"] = rows
        metrics[f"raw_files_{t}"] = len(files)
        print(f"raw.{t}_tripdata: {len(files)} files, {rows:,} rows")

    # Data window = first day of the earliest loaded month to first day after the latest one.
    # dbt reads this (single source of truth), so loading a new month extends the warehouse window.
    con.execute(f"""
        create or replace table raw.load_metadata as
        select date '{min(months)}-01'                           as window_start,
               date '{max(months)}-01' + interval 1 month         as window_end,
               current_timestamp                                  as loaded_at
    """)
    window = con.execute("select window_start, cast(window_end as date) from raw.load_metadata").fetchone()
    metrics["data_window"] = {"start": str(window[0]), "end_exclusive": str(window[1])}
    print(f"raw.load_metadata: window {window[0]} to {window[1]} (exclusive)")

    con.execute(f"""
        create or replace table raw.taxi_zone_lookup as
        select * from read_csv('{REF_DIR / "taxi_zone_lookup.csv"}', header = true)
    """)
    con.execute(f"""
        create or replace table raw.cbd_taxi_zones as
        select * from read_csv('{REF_DIR / "cbd_taxi_zones.csv"}', header = true)
    """)

    # Shapefile (NY State Plane, US feet) for maps and border-zone adjacency in dbt
    con.execute("install spatial; load spatial;")
    shp = next(REF_DIR.glob("taxi_zones/**/taxi_zones.shp"))
    con.execute(f"create or replace table raw.taxi_zone_shapes as select * from st_read('{shp}')")

    for table in ["taxi_zone_lookup", "cbd_taxi_zones", "taxi_zone_shapes"]:
        n = con.execute(f"select count(*) from raw.{table}").fetchone()[0]
        metrics[f"raw_rows_{table}"] = n
        print(f"raw.{table}: {n:,} rows")

    # Cross-check view counts against the per-file counts logged by download.py
    log_path = RESULTS_DIR / "ingestion_log.csv"
    if log_path.exists():
        with open(log_path) as f:
            logged = {}
            for r in csv.DictReader(f):
                if (ROOT / r["file"]).exists():  # the log may list months not present locally
                    logged[r["service_type"]] = logged.get(r["service_type"], 0) + int(r["rows"])
        for t, n in logged.items():
            if metrics.get(f"raw_rows_{t}") != n:
                raise SystemExit(f"Row count mismatch for {t}: view={metrics.get(f'raw_rows_{t}')} log={n}")

    trip_rows = [v for k, v in metrics.items() if k.startswith("raw_rows_") and k.endswith(tuple(TRIP_TYPES))]
    metrics["raw_rows_trips_total"] = sum(trip_rows)
    update_metrics(metrics)
    con.close()
    print(f"Wrote {DB_PATH.relative_to(DB_PATH.parents[1])} and updated results/metrics.json")


if __name__ == "__main__":
    main()
