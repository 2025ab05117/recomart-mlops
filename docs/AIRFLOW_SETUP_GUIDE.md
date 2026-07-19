# Airflow Setup Guide

## Supported Environment

RecoMart application code targets Python 3.12. Apache Airflow 3.1.2 is pinned
for orchestration and must be installed with the matching official constraints
file. Airflow is supported on POSIX systems; on Windows use Docker Desktop or
WSL for the scheduler and web UI.

## Constrained Installation

Create a dedicated virtual environment so Airflow's dependency constraints do
not alter the RecoMart application environment.

```bash
python3.12 -m venv .airflow-venv
source .airflow-venv/bin/activate
AIRFLOW_VERSION=3.1.2
PYTHON_VERSION=3.12
pip install "apache-airflow==${AIRFLOW_VERSION}" \
  --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt"
```

Do not install an unconstrained `apache-airflow` package.

## Local Metadata Database

Copy `airflow/config/airflow.env.example` values into the shell environment,
then run:

```bash
export AIRFLOW_HOME="$PWD/.airflow"
export AIRFLOW__CORE__DAGS_FOLDER="$PWD/dags"
export AIRFLOW__CORE__LOAD_EXAMPLES=False
export AIRFLOW__CORE__EXECUTOR=SequentialExecutor
export PYTHONPATH="$PWD"
airflow standalone
```

Standalone initializes the SQLite metadata database, creates local credentials,
and starts the scheduler/API/UI. Credentials are written beneath
`AIRFLOW_HOME`; never commit them.

For separate services, initialize the database, create an administrator using
the commands supported by the installed Airflow version, then start the API
server and scheduler. Use `airflow --help` because service command names changed
between Airflow 2 and 3.

## Docker Desktop

From the repository root:

```powershell
docker compose -f airflow/compose.yaml up --build
```

The Compose environment mounts the repository, uses SequentialExecutor, exposes
port 8080, and keeps Airflow metadata in a named volume. No credentials are
embedded in Compose.

## Required Services

Before an end-to-end run:

1. Ensure the popularity API is reachable at the ingestion-configured URL.
2. Set `RECOMART_DATABASE_URL`; SQLite is the local fallback.
3. Set `MLFLOW_TRACKING_URI` or use the configured local `mlruns` store.
4. Configure AWS/MinIO credentials only when `storage=s3`.

Example:

```powershell
$env:RECOMART_DATABASE_URL = "sqlite:///data/recomart_features.db"
$env:MLFLOW_TRACKING_URI = "file:./mlruns"
```

## Airflow Variables and Connections

Non-secret Variables may include:

- `recomart_pipeline_schedule`
- `recomart_default_storage`
- `recomart_strict_quality`
- `recomart_model_algorithm`
- `recomart_top_k`

Use Connections for `recomart_feature_db`, `recomart_s3`,
`recomart_mlflow`, and `recomart_notification`. Never store passwords or
webhooks in Variables.

## Verify Discovery

```powershell
python airflow/scripts/verify_airflow_setup.py
airflow dags list
airflow dags list-import-errors
```

The output must contain `recomart_end_to_end_pipeline` and no import errors.
