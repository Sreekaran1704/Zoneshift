"""Download NYC TLC trip records and reference files into data/raw/.

Idempotent: a trip file is only written after its byte size matches the server's
Content-Length (via a .part file + atomic rename), so a file that exists and opens
in DuckDB with rows > 0 is skipped without touching the network.

Usage:
    python ingestion/download.py --start 2024-01 --end 2025-12 --types yellow,green
"""
import argparse
import csv
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import requests

from utils import RAW_DIR, REF_DIR, RESULTS_DIR

TRIP_URL = "https://d37ci6vzurychx.cloudfront.net/trip-data/{type}_tripdata_{month}.parquet"
REFERENCE_FILES = {
    "taxi_zone_lookup.csv": "https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv",
    "taxi_zones.zip": "https://d37ci6vzurychx.cloudfront.net/misc/taxi_zones.zip",
    "cbd_taxi_zones.csv": "https://data.ny.gov/api/views/yfdc-w5jh/rows.csv?accessType=DOWNLOAD",
}
VALID_TYPES = {"yellow", "green", "fhvhv"}
LOG_PATH = RESULTS_DIR / "ingestion_log.csv"
LOG_FIELDS = ["service_type", "month", "file", "bytes", "rows", "status", "checked_at"]


class NotPublished(Exception):
    """The month is not (yet) available on the server."""


def month_range(start: str, end: str) -> list[str]:
    y, m = map(int, start.split("-"))
    end_y, end_m = map(int, end.split("-"))
    months = []
    while (y, m) <= (end_y, end_m):
        months.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return months


def download(url: str, dest: Path, retries: int = 4, check_size: bool = True) -> int:
    """Stream url to dest with retries; returns bytes written."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(1, retries + 1):
        try:
            with requests.get(url, stream=True, timeout=(10, 120)) as r:
                if r.status_code in (403, 404):
                    raise NotPublished(f"HTTP {r.status_code} for {url}")
                r.raise_for_status()
                expected = int(r.headers.get("Content-Length", 0))
                written = 0
                with open(part, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
                        written += len(chunk)
            if check_size and expected and written != expected:
                raise IOError(f"size mismatch: got {written}, expected {expected}")
            part.replace(dest)
            return written
        except NotPublished:
            raise
        except (requests.RequestException, IOError) as e:
            part.unlink(missing_ok=True)
            if attempt == retries:
                raise
            wait = 2 ** attempt
            print(f"  retry {attempt}/{retries - 1} in {wait}s ({e})")
            time.sleep(wait)
    raise RuntimeError("unreachable")


def parquet_rows(path: Path) -> int:
    """Validate the file opens in DuckDB; return its row count (from Parquet metadata)."""
    return duckdb.sql(f"select count(*) from read_parquet('{path}')").fetchone()[0]


def fetch_trip_file(service_type: str, month: str) -> dict:
    dest = RAW_DIR / service_type / f"{service_type}_tripdata_{month}.parquet"
    row = {"service_type": service_type, "month": month, "file": str(dest.relative_to(RAW_DIR.parent.parent))}
    status = "skipped_existing"
    if dest.exists():
        try:
            rows = parquet_rows(dest)
        except duckdb.Error:
            rows = 0
        if rows == 0:  # corrupt or empty: re-download
            dest.unlink()
    if not dest.exists():
        try:
            download(TRIP_URL.format(type=service_type, month=month), dest)
        except NotPublished:
            return row | {"bytes": 0, "rows": 0, "status": "not_published"}
        status = "downloaded"
        rows = parquet_rows(dest)
        if rows == 0:
            dest.unlink()
            return row | {"bytes": 0, "rows": 0, "status": "invalid_empty"}
    return row | {"bytes": dest.stat().st_size, "rows": rows, "status": status}


def safe_extract(zip_path: Path, out_dir: Path) -> None:
    """Extract a zip, refusing members that would escape out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    root = out_dir.resolve()
    with zipfile.ZipFile(zip_path) as z:
        for member in z.namelist():
            target = (out_dir / member).resolve()
            if root not in target.parents and target != root:
                raise ValueError(f"unsafe path in zip: {member}")
        z.extractall(out_dir)


def fetch_reference_files() -> None:
    for name, url in REFERENCE_FILES.items():
        dest = REF_DIR / name
        if dest.exists() and dest.stat().st_size > 0:
            print(f"  skip {name} (exists)")
            continue
        # data.ny.gov exports may be served without Content-Length; size check is best-effort
        n = download(url, dest, check_size=not name.startswith("cbd"))
        print(f"  got {name} ({n / 1e6:.1f} MB)")
    shp_dir = REF_DIR / "taxi_zones"
    if not any(shp_dir.glob("**/*.shp")):
        safe_extract(REF_DIR / "taxi_zones.zip", shp_dir)
        print(f"  extracted shapefile to {shp_dir.relative_to(RAW_DIR.parent.parent)}")


def write_log(rows: list[dict]) -> None:
    """Upsert this run's rows into the ingestion log, keyed by (service_type, month)."""
    existing = {}
    if LOG_PATH.exists():
        with open(LOG_PATH) as f:
            existing = {(r["service_type"], r["month"]): r for r in csv.DictReader(f)}
    for r in rows:
        existing[(r["service_type"], r["month"])] = r
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        w.writeheader()
        w.writerows(sorted(existing.values(), key=lambda r: (r["service_type"], r["month"])))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", required=True, help="YYYY-MM")
    p.add_argument("--end", required=True, help="YYYY-MM")
    p.add_argument("--types", default="yellow,green")
    p.add_argument("--skip-reference", action="store_true")
    args = p.parse_args()

    types = [t.strip() for t in args.types.split(",")]
    bad = set(types) - VALID_TYPES
    if bad:
        p.error(f"unknown types: {bad}")

    if not args.skip_reference:
        print("Reference files:")
        fetch_reference_files()

    log_rows = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for t in types:
        for month in month_range(args.start, args.end):
            r = fetch_trip_file(t, month) | {"checked_at": now}
            log_rows.append(r)
            print(f"  {t} {month}: {r['status']:<16} {r['rows']:>12,} rows  {r['bytes'] / 1e6:7.1f} MB")
            write_log(log_rows)  # write as we go so an interrupted run keeps its progress

    missing = [f"{r['service_type']} {r['month']}" for r in log_rows if r["status"] in ("not_published", "invalid_empty")]
    total_mb = sum(r["bytes"] for r in log_rows) / 1e6
    print(f"Done: {len(log_rows) - len(missing)}/{len(log_rows)} files OK, {total_mb:,.0f} MB on disk.")
    if missing:
        print("Missing:", ", ".join(missing))


if __name__ == "__main__":
    main()
