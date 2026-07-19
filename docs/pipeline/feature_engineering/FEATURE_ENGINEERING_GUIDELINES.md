# Feature Engineering and Feature Store

## Purpose

Feature engineering converts prepared MovieLens entities into reproducible,
versioned inputs for recommendation models. Features must be leakage-safe,
documented, testable, and linked to their exact source assets.

## Feature Domains

### User Features

Examples include rating count, mean and variance of ratings, activity recency,
activity span, preferred genre distribution, and positive-feedback ratio.

### Item Features

Examples include rating count, mean rating, rating dispersion, popularity,
recency-adjusted popularity, release year or age, and multi-hot genre indicators.

### Interaction Features

Examples include user/item activity at interaction time, deviation from user
mean, deviation from item mean, temporal context, and selected cross features.
Interaction features must respect event-time ordering.

### Content Features

Movie titles, years, and genres may produce encoded content features. Any fitted
vocabulary or encoder is a versioned training artifact.

## Feature Definition Contract

Every feature definition declares:

- stable feature name and human-readable description;
- owning entity and join keys;
- logical and physical data type;
- source prepared assets and required columns;
- transformation reference and parameters;
- event-time/as-of semantics;
- null/default policy and valid range;
- definition version and owner;
- leakage and freshness considerations.

Changing meaning, inputs, or calculation requires a new definition version.
Compatible metadata-only corrections may use a documented patch version.

## Time Semantics and Leakage Prevention

The pipeline establishes chronological training, validation, and test cutoffs
before fitting stateful transformations. A feature for an interaction at time
`t` may use only information available at or before the configured cutoff for
that example. Aggregations must not include future ratings.

Random splits are allowed only for explicitly justified experiments and must be
labeled as such. Evaluation intended to resemble deployment should use temporal
splits.

## Transformation Rules

- Fit encoders, scalers, imputers, and vocabularies on training data only.
- Apply the fitted transformer unchanged to validation and test data.
- Use deterministic ordering and random seeds.
- Define behavior for unseen users, unseen items, genres, and categories.
- Avoid high-cardinality dense encodings that create uncontrolled memory use.
- Retain entity keys and timestamps separately from numeric model matrices.
- Reconcile row counts before and after joins.

## Feature Store Layout

Offline feature data is stored in the S3 features zone using Parquet. A
materialization includes entity keys, optional event time, feature columns,
definition set version, as-of time, and producer metadata.

PostgreSQL registers definitions and materializations. It stores the S3 asset
reference, source asset IDs, code/config versions, schema, record count,
checksum, and state. The database does not store the full feature matrix.

## Materialization

Materialization is idempotent for a combination of source checksums, definition
versions, as-of time, configuration version, and code version. Outputs are
written and committed atomically. A successful materialization is immutable.

Feature selection for a model is an explicit feature set. Training must not
select columns by an uncontrolled wildcard that might silently include IDs,
labels, or future features.

## Quality Checks

Feature validation covers:

- schema and data type;
- entity key uniqueness at the declared grain;
- null, infinite, and invalid-value ratios;
- expected numeric ranges and categorical domains;
- row-count and join coverage;
- distribution summaries and drift against a configured reference;
- timestamp and point-in-time correctness;
- sparsity, dimensionality, and constant columns.

Threshold violations are stored as quality results and may block training.

## Cold Start

User and item cold-start behavior is explicitly supported. Possible strategies
include global priors, popularity features, content features, and an `unknown`
category. Evaluation reports must segment known-user/item and cold-start
performance rather than hiding them in an aggregate metric.

## Testing

Unit tests use small prepared datasets with known expected feature values,
including boundary timestamps, duplicates, missing categories, and unseen
entities. Property checks should verify determinism, no future-data access, key
uniqueness, and stable schema. Integration tests verify feature-store
publication and metadata registration.
