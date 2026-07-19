# Airflow Monitoring Guide

## Operational Views

The DAG list shows overall state and recent duration. Grid shows every task
instance and retry. Graph confirms gate placement. Task logs include the
pipeline, batch, stage-run, feature-batch, model-run, and MLflow identifiers
where applicable.

Monitor:

- ingestion record count and manifest
- validation score and invalid records
- prepared interaction count and sparsity
- user, item, and user-item feature counts
- model metrics, best model, and MLflow run IDs
- total and per-task duration
- retries and failure records

## Durable Evidence

Each successful run publishes a machine-readable summary, CSV task table,
Markdown report, and plain-text evidence under
`reports/orchestration/dag_run_id=<id>/`. Technical failures publish structured
records under `reports/orchestration/failures/`.

Application logs continue under their existing `logs/<stage>/` folders. Airflow
task logs remain under `AIRFLOW_HOME/logs` or the deployment's remote logging
backend.

## Notifications

`LogNotificationService` is the credential-free default. It records task
success, retry, and failure notifications in Airflow logs. Production
deployments may implement email, Slack, or Teams through Airflow Connections.
Webhook URLs and tokens must be masked and never stored in Variables.

## Alert Interpretation

- A quality-gate failure is deterministic; inspect the PDF/JSON validation
  report before clearing the task.
- Feature-store gate failures indicate empty/missing persisted feature assets.
- Task retries indicate infrastructure recovery; inspect the previous attempt.
- A callback failure is logged separately and never changes the original task
  exception.
