PY := .venv/bin/python
DBT := $(CURDIR)/.venv/bin/dbt
DBT_DIR := dbt/zoneshift
START ?= 2024-01
END ?= 2025-12
TYPES ?= yellow,green

.PHONY: setup ingest dbt dq analysis dashboard app test warehouse-files databricks ask agent-eval airflow-build airflow-up airflow-down all

# Python 3.12 venv (uv if installed, else python3.12) + pinned deps
setup:
	@if command -v uv >/dev/null 2>&1; then \
		uv venv --python 3.12 .venv && uv pip install --python $(PY) -r requirements.txt -r requirements-dev.txt; \
	else \
		python3.12 -m venv .venv && $(PY) -m pip install -r requirements.txt -r requirements-dev.txt; \
	fi

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
	$(PY) analysis/render_readme.py

# Export marts + results for the dashboard (dashboard/data/, committed so the app runs from a clone)
dashboard:
	$(PY) dashboard/export.py

app:
	.venv/bin/streamlit run dashboard/app.py

# Snowflake-dialect tests on the fakesnow emulator (no account needed)
test:
	$(PY) -m pytest -q

# Warehouse-neutral load files for Snowflake / Databricks (data/warehouse_stage/)
warehouse-files:
	$(PY) ingestion/prepare_warehouse_files.py

# Databricks Free Edition: 1% deterministic sample + full marts, dbt build in the cloud, verify vs DuckDB
databricks:
	$(PY) ingestion/prepare_warehouse_files.py --out data/warehouse_stage_databricks --sample-mod 100
	$(PY) warehouse/databricks/load.py
	$(PY) warehouse/databricks/run_dbt.py build
	$(PY) warehouse/databricks/verify.py

# Text-to-SQL agent (needs GROQ_API_KEY in .env)
ask:
	$(PY) -m agent.cli

agent-eval:
	$(PY) -m agent.eval.run_eval

AIRFLOW_DIR := orchestration/airflow

# Airflow (Docker): image with the pipeline in an isolated venv; repo mounted at the same path
$(AIRFLOW_DIR)/.env:
	printf "AIRFLOW_UID=%s\nZONESHIFT_HOME=%s\n" "$$(id -u)" "$(CURDIR)" > $@

airflow-build:
	docker build -t zoneshift-airflow:3.3.2 $(AIRFLOW_DIR)

airflow-up: $(AIRFLOW_DIR)/.env
	cd $(AIRFLOW_DIR) && docker compose up airflow-init && docker compose up -d
	@echo "Airflow UI: http://localhost:8080 (airflow / airflow)"

airflow-down:
	cd $(AIRFLOW_DIR) && docker compose down

all: ingest dbt dq analysis dashboard
