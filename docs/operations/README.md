# Operations Documentation

This folder contains cross-stage operating guidance. Detailed commands,
failure modes, and output contracts remain in each stage's execution guide.

## Reading Order

1. [END_TO_END_EXECUTION_GUIDE.md](END_TO_END_EXECUTION_GUIDE.md)
2. [Airflow Setup Guide](../pipeline/orchestration/AIRFLOW_SETUP_GUIDE.md)
3. [Airflow Monitoring Guide](../pipeline/orchestration/AIRFLOW_MONITORING_GUIDE.md)
4. [Pipeline Recovery Guide](../pipeline/orchestration/PIPELINE_RECOVERY_GUIDE.md)

## Related Repository Areas

- Stage CLIs: `src/*/cli.py`
- Airflow environment: `airflow/`
- Runtime configuration: `configs/`, environment variables
- Pipeline DAG: `dags/recomart_end_to_end_dag.py`

[Back to Documentation Home](../README.md)
