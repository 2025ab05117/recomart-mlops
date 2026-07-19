# RecoMart Documentation

This documentation is the source of truth for RecoMart architecture, engineering
standards, pipeline contracts, and operating procedures.

## Mandatory Reading

Before making any code change:

1. Read [Codex Instructions](instructions/CODEX_INSTRUCTIONS.md).
2. Read [System Architecture](architecture/SYSTEM_ARCHITECTURE.md).
3. Read [Development Guide](standards/DEVELOPMENT_GUIDE.md).
4. Read [Coding Standards](standards/CODING_STANDARDS.md).
5. Read every document in the folder for the pipeline stage being modified.

For cross-cutting changes, also read the relevant architecture and operations
documents. This tiered reading order replaces the former requirement to read
every detailed execution guide for an unrelated change without weakening the
rule that relevant documentation must be read first.

## System Overview

RecoMart is an enterprise-style recommendation data and ML pipeline:

`Generation → Ingestion → Validation → Preparation → Feature Engineering → Feature Store → Versioning and Lineage → Model Training → Airflow Orchestration`

Airflow orchestrates existing application services. Business logic remains in
focused packages under `src/`. Manifests, batch IDs, run IDs, checksums, DVC,
and MLflow preserve traceability and reproducibility.

## Documentation Structure

- [Instructions](instructions/README.md) — mandatory repository and contributor rules.
- [Architecture](architecture/README.md) — system, data-flow, storage, database, and repository design.
- [Standards](standards/README.md) — development, coding, and reporting standards.
- [Pipeline](pipeline/README.md) — stage-specific designs, contracts, and execution guides.
- [Operations](operations/README.md) — cross-stage execution and operational navigation.

Schema documents owned by one pipeline stage remain in that stage folder. This
avoids competing copies under a separate schemas directory.

## Pipeline Stages

1. [Ingestion](pipeline/ingestion/README.md)
2. [Validation](pipeline/validation/README.md)
3. [Preparation](pipeline/preparation/README.md)
4. [Feature Engineering](pipeline/feature_engineering/README.md)
5. [Versioning and Lineage](pipeline/versioning/README.md)
6. [Model Training](pipeline/modeling/README.md)
7. [Airflow Orchestration](pipeline/orchestration/README.md)

## Development Standards

Start with the [Development Guide](standards/DEVELOPMENT_GUIDE.md), then apply
the [Coding Standards](standards/CODING_STANDARDS.md) and
[Project Rules](instructions/PROJECT_RULES.md).

Do not duplicate business logic in DAGs, notebooks, routes, or documentation.
Select one authoritative document and cross-link to it.

## End-to-End Execution

Use the [End-to-End Execution Guide](operations/END_TO_END_EXECUTION_GUIDE.md)
for the ordered local commands and links to detailed stage guides.

## Documentation Maintenance

When implementation, configuration, schemas, public interfaces, or operating
procedures change, update the owning document in the same change. Run:

```powershell
python scripts/validate_docs.py
```

The validator checks local links, required documents, section indexes, stale
pre-migration paths, empty files, and duplicate filenames.
