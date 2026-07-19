# Project Structure and Responsibilities

## Purpose

This document defines the canonical repository layout. New files must be placed
according to responsibility, not convenience. Packages may depend on shared
interfaces and utilities, but business domains must remain independently
testable.

## Canonical Layout

```text
recomart-mlops/
├── configs/                 # Non-secret YAML configuration
├── dags/                    # Thin Airflow DAG definitions
├── data/                    # Local development data, normally ignored
├── docs/                    # Architecture and engineering standards
├── logs/                    # Local runtime logs, never source-controlled
├── mlruns/                  # Local MLflow state, never source-controlled
├── notebooks/               # Exploration only; not production execution
├── reports/                 # Generated local reports, not business logic
├── sample_data/             # Small, non-sensitive deterministic fixtures
├── scripts/                 # Operational entry points and bootstrap utilities
├── sql/                     # Versioned DDL and explicit SQL assets
├── src/                     # Application and pipeline business logic
├── tests/                   # Automated tests mirroring src responsibilities
├── .env.example             # Secret variable names with safe example values
├── .gitignore
├── README.md
└── requirements.txt
```

## `src/` Organization

The preferred package layout is:

```text
src/
├── api/                     # FastAPI routes, schemas, dependencies
├── batch/                   # Synthetic batch generation
├── ingestion/               # Incoming discovery and raw ingestion
├── validation/              # Schema and business-rule checks
├── preparation/             # Cleaning and canonical transformations
├── features/                # Feature definitions and materialization
├── feature_store/           # Feature persistence and retrieval
├── lineage/                 # Lineage event creation and persistence
├── modeling/                # Training, evaluation, and model packaging
├── reporting/               # Report models, rendering, and publication
├── storage/                 # S3-compatible storage adapters
├── database/                # PostgreSQL repositories and transactions
├── tracking/                # MLflow adapter
├── config/                  # Typed configuration loading and validation
└── common/                  # Truly cross-cutting logging, errors, IDs, time
```

Each directory is a Python package. Public interfaces belong in clearly named
modules; package initializers must not perform network access or other side
effects.

## Folder Responsibilities

### `configs/`

Contains version-controlled YAML for environments, data contracts, feature
definitions, quality thresholds, and model settings. YAML must never contain
passwords, access keys, secret tokens, or private endpoints containing
credentials. Environment-specific files override a documented base configuration.

### `dags/`

Contains only DAG construction, scheduling, task dependency wiring, retry policy,
and calls into `src/`. DAG parsing must not perform S3, database, MLflow, or
dataset operations.

### `data/`, `logs/`, `mlruns/`, and `reports/`

These are runtime work areas for local development. Generated artifacts must not
be treated as source. Only intentional examples, templates, or `.gitkeep` files
may be committed.

### `notebooks/`

Supports investigation and visualization. A notebook may consume published data
but must not become a production dependency. Reusable logic discovered in a
notebook must be moved into `src/` with tests.

### `sample_data/`

Contains small, deterministic, legally redistributable fixtures. Files must be
documented and must not contain credentials, personal information, or complete
large upstream datasets.

### `scripts/`

Contains small operational wrappers such as database initialization, local
bootstrap, or backfill entry points. Scripts call public application services;
they do not duplicate business logic.

### `sql/`

Contains ordered, versioned schema migrations or DDL assets. Destructive
operations must be explicit and reviewed. Runtime query construction belongs in
database repositories, using parameterized queries.

### `tests/`

Mirrors `src/` domains. Unit tests are isolated from networks. Integration tests
use disposable services or dedicated test resources. End-to-end tests validate
the complete layer sequence using small data.

## Dependency Direction

Domain logic depends on internal protocols and value objects. Infrastructure
adapters implement those protocols:

`API/DAG/scripts → application services → domain logic → interfaces ← adapters`

`common/` must not depend on business packages. Domain modules must not import
FastAPI or Airflow. Storage, database, and tracking adapters must not decide
business rules.

Circular imports are prohibited. If two packages need each other, extract a
small stable contract rather than combining responsibilities.

## Naming

- Files and packages: `snake_case`.
- Classes and exceptions: `PascalCase`.
- Functions, variables, and configuration keys: `snake_case`.
- Constants: `UPPER_SNAKE_CASE`.
- Tests: `test_<unit>_<behavior>.py`.
- SQL migrations: ordered prefix plus descriptive name.
- S3 object keys: lowercase stable prefixes and partition components.

Ambiguous names such as `utils.py`, `helpers.py`, `manager.py`, or `misc.py`
should be avoided. Name modules after their exact responsibility.

## Adding a New Capability

1. Identify the owning domain and its input/output contract.
2. Add configuration without secrets.
3. Implement logic in `src/` behind narrow interfaces.
4. Add infrastructure adapters only where required.
5. Add unit tests and relevant integration tests.
6. Wire the service into the API, DAG, or script.
7. Update architecture, schema, and operational documentation when contracts change.

No production business logic may be introduced exclusively in a DAG, notebook,
route handler, SQL file, or shell script.
