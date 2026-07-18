# RecoMart MLOps Project Overview

## Purpose

RecoMart is an enterprise-style data management and machine-learning pipeline for
recommendation systems. It ingests MovieLens data, preserves immutable source
records, validates and prepares datasets, builds reusable recommendation
features, trains models, records experiments, and publishes auditable reports.

The repository is an academic project, but its design follows production
principles: separation of concerns, reproducibility, traceability, secure
configuration, automated testing, observable execution, and recoverable data
processing.

## Objectives

- Provide a FastAPI service that creates controlled synthetic data batches.
- Store every batch in an S3-compatible data lake.
- Use Apache Airflow solely to schedule and orchestrate processing.
- Keep business logic in independently testable modules under `src/`.
- Validate data contracts before allowing data into downstream layers.
- Produce deterministic prepared datasets and features.
- Maintain a feature store with point-in-time and version metadata.
- Capture end-to-end lineage for data, features, models, and reports.
- Train and evaluate recommendation models reproducibly.
- Track parameters, metrics, artifacts, and model versions in MLflow.
- Generate human-readable data-quality and model-performance reports.

## Technology Stack

| Concern | Technology |
|---|---|
| Language | Python 3.12 |
| Batch API | FastAPI |
| Orchestration | Apache Airflow |
| Operational metadata | PostgreSQL |
| Object storage | AWS S3 or MinIO |
| Data processing | Pandas and PyArrow |
| Modeling | Scikit-Learn |
| Experiment tracking | MLflow |
| Source dataset | MovieLens |

AWS S3 and MinIO are interchangeable through the S3 protocol. Application code
must depend on an internal storage abstraction rather than provider-specific
behavior.

## System Scope

The canonical processing path is:

`MovieLens → FastAPI Generator → S3 Incoming → Airflow → Raw → Validation → Prepared → Feature Engineering → Feature Store → Lineage → Model Training → MLflow → Reports`

Every persisted dataset must move through the layers in this order. A component
must not read an earlier layer and publish directly to a later layer.

### In Scope

- Movie, rating, user, and related MovieLens records.
- Synthetic batch creation without changing the source meaning.
- Batch ingestion, schema and business-rule validation.
- Data preparation and recommendation-oriented feature engineering.
- Offline model training and evaluation.
- Dataset, feature, model, and report lineage.
- Operational metadata and run status.

### Out of Scope

- Real-time recommendation serving.
- Customer identity or production personal data.
- Online feature serving.
- Payment, catalog, or order management.
- Uncontrolled training from local ad hoc files.

## Design Principles

1. **Layered data ownership:** each data-lake layer has a precise contract.
2. **Thin orchestration:** DAGs connect tasks; they do not implement business logic.
3. **Immutable inputs:** incoming and raw objects are never edited in place.
4. **Idempotency:** retrying a run with the same identifiers has the same outcome.
5. **Configuration over constants:** YAML defines behavior; environment variables
   provide secrets.
6. **Traceability:** every artifact is linked to its source batch and producing run.
7. **Fail clearly:** errors are logged with context and raised as meaningful
   exceptions.
8. **Testability:** infrastructure is accessed through injected interfaces.
9. **Least privilege:** services receive only the permissions they need.
10. **Reproducibility:** code, configuration, data, and model versions are recorded.

## Key Identifiers

- `batch_id`: globally unique identifier assigned when a batch is generated.
- `run_id`: identifier for one pipeline execution.
- `dataset_version`: immutable version of a published dataset.
- `feature_set_version`: immutable definition and materialization version.
- `model_version`: model registry version or immutable local equivalent.
- `correlation_id`: request-to-pipeline tracing identifier.

Identifiers must be present in structured logs and metadata records whenever
applicable. UTC timestamps use ISO 8601 with a `Z` suffix.

## Quality Attributes

- **Reliability:** retries are safe, partial publications are not visible, and
  failed runs preserve diagnostic evidence.
- **Maintainability:** packages have one responsibility and public interfaces are
  documented and typed.
- **Security:** credentials never appear in code, YAML, logs, or artifacts.
- **Auditability:** lineage and checksums establish what was processed and produced.
- **Portability:** local MinIO/PostgreSQL/MLflow and cloud equivalents use the same
  contracts.
- **Scalability:** interfaces permit replacing local Pandas processing when data
  volume outgrows a single machine.

## Definition of Done

A change is complete when its behavior is documented, typed, logged, tested,
configuration-driven, and compatible with the layer contracts. Relevant unit
tests and integration tests pass, failure modes are covered, and no secrets or
machine-specific paths are introduced.
