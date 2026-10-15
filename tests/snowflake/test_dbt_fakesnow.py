"""Run the full dbt project on the `fakesnow` target (Snowflake dialect via the emulator) and check
the clean trip set equals the DuckDB build for the same sampled trips."""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import duckdb
import fakesnow
import snowflake.connector

ROOT = Path(__file__).resolve().parents[2]
DBT_DIR = ROOT / "dbt" / "zoneshift"
sys.path.insert(0, str(ROOT / "warehouse" / "snowflake"))
import load  # noqa: E402

DBT = str(Path(sys.executable).parent / "dbt")


def test_dbt_build_on_fakesnow(stage_dir, tmp_path):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    shutil.copy(DBT_DIR / "profiles.yml.example", profiles / "profiles.yml")

    with fakesnow.server() as kw:
        conn = snowflake.connector.connect(**kw, database="ZONESHIFT", schema="RAW")
        conn.cursor().execute("create database if not exists ZONESHIFT")
        load.load(conn, stage_dir)

        env = {**os.environ, "FAKESNOW_HOST": kw["host"], "FAKESNOW_PORT": str(kw["port"])}
        r = subprocess.run(
            [DBT, "build", "--profiles-dir", str(profiles), "--target", "fakesnow",
             "--target-path", str(tmp_path / "target"), "--log-path", str(tmp_path / "logs")],
            cwd=DBT_DIR, env=env, capture_output=True, text=True)
        summary = re.sub(r"\x1b\[[0-9;]*m", "", r.stdout)
        assert r.returncode == 0, summary[-4000:]
        assert re.search(r"Done\. PASS=\d+ WARN=\d+ ERROR=0 SKIP=0", summary), summary[-2000:]

        sf_ids = {row[0] for row in conn.cursor().execute("select trip_id from MARTS.FCT_TRIPS").fetchall()}
        window = conn.cursor().execute("select window_start, window_end from RAW.LOAD_METADATA").fetchone()

    # Same trips through the DuckDB build: sampled trip_ids inside the sample's window
    duck = duckdb.connect(str(ROOT / "data" / "zoneshift.duckdb"), read_only=True)
    sampled = " union all ".join(
        f"select {code} * 100000000000000 + cast(replace(regexp_extract(filename, '[0-9]{{4}}-[0-9]{{2}}'), '-', '') as bigint)"
        f" * 100000000 + file_row_number as trip_id from read_parquet('{stage_dir / t}/*.parquet')"
        for t, code in [("yellow", 1), ("green", 2)] if any((stage_dir / t).glob("*.parquet")))
    duck_ids = {row[0] for row in duck.execute(f"""
        select f.trip_id from marts.fct_trips f join ({sampled}) s using (trip_id)
        where f.pickup_at >= ? and f.pickup_at < ?
    """, [window[0], window[1]]).fetchall()}
    assert sf_ids and sf_ids == duck_ids
