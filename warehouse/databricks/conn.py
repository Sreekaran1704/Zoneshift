"""Databricks connection settings from .env (DATABRICKS_HOST / _HTTP_PATH / _TOKEN)."""
import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


def settings() -> dict:
    load_dotenv(ROOT / ".env")
    raw = os.environ["DATABRICKS_HOST"].strip()
    # Accept a bare hostname or a full URL pasted from the browser (scheme, path, query dropped)
    host = urlparse(raw if "://" in raw else f"https://{raw}").hostname
    return {"host": host, "http_path": os.environ["DATABRICKS_HTTP_PATH"].strip(),
            "token": os.environ["DATABRICKS_TOKEN"].strip()}


def connect():
    from databricks import sql

    s = settings()
    return sql.connect(server_hostname=s["host"], http_path=s["http_path"], access_token=s["token"])
