"""Run dbt against the `databricks` target with credentials from .env.

dbt does not read .env, and DATABRICKS_HOST may be pasted as a full browser URL, so this wrapper
normalizes the host, uses the committed profiles.yml.example, and passes any extra dbt arguments.
The dbt output is also saved to docs/databricks/dbt_build.log.

Usage:
    python warehouse/databricks/run_dbt.py build
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from conn import ROOT, settings

DBT = str(Path(sys.executable).parent / "dbt")


def main() -> None:
    s = settings()
    env = {**os.environ, "DATABRICKS_HOST": s["host"], "DATABRICKS_HTTP_PATH": s["http_path"],
           "DATABRICKS_TOKEN": s["token"]}
    with tempfile.TemporaryDirectory() as prof:
        shutil.copy(ROOT / "dbt" / "zoneshift" / "profiles.yml.example", Path(prof) / "profiles.yml")
        r = subprocess.run([DBT, *(sys.argv[1:] or ["build"]), "--profiles-dir", prof, "--target", "databricks",
                            # own artifacts dir: target/ keeps the DuckDB manifest + run_results
                            "--target-path", "target-databricks"],
                           cwd=ROOT / "dbt" / "zoneshift", env=env, capture_output=True, text=True)
    out = re.sub(r"\x1b\[[0-9;]*m", "", r.stdout + r.stderr)
    log = ROOT / "docs" / "databricks" / "dbt_build.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(out)
    print("\n".join(out.splitlines()[-25:]))
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
