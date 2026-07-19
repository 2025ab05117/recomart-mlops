param(
    [string]$Python = ".\.airflow-venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$env:AIRFLOW_HOME = Join-Path $root ".airflow"
$env:AIRFLOW__CORE__DAGS_FOLDER = Join-Path $root "dags"
$env:AIRFLOW__CORE__LOAD_EXAMPLES = "False"
$env:AIRFLOW__CORE__EXECUTOR = "SequentialExecutor"
$env:AIRFLOW__CORE__DEFAULT_TIMEZONE = "utc"
$env:PYTHONPATH = $root
Set-Location $root
& $Python -m airflow standalone
