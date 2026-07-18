# RecoMart Coding Instructions

## Required Preparation

Before generating or modifying code:

1. Read every Markdown document in `docs/`.
2. Inspect the existing repository structure and nearby implementation.
3. Identify the owning module, data layer, and public contract.
4. Confirm that the requested behavior does not bypass the canonical data flow.
5. Preserve unrelated existing work.

The documentation is the single source of truth. If a request conflicts with it,
state the conflict and resolve the specification before implementing.

## Project Mission

Build an enterprise-grade recommendation-system data management pipeline using
MovieLens, FastAPI, Apache Airflow, PostgreSQL, S3 or MinIO, Pandas, PyArrow,
Scikit-Learn, and MLflow on Python 3.12.

The canonical architecture is:

`MovieLens → FastAPI Generator → S3 Incoming → Airflow → Raw → Validation → Prepared → Feature Engineering → Feature Store → Lineage → Model Training → MLflow → Reports`

## Implementation Boundaries

- FastAPI handles HTTP validation and delegates batch generation.
- Airflow handles scheduling, dependencies, retries, and task execution only.
- Business logic belongs under `src/`.
- Infrastructure access is isolated behind storage, database, and tracking adapters.
- PostgreSQL stores operational metadata and lineage, not bulk datasets.
- S3-compatible storage holds immutable datasets and artifacts.
- Notebooks are exploratory and are never production dependencies.
- Scripts call public services and do not duplicate logic.

## Data-Layer Rules

The only permitted processing progression is:

`Incoming → Raw → Validated → Prepared → Features → Models → Reports`

Do not read across layers as a shortcut. Raw preserves source truth. Validation
publishes accepted data and explicit rejects. Prepared data is canonical.
Features are registered and versioned. Models consume only feature
materializations. Reports reference registered source artifacts.

Every publication is immutable, idempotent, checksum-verified, and linked by
lineage to its inputs and producing run.

## Configuration

- Read non-secret behavior from validated YAML under `configs/`.
- Read secrets from environment variables or an approved secret manager.
- Provide safe variable names and descriptions in `.env.example`.
- Never hardcode bucket names, access keys, database credentials, endpoints, or
  absolute local paths.
- Fail fast on missing or invalid required settings.

## Python Standards

- Target Python 3.12 and follow PEP 8.
- Use absolute imports and precise type hints everywhere.
- Add docstrings to every public module, class, method, function, exception, and API.
- Keep functions small and classes focused.
- Prefer dependency injection and narrow protocols.
- Avoid circular dependencies, import-time side effects, and ambiguous utility modules.
- Use deterministic transformations and explicit random seeds.
- Declare DataFrame schemas and column contracts.

## Logging and Errors

Use structured logging in every module and never use `print()` for application
events. Include relevant correlation, batch, run, stage, and asset identifiers.
Never log credentials, full connection strings, or unbounded data.

Validate all external inputs. Raise meaningful application exceptions and
preserve causes. Classify configuration, validation, storage, database,
tracking, integrity, and transient failures. Never silently ignore exceptions.
Retry only bounded, transient, idempotent operations.

## API Requirements

FastAPI endpoints use typed request/response models, explicit status codes,
bounded parameters, consistent error responses, and complete OpenAPI
documentation. Route functions remain thin. Batch creation supports traceable
identifiers and idempotent submission.

## Airflow Requirements

DAG files define schedules, task wiring, execution policy, and calls to `src/`.
They do not contain transformations, validation logic, feature engineering,
model fitting, or report computation. DAG imports perform no network or dataset
operations. XCom carries only small identifiers and summaries.

## Storage and Database Requirements

Use logical S3 zones resolved from configuration. Write data to temporary
run-scoped locations, verify it, then publish a manifest and commit marker.
Never overwrite committed objects.

Use repository interfaces and parameterized SQL. Keep database transactions
short and do not hold them open during remote calls. Register an asset only
after successful object publication. Handle cross-system consistency with
idempotency, immutable objects, and reconciliation.

## Feature and Modeling Requirements

Feature definitions declare entity keys, types, sources, time semantics,
defaults, and versions. Prevent temporal leakage, fit transformations only on
training data, and define cold-start behavior.

Training uses registered feature materializations, explicit splits, recorded
seeds, baseline comparisons, and appropriate recommendation metrics. MLflow logs
parameters, metrics, tags, signatures, datasets, and artifacts. Tracking
failures are surfaced. Only models passing configured gates may be registered or
promoted.

## Testing Requirements

Each module must be independently testable. Add deterministic unit tests for
success, boundaries, invalid inputs, and dependency failures. Mock interfaces,
not business behavior. Add adapter integration tests for PostgreSQL, S3/MinIO,
and MLflow, plus a small end-to-end test for the complete layer sequence.

Tests must not depend on production credentials, external shared state,
execution order, or large datasets.

## Documentation and Change Rules

Update documentation with any architecture, schema, configuration, public
interface, feature-definition, or operational change. Breaking contracts require
versioning and a migration or reprocessing plan.

When generating code:

- follow the existing project structure;
- modify only the intended module and directly related tests/configuration;
- explain assumptions and consequential design choices;
- avoid placeholders, unfinished branches, and fabricated integrations;
- do not generate files outside the requested scope;
- verify the result with proportionate automated checks.

## Completion Checklist

Before declaring work complete, confirm:

- correct folder and single responsibility;
- no layer bypass or DAG business logic;
- configuration externalized and secrets protected;
- public interfaces typed and documented;
- structured logs and meaningful errors included;
- S3/PostgreSQL/MLflow failures handled;
- behavior idempotent and lineage-aware;
- tests added and passing;
- relevant documentation updated;
- no credentials, generated runtime state, or machine-specific paths introduced.
