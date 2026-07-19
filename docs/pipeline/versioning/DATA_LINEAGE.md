# Data Lineage

## End-to-end graph

```text
MovieLens / Generator
          |
          v
 Incoming (incoming-v1.0.0)
          |
          v
 Raw (raw-v1.0.0)
          |
          v
 Validated (validated-v1.0.0)
          |
          v
 Prepared (prepared-v1.0.0) ------> EDA Reports
          |
          v
 Features / Feature Store (features-v1.0.0)
          |
          v
 Models (models-v1.0.0) ----------> Model Reports
          |
          v
 Collaborative MLflow Run
 Content-based MLflow Run
```

The rendered form is `reports/versioning/pipeline_lineage.png`. The
machine-readable graph is `reports/versioning/lineage_report.json`.

## Manifest reuse

The lineage service locates the latest successful artifact through existing
manifests:

| Stage | Authoritative metadata |
|---|---|
| Incoming / Raw | `ingestion_manifest.json` |
| Validated | `validation_manifest.json` |
| Prepared / EDA | `preparation_manifest.json` |
| Features | `feature_manifest.json` |
| Models / model reports | `training_summary.json` and model metadata |
| MLflow | MLflow run metadata embedded in the training summary |

It does not invent replacement row counts, source paths, configuration hashes,
run IDs, or timestamps when the producing manifest already contains them.

## Lineage edge contract

Every transformation edge records:

- `lineage_id`, deterministically derived from parent, child, batch, and
  transformation;
- parent and child semantic versions;
- pipeline stage;
- transformation name;
- batch ID;
- execution completion timestamp;
- manifest path;
- output checksum.

MLflow edges additionally contain the artifact URI. Dataset nodes record batch,
stage, and checksum. The graph must be directed and acyclic.

## Transformations

| Child | Transformation |
|---|---|
| Raw | Immutable file and REST API ingestion |
| Validated | Schema, quality, range, format, and referential validation |
| Prepared | Cleaning, encoding, normalization, interactions, matrices, split |
| Features | Point-in-time recommendation feature engineering |
| Models | Collaborative and content-based training |
| EDA reports | Exploratory data analysis |
| Model reports | Evaluation and comparison reporting |
| MLflow runs | Parameters, metrics, models, and artifacts logged per algorithm |

Transformation configuration remains Git-versioned and its SHA-256 is copied
from the stage manifest where available.

## Batch traceability

The current graph preserves batch
`RECO_20260718_211004_2ec353` from ingestion through training. Feature batch
and model-run identifiers remain in their manifests and registry `run_id`
fields. The shared correlation identifier remains in upstream manifests.

## Verification

`python -m src.versioning.cli --verify` checks:

1. every selected storage location exists;
2. the current composite SHA-256 matches the registry;
3. every manifest path is readable, valid JSON, and non-empty;
4. every lineage parent and child node exists;
5. the graph contains no cycle.

`verify_dataset_version`, `verify_checksum`, `verify_lineage`, and
`verify_manifest` are reusable Python utilities. Verification failure returns
exit code `1`; technical failure returns `2`.

## Lineage limitations

The current generator does not publish a standalone generator manifest, so
Incoming reuses the ingestion manifest's `source_path`, batch, file counts,
and checksums. Model training publishes a training summary and per-model
metadata rather than a file named `model_manifest.json`; these are treated as
the authoritative model manifests. No earlier stage is modified merely to
rename these existing contracts.
