PY := .venv/bin/python
DBT := $(CURDIR)/.venv/bin/dbt
DBT_DIR := dbt/zoneshift
START ?= 2024-01
END ?= 2025-12
TYPES ?= yellow,green

.PHONY: setup ingest dbt dq analysis all

setup:
	python3 -m venv .venv || true
	$(PY) -m pip install -r requirements.txt

ingest:
	$(PY) ingestion/download.py --start $(START) --end $(END) --types $(TYPES)
	$(PY) ingestion/load_duckdb.py

$(DBT_DIR)/profiles.yml:
	cp $(DBT_DIR)/profiles.yml.example $@

dbt: $(DBT_DIR)/profiles.yml
	cd $(DBT_DIR) && $(DBT) build --profiles-dir .

# Data quality report + test counts (reads the run_results.json written by `make dbt`)
dq:
	$(PY) scripts/data_quality_report.py

analysis:
	$(PY) analysis/did.py

all: ingest dbt dq analysis
