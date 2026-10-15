"""Load ZoneShift data into Databricks (Unity Catalog, Free Edition).

1. Uploads prepared raw files (a deterministic sample, see --sample-mod in
   ingestion/prepare_warehouse_files.py) to the volume /Volumes/workspace/raw/landing/ and creates
   workspace.raw.* tables, so `dbt build --target databricks` runs the whole project in the cloud.
2. Uploads the full-data marts exported for the dashboard (dashboard/data/*.parquet, built locally
   from all trips) as workspace.zoneshift_full.* tables.

Usage:
    python warehouse/databricks/load.py [--stage-dir data/warehouse_stage_databricks]
"""
import argparse
import json
from pathlib import Path

from conn import ROOT, connect, settings

CATALOG = "workspace"
VOLUME = f"/Volumes/{CATALOG}/raw/landing"
FULL_MARTS = ["agg_zone_day", "agg_zone_hour", "dim_zone", "dim_date", "did_results", "event_study"]


def upload(files_api, local: Path, remote: str) -> None:
    with open(local, "rb") as f:
        files_api.upload(remote, f, overwrite=True)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stage-dir", type=Path, default=ROOT / "data" / "warehouse_stage_databricks")
    args = p.parse_args()
    from databricks.sdk import WorkspaceClient

    s = settings()
    w = WorkspaceClient(host=f"https://{s['host']}", token=s["token"])
    cur = connect().cursor()
    run = lambda sql: cur.execute(sql)  # noqa: E731

    run(f"create schema if not exists {CATALOG}.raw")
    run(f"create volume if not exists {CATALOG}.raw.landing")
    run(f"create schema if not exists {CATALOG}.zoneshift_full")

    # 1. Raw sample
    manifest = json.loads((args.stage_dir / "manifest.json").read_text())
    for t in ["yellow", "green"]:
        for f in sorted((args.stage_dir / t).glob("*.parquet")):
            upload(w.files, f, f"{VOLUME}/{t}/{f.name}")
        run(f"""create or replace table {CATALOG}.raw.{t}_tripdata as
                select * except (_rescued_data)
                from read_files('{VOLUME}/{t}/', format => 'parquet', rescuedDataColumn => '_rescued_data')""")
    for f in sorted((args.stage_dir / "reference").glob("*.csv")):
        upload(w.files, f, f"{VOLUME}/reference/{f.name}")
    csv = lambda name, schema: (  # noqa: E731
        f"read_files('{VOLUME}/reference/{name}.csv', format => 'csv', header => true, schema => '{schema}')")
    run(f"""create or replace table {CATALOG}.raw.taxi_zone_lookup as
            select * from {csv('taxi_zone_lookup', 'LocationID INT, Borough STRING, Zone STRING, service_zone STRING')}""")
    # Column names with spaces need Delta column mapping
    run(f"""create or replace table {CATALOG}.raw.cbd_taxi_zones (`Taxi Zone` INT, `Polygon` STRING)
            tblproperties ('delta.columnMapping.mode' = 'name')""")
    run(f"""insert into {CATALOG}.raw.cbd_taxi_zones
            select * from {csv('cbd_taxi_zones', 'taxi_zone INT, polygon STRING')}""")
    run(f"""create or replace table {CATALOG}.raw.taxi_zone_shapes as
            select * from {csv('taxi_zone_shapes', 'LocationID INT, zone STRING, borough STRING, geom STRING')}""")
    run(f"""create or replace table {CATALOG}.raw.load_metadata as
            select * from {csv('load_metadata', 'window_start DATE, window_end DATE, loaded_at TIMESTAMP')}""")

    counts, expected = {}, {}
    for t in ["yellow", "green"]:
        cur.execute(f"select count(*) from {CATALOG}.raw.{t}_tripdata")
        counts[f"raw.{t}_tripdata"] = cur.fetchone()[0]
        expected[f"raw.{t}_tripdata"] = sum(manifest["trips"].get(t, {}).values())
    for name in ["taxi_zone_lookup", "cbd_taxi_zones", "taxi_zone_shapes", "load_metadata"]:
        cur.execute(f"select count(*) from {CATALOG}.raw.{name}")
        counts[f"raw.{name}"] = cur.fetchone()[0]
        expected[f"raw.{name}"] = manifest["reference"][name]
    bad = {k: (counts[k], expected[k]) for k in counts if counts[k] != expected[k]}
    if bad:
        raise SystemExit(f"Row count mismatch (loaded, expected): {bad}")

    # 2. Full-data marts (built locally from every trip)
    for name in FULL_MARTS:
        local = ROOT / "dashboard" / "data" / f"{name}.parquet"
        upload(w.files, local, f"{VOLUME}/full_marts/{name}.parquet")
        run(f"""create or replace table {CATALOG}.zoneshift_full.{name} as
                select * except (_rescued_data)
                from read_files('{VOLUME}/full_marts/{name}.parquet', format => 'parquet',
                                rescuedDataColumn => '_rescued_data')""")
        cur.execute(f"select count(*) from {CATALOG}.zoneshift_full.{name}")
        counts[f"zoneshift_full.{name}"] = cur.fetchone()[0]

    out = ROOT / "docs" / "databricks" / "load_counts.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"sample_mod": manifest.get("sample_mod"), "tables": counts}, indent=2))
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
