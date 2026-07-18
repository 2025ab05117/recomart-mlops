# MLflow Guide

## Tracking behavior

The modeling pipeline uses the URI in `MLFLOW_TRACKING_URI` when set. Otherwise
it uses the configured local `mlruns/` store. MLflow 3.x local-file tracking is
explicitly opted in for this assignment fallback. A remote HTTP tracking server
can be used without code changes.

## Run the pipeline

```powershell
python -m src.modeling.cli --algorithm all
```

The experiment name defaults to `recomart-recommendation-models`. Collaborative
and content models receive independent MLflow runs so their parameters,
metrics, and artifacts remain independently addressable.

## Start the local UI

```powershell
$env:MLFLOW_ALLOW_FILE_STORE = "true"
mlflow ui --backend-store-uri ./mlruns --port 5000
```

Open `http://localhost:5000` and select the RecoMart experiment.

## Logged data

Parameters include algorithm settings, feature batch, source batch, dataset
sizes, K, and configuration hash. Metrics include accuracy, ranking, coverage,
diversity, novelty, duration, and memory-related summaries where applicable.
Artifacts include serialized models, evaluation JSON, metadata, and the
effective training configuration.

MLflow returns `run_id`, `experiment_id`, and `artifact_uri`; these are copied
into the training summary and model metadata.

## Remote server

Set only a non-secret endpoint:

```powershell
$env:MLFLOW_TRACKING_URI = "http://localhost:5000"
python -m src.modeling.cli
```

Authentication secrets belong in the environment or platform secret manager.
They must never be placed in YAML, command history, model metadata, or logs.

## Troubleshooting

- Verify `mlflow` is installed in the active virtual environment.
- On MLflow 3.x file-store errors, use the CLI shown above; the pipeline itself
  supplies the required opt-in.
- If a remote server is unreachable, either restore it or remove
  `MLFLOW_TRACKING_URI` to use local tracking.
- Inspect `logs/modeling/model_training.log` for the model-run and feature-batch
  context. Credential-bearing URLs are never logged.
