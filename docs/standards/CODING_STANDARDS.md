# Coding Standards

## Scope

These rules apply to all Python code, tests, DAGs, and operational scripts in
RecoMart. Python 3.12 is the supported runtime.

## General Style

- Follow PEP 8 and use automated formatting and linting consistently.
- Prefer clear, small functions and focused classes.
- Use absolute imports from the project package.
- Avoid duplicated logic and premature generic abstractions.
- Avoid module import side effects.
- Use context managers for files, database resources, and temporary resources.
- Do not use `print()` in application code; use structured logging.

## Type Hints

All function and method parameters and return values are typed. Public
attributes and complex local values should be typed when inference is unclear.
Use precise collection and protocol types. Avoid `Any` unless isolating an
untyped third-party boundary, and document the reason.

DataFrame boundaries require an accompanying schema or documented column
contract; `DataFrame` alone is not an adequate data contract.

## Documentation

Every public module, class, method, function, API endpoint, configuration model,
and exception has a concise docstring. Docstrings state purpose, important
arguments, return value, raised exceptions, side effects, and relevant
idempotency behavior. Comments explain why, constraints, or non-obvious tradeoffs
rather than restating code.

## Naming

- Packages, modules, functions, and variables: `snake_case`.
- Classes, protocols, and exceptions: `PascalCase`.
- Constants: `UPPER_SNAKE_CASE`.
- Boolean values begin with `is_`, `has_`, `can_`, or another clear predicate.
- Units appear in names where ambiguity exists, such as `timeout_seconds`.

Names must express domain meaning. Avoid `data`, `result`, `manager`, or
`processor` when a more specific term is available.

## Functions and Classes

A function performs one coherent operation. A class has one reason to change.
Dependencies are injected through constructors or explicit parameters.
Infrastructure clients must not be created inside domain transformations.
Prefer composition to inheritance and immutable value objects for identifiers
and contracts.

## Configuration and Secrets

Behavioral configuration is read from version-controlled YAML and validated at
startup. Secrets and sensitive connection values are read from environment
variables or a secret manager. Code must not hardcode:

- bucket names or environment-specific prefixes;
- database names, users, passwords, or hosts;
- S3 access keys;
- MLflow credentials or tracking endpoints;
- absolute developer-machine paths.

Missing or invalid required configuration fails fast with a meaningful error.

## Structured Logging

Each module obtains a named logger. Log records are machine-parseable and use
stable event names. Include identifiers such as `correlation_id`, `batch_id`,
`run_id`, stage, asset ID, and duration where relevant.

- `DEBUG`: detailed diagnostic context without sensitive data.
- `INFO`: lifecycle events and successful milestones.
- `WARNING`: recoverable anomalies, retries, or threshold concerns.
- `ERROR`: failed operations requiring intervention or task failure.

Never log secrets, connection strings, full environment dumps, or unbounded row
content. Log an exception once at the boundary responsible for handling or
terminating it.

## Error Handling

Validate inputs at system boundaries. Raise domain-specific exceptions with
actionable messages. Preserve exception chaining. Never silently ignore an
exception or use a broad catch without classification and an explicit outcome.

Distinguish validation failures, configuration errors, storage errors, database
errors, tracking errors, integrity conflicts, and transient dependency errors.
Only retry operations known to be safe and transient.

## Data Processing

- Declare schemas and avoid uncontrolled type inference downstream of incoming.
- Use vectorized Pandas operations where clear and efficient.
- Avoid row-wise mutation for large datasets.
- Make ordering explicit before order-dependent logic.
- Set random seeds and record them.
- Normalize timestamps to UTC.
- Never mutate an upstream persisted dataset in place.
- Reconcile input, accepted, rejected, and output record counts.

## API Standards

FastAPI routes validate request and response models, use explicit status codes,
and delegate to services. Errors use a consistent response envelope without
internal stack traces. Batch sizes, ranges, and filenames are bounded and
validated. Idempotency and correlation headers are supported where applicable.
Every endpoint is documented in OpenAPI through names, summaries, schemas, and
response descriptions.

## Testing

Every module is independently testable. Unit tests:

- avoid network and shared database dependencies;
- cover success, boundary, invalid-input, and dependency-failure behavior;
- use deterministic seeds and clocks;
- assert outputs and observable side effects;
- do not assert incidental implementation details.

Integration tests verify adapter contracts against disposable PostgreSQL,
S3-compatible storage, and MLflow services. Test fixtures remain small.

## Dependency and Security Rules

Pin or constrain dependencies deliberately and review upgrades. Do not execute
untrusted serialized models or arbitrary user-provided code. Sanitize object
keys and report content. Use parameterized SQL. Temporary files have restrictive
scope and are removed safely.

## Review Checklist

A review confirms correct package ownership, no DAG business logic, type and
documentation completeness, external configuration, safe error handling,
structured logging, idempotency, tests, and updated contracts or documentation.
