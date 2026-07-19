#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export AIRFLOW_HOME="${AIRFLOW_HOME:-$ROOT/.airflow}"
export AIRFLOW__CORE__DAGS_FOLDER="${AIRFLOW__CORE__DAGS_FOLDER:-$ROOT/dags}"
export AIRFLOW__CORE__LOAD_EXAMPLES="${AIRFLOW__CORE__LOAD_EXAMPLES:-False}"
export AIRFLOW__CORE__EXECUTOR="${AIRFLOW__CORE__EXECUTOR:-SequentialExecutor}"
export AIRFLOW__CORE__DEFAULT_TIMEZONE="${AIRFLOW__CORE__DEFAULT_TIMEZONE:-utc}"
export PYTHONPATH="${PYTHONPATH:-$ROOT}"
cd "$ROOT"
python -m airflow standalone
