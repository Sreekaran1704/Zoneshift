"""Shared paths and helpers for ingestion scripts."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
REF_DIR = RAW_DIR / "reference"
DB_PATH = ROOT / "data" / "zoneshift.duckdb"
RESULTS_DIR = ROOT / "results"
METRICS_PATH = RESULTS_DIR / "metrics.json"


def update_metrics(updates: dict) -> None:
    """Merge `updates` into results/metrics.json (other keys are preserved)."""
    metrics = json.loads(METRICS_PATH.read_text()) if METRICS_PATH.exists() else {}
    metrics.update(updates)
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    METRICS_PATH.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n")
