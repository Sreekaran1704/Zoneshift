"""ZoneShift monthly pipeline: detect newly published TLC months, download, validate, rebuild.

Runs the same scripts as the Makefile (ingestion/, dbt, scripts/, dashboard/export.py) from an
isolated venv in the image. The pre-registered DiD (analysis/did.py) is pinned to 2024-2025 and
is not re-run here.

Params (trigger with config to backfill):
    backfill_start / backfill_end: "YYYY-MM" to (re)load an explicit month range.
    types: comma-separated trip types (default "yellow,green").
    max_months: cap on how many new months one run may load.
"""
import csv
import os
import re
import shlex
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

from airflow.exceptions import AirflowFailException, AirflowSkipException
from airflow.sdk import Param, dag, task

HOME = os.environ.get("ZONESHIFT_HOME", "/opt/zoneshift")
VENV = "/opt/zoneshift-venv/bin"
LOG = Path(HOME) / "results" / "ingestion_log.csv"
TRIP_URL = "https://d37ci6vzurychx.cloudfront.net/trip-data/{type}_tripdata_{month}.parquet"
OK_STATUSES = {"downloaded", "skipped_existing"}
MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"
VALID_TYPES = {"yellow", "green", "fhvhv"}


def checked_month(value: str, name: str) -> str:
    """Params reach a shell command, so validate them here (Param schemas can be bypassed)."""
    if not isinstance(value, str) or not re.fullmatch(MONTH_PATTERN, value):
        raise AirflowFailException(f"{name} must be YYYY-MM, got {value!r}")  # bad input: no retries
    return value


def next_month(month: str) -> str:
    y, m = map(int, month.split("-"))
    return f"{y + (m == 12):04d}-{m % 12 + 1:02d}"


def month_range(start: str, end: str) -> list[str]:
    out = [start]
    while out[-1] < end:
        out.append(next_month(out[-1]))
    return out


def is_published(service_type: str, month: str) -> bool:
    req = urllib.request.Request(TRIP_URL.format(type=service_type, month=month), method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status == 200
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):  # CloudFront returns 403 for months not yet published
            return False
        raise


def read_log() -> list[dict]:
    if not LOG.exists():
        return []
    with open(LOG) as f:
        return list(csv.DictReader(f))


@dag(
    dag_id="zoneshift_monthly",
    description="Load newly published NYC TLC months and rebuild the ZoneShift warehouse",
    schedule="0 6 20 * *",  # TLC posts monthly files with a ~2 month lag; check on the 20th
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=10)},
    params={
        "backfill_start": Param(None, type=["null", "string"], pattern=MONTH_PATTERN),
        "backfill_end": Param(None, type=["null", "string"], pattern=MONTH_PATTERN),
        "types": Param("yellow,green", type="string"),
        "max_months": Param(12, type="integer", minimum=1),
    },
    doc_md=__doc__,
    tags=["zoneshift", "tlc"],
)
def zoneshift_monthly():

    @task
    def detect_months(params: dict) -> dict:
        types = [t.strip() for t in str(params["types"]).split(",")]
        if not types or set(types) - VALID_TYPES:
            raise AirflowFailException(f"types must be a comma-separated subset of {sorted(VALID_TYPES)}")
        if params["backfill_start"]:
            start = checked_month(params["backfill_start"], "backfill_start")
            end = checked_month(params["backfill_end"] or start, "backfill_end")
            if end < start:
                raise AirflowFailException(f"backfill_end {end} is before backfill_start {start}")
            print(f"Backfill requested: {start}..{end}")
            return {"start": start, "end": end, "types": ",".join(types)}

        loaded = {}
        for r in read_log():
            if r["status"] in OK_STATUSES and int(r["rows"]) > 0:
                loaded.setdefault(r["service_type"], set()).add(r["month"])
        if not all(t in loaded for t in types):
            raise ValueError(f"No loaded months for some of {types}; run a backfill first")
        latest = min(max(loaded[t]) for t in types)  # newest month loaded for every type

        current = date.today().strftime("%Y-%m")
        new, month = [], next_month(latest)
        while month <= current and len(new) < params["max_months"]:
            if not all(is_published(t, month) for t in types):
                break
            new.append(month)
            month = next_month(month)
        print(f"Latest loaded month: {latest}; newly published: {new or 'none'}")
        if not new:
            raise AirflowSkipException(f"Nothing new after {latest}")
        return {"start": new[0], "end": new[-1], "types": ",".join(types)}

    @task.bash(cwd=HOME)
    def download(months: dict) -> str:
        q = {k: shlex.quote(str(v)) for k, v in months.items()}  # defence in depth after validation
        return f"{VENV}/python ingestion/download.py --start {q['start']} --end {q['end']} --types {q['types']}"

    @task
    def validate(months: dict) -> int:
        want = {(t, m) for t in months["types"].split(",")
                for m in month_range(months["start"], months["end"])}
        rows = {(r["service_type"], r["month"]): r for r in read_log()}
        bad = sorted(k for k in want if k not in rows or rows[k]["status"] not in OK_STATUSES
                     or int(rows[k]["rows"]) <= 0)
        if bad:
            raise ValueError(f"Months missing or invalid after download: {bad}")
        total = sum(int(rows[k]["rows"]) for k in want)
        print(f"Validated {len(want)} files, {total:,} rows")
        return total

    load_duckdb = task.bash(cwd=HOME, task_id="load_duckdb")(
        lambda: f"{VENV}/python ingestion/load_duckdb.py")()

    dbt_build = task.bash(cwd=f"{HOME}/dbt/zoneshift", task_id="dbt_build")(
        lambda: "(test -f profiles.yml || cp profiles.yml.example profiles.yml) && "
                f"{VENV}/dbt build --profiles-dir .")()

    dq_report = task.bash(cwd=HOME, task_id="data_quality_report")(
        lambda: f"{VENV}/python scripts/data_quality_report.py")()

    refresh_exports = task.bash(cwd=HOME, task_id="refresh_dashboard_exports")(
        lambda: f"{VENV}/python dashboard/export.py")()

    months = detect_months()
    download(months) >> validate(months) >> load_duckdb >> dbt_build >> dq_report >> refresh_exports


zoneshift_monthly()
