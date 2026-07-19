# RecoMart Pipeline Documentation

The pipeline advances through these ordered stages:

```text
Generation
    ↓
Ingestion
    ↓
Validation
    ↓
Preparation
    ↓
Feature Engineering
    ↓
Feature Store
    ↓
Versioning and Lineage
    ↓
Model Training
    ↓
Airflow Orchestration
```

## Stage Documentation

1. [Ingestion](ingestion/README.md)
2. [Validation](validation/README.md)
3. [Preparation](preparation/README.md)
4. [Feature Engineering and Store](feature_engineering/README.md)
5. [Versioning and Lineage](versioning/README.md)
6. [Model Training and MLflow](modeling/README.md)
7. [Airflow Orchestration](orchestration/README.md)

Airflow only orchestrates. Business logic remains under `src/`. Stage manifests
are durable contracts between tasks; batch and run identifiers maintain
traceability. DVC versions data, model, and report artifacts. MLflow tracks
model experiments, metrics, and trained-model artifacts.

The generator is documented by the system architecture and its implementation
contract because it has no separate stage-document set.

[Back to Documentation Home](../README.md)
