"""Load prepared files into Snowflake: raw DDL -> internal stage (PUT) -> COPY INTO -> row checks.

Input is the output of ingestion/prepare_warehouse_files.py (default data/warehouse_stage/).
Connection settings come from .env (SNOWFLAKE_*); tests pass a fakesnow connection instead.

Usage:
    python warehouse/snowflake/load.py [--stage-dir data/warehouse_stage] [--key-queries]
"""
import argparse
import json
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TRIP_TABLES = {"yellow": "raw.yellow_tripdata", "green": "raw.green_tripdata"}
REF_TABLES = {"taxi_zone_lookup": "raw.taxi_zone_lookup", "cbd_taxi_zones": "raw.cbd_taxi_zones",
              "taxi_zone_shapes": "raw.taxi_zone_shapes", "load_metadata": "raw.load_metadata"}


def sql_statements(path: Path) -> list[str]:
    """Split a .sql file on ';', dropping comment-only lines."""
    text = "\n".join(ln for ln in path.read_text().splitlines() if not ln.strip().startswith("--"))
    return [s.strip() for s in text.split(";") if s.strip()]


def key_queries() -> dict[str, str]:
    """Named queries from key_queries.sql ('-- name: x' headers)."""
    out, name, buf = {}, None, []
    for line in (HERE / "key_queries.sql").read_text().splitlines():
        m = re.match(r"--\s*name:\s*(\w+)", line)
        if m:
            if name:
                out[name] = "\n".join(buf).strip().rstrip(";")
            name, buf = m.group(1), []
        elif not line.strip().startswith("--"):
            buf.append(line)
    if name:
        out[name] = "\n".join(buf).strip().rstrip(";")
    return out


def load(conn, stage_dir: Path) -> dict:
    """Create raw tables, stage and COPY the prepared files; verify counts against manifest.json."""
    manifest = json.loads((stage_dir / "manifest.json").read_text())
    cur = conn.cursor()
    for f in ["01_raw_ddl.sql", "02_stage.sql"]:
        for stmt in sql_statements(HERE / f):
            cur.execute(stmt)

    for t in TRIP_TABLES:
        for f in sorted((stage_dir / t).glob("*.parquet")):
            cur.execute(f"put file://{f} @raw.zoneshift_stage/{t}/ auto_compress = false overwrite = true")
    for f in sorted((stage_dir / "reference").glob("*.csv")):
        cur.execute(f"put file://{f} @raw.zoneshift_stage/reference/ auto_compress = false overwrite = true")

    for stmt in sql_statements(HERE / "03_copy.sql"):
        cur.execute(stmt)

    if "zone_spatial_fallback" in manifest["reference"]:  # emulator-only, see dim_zone.sql
        cur.execute("create or replace table raw.zone_spatial_fallback (location_id integer, "
                    "is_border_zone boolean, centroid_lon double, centroid_lat double)")
        cur.execute("copy into raw.zone_spatial_fallback "
                    "from @raw.zoneshift_stage/reference/zone_spatial_fallback.csv "
                    "file_format = (type = csv skip_header = 1)")

    counts, expected = {}, {}
    for t, table in TRIP_TABLES.items():
        counts[table] = cur.execute(f"select count(*) from {table}").fetchone()[0]
        expected[table] = sum(manifest["trips"].get(t, {}).values())
    ref_tables = dict(REF_TABLES)
    if "zone_spatial_fallback" in manifest["reference"]:
        ref_tables["zone_spatial_fallback"] = "raw.zone_spatial_fallback"
    for name, table in ref_tables.items():
        counts[table] = cur.execute(f"select count(*) from {table}").fetchone()[0]
        expected[table] = manifest["reference"][name]
    bad = {t: (counts[t], expected[t]) for t in counts if counts[t] != expected[t]}
    if bad:
        raise RuntimeError(f"Row count mismatch (loaded, expected): {bad}")
    return counts


def run_key_queries(conn) -> dict[str, list[tuple]]:
    cur = conn.cursor()
    return {name: cur.execute(sql).fetchall() for name, sql in key_queries().items()}


def connect():
    import snowflake.connector
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        role=os.environ.get("SNOWFLAKE_ROLE") or None,
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "ZONESHIFT_WH"),
        database=os.environ.get("SNOWFLAKE_DATABASE", "ZONESHIFT"),
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stage-dir", type=Path, default=ROOT / "data" / "warehouse_stage")
    p.add_argument("--key-queries", action="store_true", help="also run key_queries.sql and print results")
    args = p.parse_args()
    conn = connect()
    counts = load(conn, args.stage_dir)
    print(json.dumps(counts, indent=2))
    if args.key_queries:
        for name, rows in run_key_queries(conn).items():
            print(f"\n-- {name}"), [print(r) for r in rows]


if __name__ == "__main__":
    main()
