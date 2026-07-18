# Data Flow and Processing Contracts

## Purpose

This document defines how data advances through RecoMart. The layer order is
mandatory:

`Incoming → Raw → Validated → Prepared → Features → Models → Reports`

Feature-store registration, lineage, and MLflow tracking occur at their relevant
transitions and never bypass the persisted layers.

## Source Entities

The initial MovieLens domains are:

- **ratings:** user, movie, rating value, and event timestamp;
- **movies:** movie identifier, title, year when derivable, and genres;
- **tags:** optional user-generated movie tags and timestamps;
- **links:** optional mappings to external movie identifiers.

An enabled dataset edition determines which entities are required. Source
identity and original values must remain recoverable from the raw layer.

## Batch Manifest

Every batch has a machine-readable manifest containing:

- manifest and schema version;
- `batch_id` and `correlation_id`;
- source name and dataset edition;
- creation timestamp in UTC;
- entity file list and media format;
- record count, byte size, and SHA-256 checksum per file;
- generator parameters and random seed, if synthesis is used;
- expected partition values;
- optional parent/source dataset checksum.

The manifest is committed last. A batch without a valid committed manifest is
incomplete and must not be processed.

## Layer Contracts

### Incoming

Contains exactly what the generator submitted. The layer is append-only and may
contain malformed business data, but payload checksums and manifest structure
must be readable. Objects are not consumed by deleting or moving them.

### Raw

Contains an immutable normalized serialization of the accepted incoming
payload. Ingestion adds operational columns such as `batch_id`,
`ingested_at_utc`, `source_object_uri`, and `source_row_number`. It must not
clean, deduplicate, impute, or discard source records.

### Validated

Contains records that satisfy the declared schema and validation rules.
Rejected records are written to quarantine with reason codes and source
references. A configurable threshold decides whether a batch passes, fails, or
is quarantined. Validation results are always persisted.

### Prepared

Contains canonical analytical tables. Preparation applies documented type
normalization, null handling, deduplication, title/year parsing, genre
normalization, and integrity enforcement. Transformations are deterministic and
record counts are reconciled against validated input.

### Features

Contains versioned user, item, interaction, and context features. Features are
generated only from prepared data using a registered definition and a declared
as-of time. Train/validation/test boundaries are established before fitting
stateful transformations.

### Models

Contains immutable serialized model artifacts, training summaries, signatures,
dependency metadata, and references to MLflow runs. Models consume only
registered feature materializations.

### Reports

Contains data-quality, pipeline, and model-evaluation reports. Every report
references the producing run and source assets. Reports never become implicit
inputs to a processing stage.

## Stage Transitions

| Transition | Required checks | Primary output |
|---|---|---|
| Incoming → Raw | manifest, checksum, format, idempotency | raw Parquet and asset metadata |
| Raw → Validated | schema, domains, keys, integrity, thresholds | valid data, rejects, quality result |
| Validated → Prepared | canonicalization and reconciliation | prepared entity tables |
| Prepared → Features | definition version, leakage controls | feature materializations |
| Features → Models | split validity and reproducibility inputs | model and evaluation artifacts |
| Models → Reports | artifact and metric completeness | versioned reports |

## Validation Rules

At minimum, validation checks:

- required columns and compatible physical types;
- non-null primary/entity identifiers;
- rating values within the configured range;
- parseable, plausible timestamps;
- unique keys where the contract requires uniqueness;
- referential integrity from ratings/tags/links to movies and users;
- duplicate rows and conflicting duplicates;
- allowed genre representation;
- file and record-count consistency with the manifest;
- freshness and volume thresholds.

Rules have stable identifiers, severity, description, observed value, expected
condition, affected count, and bounded samples. Samples must not expose secrets
or excessive user-level data.

## Preparation Rules

Preparation must be documented and deterministic. Duplicate resolution uses a
declared key and tie-break rule. Missing values use explicit policies—reject,
preserve, impute, or label—and never silent coercion. Time is normalized to UTC.
Categorical normalization preserves an `unknown` representation when required.

## Idempotency and Atomic Publication

A stage idempotency key is derived from the stage name, input checksums,
configuration version, and code version. Output is first written to a temporary
or run-scoped prefix, verified, then made visible through a success/commit
marker and metadata transaction.

Existing output with the same key and checksums is reused. Existing output with
different checksums is a conflict and must fail.

## Lineage

Each successful transition records:

- input and output asset identifiers and URIs;
- batch, pipeline run, and task identifiers;
- code and configuration version;
- schema/feature definition version;
- start and completion timestamps;
- record counts and checksums;
- transformation name and status.

Rejected data is linked to both its raw input and validation result.

## Backfills and Reprocessing

Backfills use a new `run_id`, an explicit date or batch range, and pinned
configuration. They do not mutate historical assets. Reprocessing creates a new
dataset version and lineage branch. Promotion of reprocessed outputs requires
the same validation gates as routine processing.
