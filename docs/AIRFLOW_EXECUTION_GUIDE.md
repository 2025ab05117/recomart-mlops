# Airflow Execution Guide

## Default Manual Run

Enable `recomart_end_to_end_pipeline` in the UI, make the popularity API
available, and trigger with default parameters.

```powershell
airflow dags trigger recomart_end_to_end_pipeline
```

PowerShell configuration example:

```powershell
airflow dags trigger recomart_end_to_end_pipeline `
  --conf '{"run_generator":true,"strict_quality":false,"run_versioning":true,"train_algorithm":"all","top_k":10}'
```

Bash:

```bash
airflow dags trigger recomart_end_to_end_pipeline \
  --conf '{"run_generator":true,"strict_quality":false,"run_versioning":true,"train_algorithm":"all","top_k":10}'
```

## Reprocess an Existing Batch

```powershell
airflow dags trigger recomart_end_to_end_pipeline `
  --conf '{"run_generator":false,"batch_id":"RECO_20260719_010203_ab12cd"}'
```

A supplied batch automatically disables generation. Existing stage idempotency
rules determine whether compatible outputs are reused.

## Selective Model Execution

Set `train_algorithm` to `collaborative`, `content`, or `all`. Set `top_k` to a
positive integer. `source_split=train` is the leakage-safe default; `all` is
exploratory and explicitly leakage-prone.

Generation, EDA, and version registration can be controlled with
`run_generator`, `run_eda`, and `run_versioning`. Stage reprocessing uses an
existing batch plus Airflow task clearing as described in the recovery guide.

## Inspect a Run

Use Grid for states, Graph for dependencies, and Task Instance → Log for stage
and application logs. Generated evidence is stored under:

```text
reports/orchestration/dag_run_id=<dag-run-id>/
```

Useful Airflow 3 commands:

```powershell
airflow dags list
airflow dags list-import-errors
airflow dags state recomart_end_to_end_pipeline <logical-date>
airflow tasks states-for-dag-run recomart_end_to_end_pipeline <dag-run-id>
```

Confirm exact syntax with `airflow <group> <command> --help` for the installed
release.

## Local Test Execution

Airflow 3 supports running the DAG file in test mode:

```powershell
airflow dags test recomart_end_to_end_pipeline -f dags/recomart_end_to_end_dag.py
```

This produces task logs and output artifacts but does not replace a scheduler/UI
run for screenshot evidence.
