# Mandatory Project Rules

## Authority

The files under `docs/` are the single source of truth for RecoMart architecture
and implementation. When code and documentation conflict, stop, resolve the
design decision, update the appropriate documentation, and then change code.

## Non-Negotiable Rules

1. Use Python 3.12.
2. Follow the data sequence `Incoming → Raw → Validated → Prepared → Features
   → Models → Reports`.
3. Do not skip, overwrite, or mutate a committed data layer.
4. Use Airflow only for orchestration.
5. Keep business logic in focused packages under `src/`.
6. Read behavioral configuration from validated YAML.
7. Read secrets from environment variables or an approved secret manager.
8. Never hardcode credentials, bucket names, database connection details,
   MLflow endpoints, or machine-specific absolute paths.
9. Use structured logging; do not use `print()` in application code.
10. Validate inputs and raise meaningful, classified exceptions.
11. Handle and surface S3, PostgreSQL, and MLflow failures.
12. Use Python type hints throughout.
13. Document every public class, method, function, exception, and API.
14. Prefer absolute imports.
15. Keep packages single-purpose and avoid duplicated code.
16. Make stages idempotent, deterministic where possible, and independently testable.
17. Record lineage for every published asset.
18. Never log or commit secrets.
19. Use parameterized SQL and least-privilege access.
20. Add or update tests for every behavior change.

## Layer Enforcement

- Incoming data may be read only by ingestion.
- Raw data may be read by validation and lineage/reconciliation tooling.
- Validated data may be read by preparation.
- Prepared data may be read by feature engineering.
- Feature materializations may be read by training.
- Model artifacts and registered metrics may be read by reporting.

Observability and lineage components may inspect metadata across layers, but
must not introduce an alternate transformation path.

## Change Management

Changes to schemas, feature meanings, configuration contracts, database
structures, object-key conventions, or public interfaces require:

- explicit versioning and compatibility assessment;
- migration or reprocessing plan when applicable;
- tests covering old/new boundaries as required;
- documentation updates in the same change;
- no silent reinterpretation of an existing immutable version.

## Prohibited Practices

- Business transformations inside DAG files, route handlers, notebooks, or scripts.
- Broad exception handling that suppresses failure.
- Unbounded object-store listings or diagnostic samples.
- Passing DataFrames, datasets, models, or secrets through Airflow XCom.
- Inferring production schemas from CSV on every run.
- Editing committed S3 objects in place.
- Training directly from incoming, raw, validated, or prepared data.
- Fitting preprocessors on validation or test data.
- Checking generated logs, MLflow state, large datasets, or credentials into Git.
- Creating a shared “God class” that coordinates unrelated domains.
- Mocking the unit under test instead of its external dependencies.

## Operational Rules

All timestamps are UTC internally. Every run uses stable identifiers. External
calls have timeouts. Retries are bounded and restricted to transient,
idempotent operations. Partial outputs remain uncommitted. Terminal status and
failure reason are recorded. Reprocessing creates new versions.

## Security Rules

Apply least privilege to S3 and PostgreSQL. Use TLS where supported. Sanitize
untrusted filenames, keys, tags, and report content. Do not deserialize
untrusted model artifacts. Redact sensitive values from logs and error
responses. `.env.example` documents variable names only and contains no real
secrets.

## Quality Gate

A change may be accepted only when:

- it respects package and layer boundaries;
- configuration and secret handling comply with policy;
- public interfaces are documented and typed;
- logs and errors provide actionable context;
- unit tests pass and relevant integration tests are present;
- data reconciliation and lineage are preserved;
- documentation matches the implemented behavior.

## Decision Priority

When requirements compete, prioritize:

1. data integrity and security;
2. correctness and reproducibility;
3. clear failure and auditability;
4. maintainability and testability;
5. performance supported by measurement;
6. convenience.
