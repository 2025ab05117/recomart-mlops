# End-to-End Execution Guide

This is the cross-stage command sequence. Follow the linked stage guides for
prerequisites, configuration, verification, and troubleshooting.

## Prerequisites

- Python 3.12 environment with `requirements.txt` installed
- MovieLens source files under `data/basedata/ml-100k/`
- Environment variables for optional PostgreSQL, S3/MinIO, and remote MLflow
- No credentials in YAML, command arguments, documentation, or Git

## Ordered Local Execution

1. Generate incoming data:

   ```powershell
   python -m src.generator.batch_generator
   ```

2. Start the popularity API:

   ```powershell
   python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
   ```

3. Run [ingestion](../pipeline/ingestion/INGESTION_EXECUTION_GUIDE.md):

   ```powershell
   python -m src.ingestion.cli
   ```

4. Run [validation](../pipeline/validation/VALIDATION_EXECUTION_GUIDE.md):

   ```powershell
   python -m src.validation.cli
   ```

5. Run [preparation and EDA](../pipeline/preparation/PREPARATION_EXECUTION_GUIDE.md):

   ```powershell
   python -m src.preparation.cli
   ```

6. Initialize and run [feature engineering](../pipeline/feature_engineering/FEATURE_EXECUTION_GUIDE.md):

   ```powershell
   $env:RECOMART_DATABASE_URL = "sqlite:///data/recomart_features.db"
   python -m src.feature_engineering.cli --initialize-database
   python -m src.feature_engineering.cli
   ```

7. Run [versioning and lineage](../pipeline/versioning/DVC_GUIDE.md):

   ```powershell
   python -m src.versioning.cli
   ```

8. Run [model training](../pipeline/modeling/MODEL_TRAINING_DESIGN.md):

   ```powershell
   python -m src.modeling.cli --algorithm all
   ```

## Airflow Execution

For orchestrated execution, follow the
[Airflow Setup Guide](../pipeline/orchestration/AIRFLOW_SETUP_GUIDE.md), then
trigger:

```powershell
airflow dags trigger recomart_end_to_end_pipeline
```

Airflow invokes the same application services and does not replace their
business logic.

## Verify Outputs

Inspect each stage's authoritative manifest before downstream artifacts:
ingestion, validation, preparation, feature, versioning registry/lineage, and
model training summary. For Airflow, inspect
`reports/orchestration/dag_run_id=<id>/pipeline_run_summary.json`.

## Troubleshooting

Use the stage execution guide nearest the failure. For task reruns, database
recovery, validation gates, model failures, and immutable conflicts, use the
[Pipeline Recovery Guide](../pipeline/orchestration/PIPELINE_RECOVERY_GUIDE.md).

[Back to Documentation Home](../README.md)
