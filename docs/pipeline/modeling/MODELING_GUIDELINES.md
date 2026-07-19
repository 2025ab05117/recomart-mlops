# Modeling and MLflow Guidelines

## Purpose

RecoMart trains reproducible recommendation baselines and candidate models from
registered feature materializations. Model code lives in `src/modeling/`, not
DAGs or notebooks.

## Modeling Scope

Scikit-Learn is the primary modeling framework. The initial system should favor
interpretable, well-tested baselines before adding complexity. Depending on the
declared problem, supported approaches may include:

- global, user, item, and popularity baselines;
- content-based ranking or similarity;
- supervised rating prediction using engineered user/item features;
- ranking candidates using a documented negative-sampling strategy.

The prediction target and serving interpretation must be explicit. Rating
prediction metrics must not be presented as ranking quality without a ranking
evaluation design.

## Training Contract

Every training run specifies:

- registered feature materialization IDs and checksums;
- target definition and excluded columns;
- split strategy and cutoff timestamps;
- estimator and hyperparameters;
- preprocessing artifact versions;
- random seeds;
- evaluation metrics and acceptance thresholds;
- code, dependency, and configuration versions.

Training consumes features only from the feature layer. Direct reads from raw,
validated, or prepared layers are prohibited.

## Dataset Splitting

Temporal splits are preferred. The split implementation prevents the same
future interaction from influencing past features. User/item coverage and
cold-start composition are recorded per split.

Cross-validation, if used, must respect time and entity leakage constraints.
Hyperparameter selection uses only training and validation data. The test set is
evaluated once for the selected candidate.

## Reproducibility

- Pin input asset and feature definition versions.
- Set and log all available random seeds.
- Record dependency and Python versions.
- Persist fitted preprocessing with the model.
- Use deterministic ordering before sampling.
- Record the source-control revision and dirty-state indicator.

A run is reproducible when another worker with the recorded inputs and
configuration can produce equivalent metrics within declared numerical
tolerance.

## Evaluation

Metric selection follows the task:

- rating prediction: RMSE, MAE, and coverage;
- top-N ranking: precision@K, recall@K, MAP@K or NDCG@K, hit rate, and coverage;
- system quality: catalog coverage, novelty/diversity where defined, inference
  resource measurements, and cold-start segments.

Compare every candidate to a documented baseline. Metrics are reported overall
and for important segments. Acceptance thresholds are configuration-driven and
versioned.

## MLflow Tracking

Each training run logs:

- model and pipeline parameters;
- metrics with unambiguous names and units;
- tags for batch, pipeline run, dataset, feature set, code, and environment;
- split and quality summaries;
- model, transformer, signature, input example, and evaluation artifacts;
- report and S3 asset references.

MLflow tracking failures are explicit failures of the model stage. Logging is
performed through an internal tracking adapter so unit tests do not require a
live server.

## Model Packaging

A model package includes the estimator, fitted preprocessing, input/output
signature, supported feature definition versions, training summary, evaluation
results, dependency metadata, and checksum. Loading must validate compatibility
and must not execute artifacts from untrusted origins.

## Registration and Promotion

Only models that pass configured quality and integrity gates are eligible for
registration. Promotion requires:

1. successful pipeline and feature-quality status;
2. complete metrics and artifacts;
3. improvement or justified tradeoff against the active baseline;
4. reproducibility metadata;
5. an auditable approval record when required.

Promotion uses model aliases or lifecycle states rather than overwriting a
model. Rollback points an alias to a previously approved immutable version.

## Failure Handling

Invalid features, insufficient split coverage, non-finite metrics, serialization
failure, MLflow unavailability, and threshold failure produce distinct errors.
Failed training runs preserve sanitized diagnostics but cannot be promoted.

## Testing

Unit tests cover split logic, feature selection, metric calculations, baseline
comparison, serialization, and failure classification. Small deterministic
datasets are used. Integration tests verify MLflow logging and artifact
round-tripping. Model-quality tests use tolerances rather than brittle exact
floating-point equality.
