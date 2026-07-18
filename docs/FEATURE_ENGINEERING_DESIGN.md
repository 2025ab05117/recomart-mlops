# RecoMart Feature Engineering Design

## Architecture and Inputs

The feature layer reads only Parquet paths declared by an eligible
`preparation_manifest.json`. `loader.py` resolves lineage; `features.py`
computes deterministic feature groups; `catalog.py` creates definitions and
lineage; `storage.py` persists one SQLAlchemy transaction; `runner.py`
coordinates optional immutable Parquet snapshots and reports.

Static attributes come from `users_prepared` and `products_prepared`.
Behavioral calculations use `train.parquet` by default. Selecting `all` is
explicitly leakage-prone and intended only for exploration.

## Reference Time and Leakage Prevention

`feature_reference_timestamp` is the maximum timestamp in the selected source
split. Events are filtered to `event_timestamp <= reference`. Training mode
never reads validation or test events for user, item, pair, co-occurrence, or
similarity aggregates. Explicit ratings and implicit weights remain separate.
Absent interactions are not negative ratings and are never materialized.

## Feature Logic

User features cover lifetime/windowed activity, product/session diversity,
ratings, commerce, recency, tenure, preferences, conversions, quantile activity
level, and cold start. Item features cover activity, unique users, explicit
ratings, commerce, separate popularity measures, windows/growth, catalog
attributes, ranks, long tail, and cold start. User-item features contain
observed-pair counts, implicit/explicit feedback, temporal history, affinities,
and price preference.

Sparse binary user-item multiplication creates canonical co-occurrence pairs
without a Cartesian product. Support, directional confidence, and lift use
distinct active users. Same-session and co-purchase counts are separate.

Sparse weighted item-user vectors feed brute-force cosine nearest neighbors.
Jaccard uses user-set overlap. Content similarity covers category, brand,
normalized price distance, and rating distance. Configured weights combine the
six measures and retain top-K non-self neighbors.

## Nulls, Windows, and Persistence

Counts/spend default to zero. Missing ratings remain null. Ratios with a zero
denominator and recency without a prior purchase remain null. Windows of 1, 7,
and 30 days end at the reference timestamp.

PostgreSQL is primary; SQLite uses unqualified table names for local/test use.
Feature groups, batch metadata, definitions, and lineage are committed in one
transaction. Parquet snapshots support recovery and reproducibility.

## Idempotency

Identity combines source batch, source split, configuration SHA-256, feature
version, and prepared input checksums. A matching successful batch returns
`IDEMPOTENT_SUCCESS`. Reusing a feature batch ID with different identity fails.

