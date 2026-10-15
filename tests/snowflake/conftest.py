"""Fixtures for the Snowflake-dialect tests (run against fakesnow, no Snowflake account needed).

Requires data/zoneshift.duckdb built by the pipeline (CI builds it from small downloaded months).
"""
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "zoneshift.duckdb"
# A pre-policy and a post-policy month (the post month starts after 2025-01-05)
SAMPLE_MONTHS = ["2024-12", "2025-02"]
SAMPLE_ROWS_PER_FILE = 2000


@pytest.fixture(scope="session")
def trip_types() -> list[str]:
    if not DB_PATH.exists():
        pytest.skip("data/zoneshift.duckdb not built; run `make ingest dbt` first")
    types = [t for t in ["yellow", "green"]
             if all((ROOT / "data" / "raw" / t / f"{t}_tripdata_{m}.parquet").exists() for m in SAMPLE_MONTHS)]
    if not types:
        pytest.skip(f"raw files for {SAMPLE_MONTHS} not downloaded")
    return types


@pytest.fixture(scope="session")
def stage_dir(tmp_path_factory, trip_types) -> Path:
    """Deterministic sample prepared exactly as for a real Snowflake load."""
    out = tmp_path_factory.mktemp("warehouse_stage")
    subprocess.run(
        [sys.executable, str(ROOT / "ingestion" / "prepare_warehouse_files.py"), "--out", str(out),
         "--types", ",".join(trip_types), "--months", ",".join(SAMPLE_MONTHS),
         "--sample-per-file", str(SAMPLE_ROWS_PER_FILE), "--spatial-fallback"],
        check=True, capture_output=True, text=True)
    return out


@pytest.fixture()
def duck(stage_dir):
    """DuckDB over the same prepared files, to compute expected results independently."""
    con = duckdb.connect()
    for t in ["yellow", "green"]:
        files = sorted((stage_dir / t).glob("*.parquet"))
        if files:
            con.execute(f"create view {t}_tripdata as select * from read_parquet('{stage_dir / t}/*.parquet')")
    con.execute(f"create view cbd_taxi_zones as select * from read_csv('{stage_dir}/reference/cbd_taxi_zones.csv', header=true)")
    return con
