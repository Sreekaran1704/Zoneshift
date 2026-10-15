"""Snowflake loader (DDL -> stage PUT -> COPY INTO) and key Snowflake-dialect queries on fakesnow."""
import json
import sys
from pathlib import Path

import fakesnow
import pytest
import snowflake.connector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "warehouse" / "snowflake"))
import load  # noqa: E402


@pytest.fixture()
def sf(stage_dir):
    with fakesnow.patch():
        conn = snowflake.connector.connect(database="ZONESHIFT", schema="RAW")
        conn.cursor().execute("create database if not exists ZONESHIFT")
        yield conn, load.load(conn, stage_dir)


def test_copy_loads_every_row(sf, stage_dir):
    _, counts = sf
    manifest = json.loads((stage_dir / "manifest.json").read_text())
    for t, files in manifest["trips"].items():
        assert counts[f"raw.{t}_tripdata"] == sum(files.values()) > 0
    assert counts["raw.taxi_zone_lookup"] == 265
    assert counts["raw.cbd_taxi_zones"] == 38
    assert counts["raw.load_metadata"] == 1


def test_loaded_values_round_trip(sf, duck, trip_types):
    """Spot-check that types survive COPY: sums and timestamps match DuckDB on the same files."""
    conn, _ = sf
    for t in trip_types:
        ts = "tpep_pickup_datetime" if t == "yellow" else "lpep_pickup_datetime"
        q = f"select count(*), round(sum(fare_amount), 2), min({ts}), max(file_row_number) from {t}_tripdata"
        got = conn.cursor().execute(q.replace(f"from {t}", f"from raw.{t}")).fetchone()
        want = duck.execute(q).fetchone()
        assert tuple(got) == tuple(want)


def test_key_queries_match_duckdb(sf, duck, trip_types):
    conn, _ = sf
    results = load.run_key_queries(conn)
    assert set(results) == set(load.key_queries())

    if "yellow" in trip_types:
        want = duck.execute("""
            select case when c."Taxi Zone" is not null then 'cbd' else 'other' end,
                   case when y.tpep_pickup_datetime >= timestamp '2025-01-05' then 'post' else 'pre' end,
                   count(*), median(y.fare_amount)
            from yellow_tripdata y left join cbd_taxi_zones c on c."Taxi Zone" = y.PULocationID
            group by 1, 2 order by 1, 2
        """).fetchall()
        assert [tuple(r) for r in results["cbd_vs_other_pre_post"]] == want
        assert {r[1] for r in want} == {"pre", "post"}  # sample spans the policy date

        want_fee = duck.execute("""
            select cbd_congestion_fee, count(*) from yellow_tripdata
            where tpep_pickup_datetime >= timestamp '2025-01-05' group by 1 order by 1 nulls first
        """).fetchall()
        assert [tuple(r) for r in results["cbd_fee_distribution"]] == want_fee

    months = duck.execute(" union all ".join(
        f"select '{t}', regexp_extract(filename, '[0-9]{{4}}-[0-9]{{2}}'), count(*) from {t}_tripdata group by 1, 2"
        for t in trip_types) + " order by 1, 2").fetchall()
    assert [tuple(r) for r in results["trips_by_service_month"]] == months
