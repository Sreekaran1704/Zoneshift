FROM apache/airflow:3.3.2-python3.12

# Pipeline code runs from an isolated venv so dbt/duckdb/pandas pins never touch Airflow's deps.
USER root
RUN python -m venv /opt/zoneshift-venv && chown -R airflow: /opt/zoneshift-venv
USER airflow
COPY requirements-pipeline.txt /tmp/requirements-pipeline.txt
RUN /opt/zoneshift-venv/bin/pip install --no-cache-dir -r /tmp/requirements-pipeline.txt \
 && /opt/zoneshift-venv/bin/python -c "import duckdb; duckdb.sql('install spatial')"
