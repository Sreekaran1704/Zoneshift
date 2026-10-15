"""Schema context for the agent: allowlisted marts with dbt descriptions and actual column types."""
import json
from functools import lru_cache
from pathlib import Path

import duckdb

from agent.guard import ALLOWED_SCHEMA, ALLOWED_TABLES

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "dbt" / "zoneshift" / "target" / "manifest.json"
DB_PATH = ROOT / "data" / "zoneshift.duckdb"
TABLE_ORDER = ["fct_trips", "agg_zone_day", "agg_zone_hour", "dim_zone", "dim_date"]


def connect() -> duckdb.DuckDBPyConnection:
    """Read-only connection with file/network access disabled (second guard layer)."""
    return duckdb.connect(str(DB_PATH), read_only=True,
                          config={"enable_external_access": False, "lock_configuration": True})


@lru_cache(maxsize=1)
def schema_context() -> str:
    if not MANIFEST.exists():
        raise SystemExit("dbt manifest not found: run `dbt parse` (or `make dbt`) first")
    nodes = json.loads(MANIFEST.read_text())["nodes"]
    con = connect()
    first, last = con.execute("select min(date_day), max(date_day) from marts.dim_date").fetchone()
    lines = [
        f"DuckDB database. Query only these tables, always schema-qualified as {ALLOWED_SCHEMA}.<table>.",
        f"Data covers pickup dates {first} to {last}. NYC congestion pricing started 2025-01-05.",
        "",
    ]
    for t in TABLE_ORDER:
        assert t in ALLOWED_TABLES
        node = nodes[f"model.zoneshift.{t}"]
        rows = con.execute(
            "select column_name, data_type from information_schema.columns "
            "where table_schema = ? and table_name = ? order by ordinal_position", [ALLOWED_SCHEMA, t]
        ).fetchall()
        lines.append(f"TABLE {ALLOWED_SCHEMA}.{t}: {' '.join(node['description'].split())}")
        for col, typ in rows:
            desc = " ".join(node["columns"].get(col, {}).get("description", "").split())
            lines.append(f"  - {col} {typ}" + (f": {desc}" if desc else ""))
        lines.append("")
    lines += [
        "NOTES:",
        "- agg_zone_day and agg_zone_hour have service_type 'yellow', 'green' and 'all' (= both). "
        "Always filter service_type (use 'all' for both services) or trips are double counted.",
        "- fct_trips has one row per clean trip (service_type 'yellow' or 'green' only); it is large, "
        "so prefer agg_zone_day for zone/day totals when it has the needed columns.",
        "- Zone names, boroughs and the CBD/border flags are in dim_zone (join on location_id = "
        "pu_location_id or do_location_id). Calendar attributes are in dim_date (join on date_day).",
        "- 'CBD' = congestion pricing zone (dim_zone.is_cbd); 'before/after the policy' = "
        "dim_date.post_policy or pickup_date >= DATE '2025-01-05'.",
    ]
    return "\n".join(lines)
