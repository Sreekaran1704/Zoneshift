"""Write warehouse-neutral load files from the DuckDB raw schema (for Snowflake / Databricks).

Each monthly trip file is re-written from the raw.<type>_tripdata view, so every file has the same
unified schema (union_by_name), plus `filename` (basename) and `file_row_number`. Cloud loaders can
then COPY by column name without needing stage metadata columns, and trip_id is identical in every
warehouse. Reference data is written as CSV (zone shapes as WKT in NY State Plane, EPSG:2263).

Usage:
    python ingestion/prepare_warehouse_files.py [--out DIR] [--types yellow,green]
        [--months 2024-01,2025-01] [--sample-per-file N | --sample-mod N]
"""
import argparse
import json
import shutil
from pathlib import Path

import duckdb

from utils import DB_PATH, RAW_DIR, REF_DIR, ROOT

DEFAULT_OUT = ROOT / "data" / "warehouse_stage"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--types", default="yellow,green")
    p.add_argument("--months", default=None, help="comma-separated YYYY-MM filter (default: all loaded)")
    p.add_argument("--sample-per-file", type=int, default=None,
                   help="keep only rows with file_row_number < N (deterministic sample)")
    p.add_argument("--sample-mod", type=int, default=None,
                   help="keep rows with file_row_number %% N = 0 (deterministic 1/N sample spread over every day)")
    p.add_argument("--db", type=Path, default=DB_PATH)
    p.add_argument("--spatial-fallback", action="store_true",
                   help="also export zone_spatial_fallback.csv from marts.dim_zone (fakesnow tests only)")
    args = p.parse_args()

    con = duckdb.connect(str(args.db), read_only=True)
    con.execute("load spatial")
    if args.out.exists():
        shutil.rmtree(args.out)
    manifest = {"trips": {}, "reference": {}, "sample_per_file": args.sample_per_file,
                "sample_mod": args.sample_mod}
    months = set(args.months.split(",")) if args.months else None

    for t in args.types.split(","):
        files = sorted((RAW_DIR / t).glob(f"{t}_tripdata_*.parquet"))
        if months:
            files = [f for f in files if f.stem.rsplit("_", 1)[1] in months]
        out_dir = args.out / t
        out_dir.mkdir(parents=True, exist_ok=True)
        for f in files:
            where = f"filename = '{f}'"
            if args.sample_per_file:
                where += f" and file_row_number < {args.sample_per_file}"
            if args.sample_mod:
                where += f" and file_row_number % {args.sample_mod} = 0"
            dest = out_dir / f.name
            con.execute(f"""
                copy (
                    select * replace (regexp_extract(filename, '[^/]+$') as filename)
                    from raw.{t}_tripdata where {where}
                ) to '{dest}' (format parquet, compression zstd)
            """)
            n = con.execute(f"select count(*) from read_parquet('{dest}')").fetchone()[0]
            manifest["trips"].setdefault(t, {})[f.name] = n
        print(f"{t}: {len(files)} files, {sum(manifest['trips'].get(t, {}).values()):,} rows")

    ref = args.out / "reference"
    ref.mkdir(parents=True, exist_ok=True)
    shutil.copy(REF_DIR / "taxi_zone_lookup.csv", ref / "taxi_zone_lookup.csv")
    shutil.copy(REF_DIR / "cbd_taxi_zones.csv", ref / "cbd_taxi_zones.csv")
    con.execute(f"""
        copy (select LocationID, zone, borough, st_astext(geom) as geom
              from raw.taxi_zone_shapes order by LocationID)
        to '{ref / "taxi_zone_shapes.csv"}' (header, delimiter ',')
    """)
    if args.spatial_fallback:
        con.execute(f"""
            copy (select location_id, is_border_zone, centroid_lon, centroid_lat
                  from marts.dim_zone order by location_id)
            to '{ref / "zone_spatial_fallback.csv"}' (header, delimiter ',')
        """)
    if months:  # window of the exported subset, so a sampled warehouse is self-consistent
        lo, hi = min(months), max(months)
        con.execute(f"""
            copy (select date '{lo}-01' as window_start,
                         cast(date '{hi}-01' + interval 1 month as date) as window_end,
                         current_timestamp::timestamp as loaded_at)
            to '{ref / "load_metadata.csv"}' (header, delimiter ',')
        """)
    else:
        con.execute(f"""
            copy (select window_start, cast(window_end as date) as window_end, loaded_at::timestamp as loaded_at
                  from raw.load_metadata)
            to '{ref / "load_metadata.csv"}' (header, delimiter ',')
        """)
    for csv_file in sorted(ref.glob("*.csv")):
        manifest["reference"][csv_file.stem] = con.execute(
            f"select count(*) from read_csv('{csv_file}', header = true)").fetchone()[0]

    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Wrote {args.out} (manifest.json with row counts)")


if __name__ == "__main__":
    main()
