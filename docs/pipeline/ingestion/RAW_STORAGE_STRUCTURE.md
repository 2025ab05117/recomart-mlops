# Raw Storage Structure

## Purpose

The raw layer is the immutable, source-preserving record of accepted ingestion
payloads. It retains CSV and JSON formats exactly as collected. Conversion to
Parquet and business preparation belong to later pipeline stages.

## Canonical Relative Layout

Every data object uses:

```text
<source>/<dataset_type>/
ingestion_date=<YYYY-MM-DD>/
ingestion_hour=<HH>/
batch_id=<batch-id>/
<source-filename>
```

The manifest omits dataset type:

```text
manifests/
ingestion_date=<YYYY-MM-DD>/
ingestion_hour=<HH>/
batch_id=<batch-id>/
ingestion_manifest.json
```

All partition timestamps use UTC.

## Local Filesystem

With the default `data/raw` root:

```text
data/raw/
├── file/
│   ├── users/
│   │   └── ingestion_date=2026-07-19/
│   │       └── ingestion_hour=01/
│   │           └── batch_id=RECO_20260719_010203_ab12cd/
│   │               └── users.csv
│   ├── products/.../products.json
│   ├── clickstream/.../clickstream.csv
│   └── purchasehistory/.../purchasehistory.csv
├── api/
│   └── popularity/
│       └── ingestion_date=2026-07-19/
│           └── ingestion_hour=01/
│               └── batch_id=RECO_20260719_010203_ab12cd/
│                   └── popularity.json
└── manifests/
    └── ingestion_date=2026-07-19/
        └── ingestion_hour=01/
            └── batch_id=RECO_20260719_010203_ab12cd/
                └── ingestion_manifest.json
```

## S3-Compatible Object Keys

With bucket `recomart-data` and prefix `raw`:

```text
s3://recomart-data/raw/file/users/ingestion_date=2026-07-19/ingestion_hour=01/batch_id=RECO_20260719_010203_ab12cd/users.csv
s3://recomart-data/raw/file/products/ingestion_date=2026-07-19/ingestion_hour=01/batch_id=RECO_20260719_010203_ab12cd/products.json
s3://recomart-data/raw/file/clickstream/ingestion_date=2026-07-19/ingestion_hour=01/batch_id=RECO_20260719_010203_ab12cd/clickstream.csv
s3://recomart-data/raw/file/purchasehistory/ingestion_date=2026-07-19/ingestion_hour=01/batch_id=RECO_20260719_010203_ab12cd/purchasehistory.csv
s3://recomart-data/raw/api/popularity/ingestion_date=2026-07-19/ingestion_hour=01/batch_id=RECO_20260719_010203_ab12cd/popularity.json
s3://recomart-data/raw/manifests/ingestion_date=2026-07-19/ingestion_hour=01/batch_id=RECO_20260719_010203_ab12cd/ingestion_manifest.json
```

MinIO uses the same keys. Only endpoint and credential resolution differ.

## Partition Meanings

| Partition | Meaning |
|---|---|
| `source` | Collection channel: `file`, `api`, or `manifests` |
| `dataset_type` | Stable logical dataset name |
| `ingestion_date` | UTC date when the run started |
| `ingestion_hour` | Two-digit UTC hour when the run started |
| `batch_id` | Validated immutable batch identifier |

Run start time determines all partitions for one batch. Files from one run
therefore share date, hour, and batch ID.

## Naming Rules

- Source and dataset names are lowercase stable identifiers.
- Partition labels use lowercase `snake_case`.
- Local and object-store separators are forward slashes in logical paths.
- Batch IDs contain only letters, digits, hyphens, and underscores.
- Filenames are fixed trusted basenames; path traversal components are rejected.
- S3 prefixes are configured without leading or trailing slashes.

## Source Preservation

- `users.csv`, `clickstream.csv`, and `purchasehistory.csv` remain CSV.
- `products.json` and API `popularity.json` remain JSON arrays.
- Ingestion adds no columns and changes no row values.
- SHA-256 proves content identity between source/response and raw output.
- Counts and operational fields live in the manifest rather than source files.

## Immutability

A raw destination is append-only:

- matching destination and checksum: idempotent success;
- matching destination and different checksum: conflict and failure;
- no in-place update, delete, or silent overwrite is permitted.

For S3, SHA-256 is stored as object metadata because an ETag is not a reliable
universal content checksum. Provider versioning and retention are recommended
additional controls but do not replace immutable object keys.

## Runtime Source Control Policy

`data/raw/` is runtime state and is ignored by Git except for an optional
`.gitkeep`. Raw batches, manifests, credentials, and ingestion logs must not be
committed.
