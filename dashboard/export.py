"""Export dashboard data from data/zoneshift.duckdb + results/ into dashboard/data/.

Parquet files are small enough to commit, so the Streamlit app runs from a fresh clone (and on
Streamlit Community Cloud) without the 1.5 GB raw data. Use --csv to also write CSVs for
Tableau Public / Power BI.

Usage:
    python dashboard/export.py [--csv]
"""
import argparse
import json
import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ingestion"))
from utils import DB_PATH, RESULTS_DIR  # noqa: E402

OUT = ROOT / "dashboard" / "data"
MARTS = ["agg_zone_day", "agg_zone_hour", "dim_zone", "dim_date"]
SIMPLIFY_FT = 40  # polygon simplification tolerance (NY State Plane feet) for a lighter map


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--csv", action="store_true", help="also write CSV copies")
    args = p.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(DB_PATH), read_only=True)
    con.execute("load spatial")
    frames = {t: con.sql(f"select * from marts.{t}").df() for t in MARTS}
    frames["did_results"] = pd.read_csv(RESULTS_DIR / "did_results.csv")
    frames["event_study"] = pd.read_csv(RESULTS_DIR / "event_study.csv")

    for name, df in frames.items():
        df.to_parquet(OUT / f"{name}.parquet", index=False)
        if args.csv:
            df.to_csv(OUT / f"{name}.csv", index=False)

    # Zone polygons as WGS84 GeoJSON with dim_zone attributes
    rows = con.execute(f"""
        select z.location_id, z.zone, z.borough, z.is_cbd, z.is_border_zone,
               st_asgeojson(st_transform(st_simplifypreservetopology(s.geom, {SIMPLIFY_FT}),
                                         'EPSG:2263', 'EPSG:4326', always_xy := true)) as geometry
        from marts.dim_zone z join staging.stg_taxi_zone_shapes s using (location_id)
        order by z.location_id
    """).fetchall()
    features = [{
        "type": "Feature",
        "properties": {"location_id": r[0], "zone": r[1], "borough": r[2],
                       "is_cbd": r[3], "is_border_zone": r[4]},
        "geometry": json.loads(r[5]),
    } for r in rows]
    (OUT / "zones.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}))

    sizes = {f.name: f"{f.stat().st_size / 1e6:.1f} MB" for f in sorted(OUT.iterdir())}
    print("Exported to dashboard/data:", sizes)


if __name__ == "__main__":
    main()
