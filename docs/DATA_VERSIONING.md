# Data Versioning

## Purpose

RecoMart versions data because source code alone cannot reproduce a model.
Reproducibility requires the exact input bytes, transformation configuration,
manifests, feature materialization, model artifacts, and reports. Git versions
source code, YAML, SQL, DVC metadata, and documentation. DVC versions generated
and large artifacts. Git LFS is not used.

## Versioned lifecycle

The registered lifecycle is:

`Incoming → Raw → Validated → Prepared → Features → Models`

EDA reports branch from Prepared. Model reports branch from Models. Model
lineage terminates in the corresponding MLflow experiment runs.

Independent DVC targets are maintained for:

- `data/incoming`
- `data/raw`
- `data/validated`
- `data/prepared`
- `data/features`
- `models`
- `reports/eda`
- `reports/model_training`

Each target has a small `.dvc` metadata file committed to Git. Its content is
stored in the local DVC cache and, when configured, in a remote. Generated
payloads remain excluded from Git.

## Semantic version strategy

Human-readable versions follow `<artifact>-vMAJOR.MINOR.PATCH`, for example
`prepared-v1.0.0`.

- **MAJOR** changes when the dataset contract is incompatible.
- **MINOR** changes for backward-compatible schema or feature additions.
- **PATCH** changes when bytes change without a schema-contract change.

The YAML configuration defines the starting contract version. Registration
reuses an existing version when the deterministic artifact SHA-256 is unchanged.
When the checksum changes, it increments the greatest registered patch. The
registry DVC output is persistent so version history survives `dvc repro`.
Historical registry states also remain recoverable through Git and DVC.

## Checksums

Files use SHA-256 over their bytes. Directories use a deterministic composite:
sorted relative file name, separator, file SHA-256, and newline for every file.
This makes moves within an artifact, additions, removals, renames, and byte
changes detectable. The ingestion, validation, preparation, feature, and model
manifests remain authoritative for their own per-file and configuration hashes;
the registry adds one artifact-level checksum instead of duplicating those
fields.

Both the producing manifest and registry preserve pre/post-transformation
identity. A lineage edge contains the child artifact checksum, while the parent
registry record supplies its input checksum.

## Dataset registry

`reports/versioning/dataset_registry.json` records every registered version:

- dataset version and name;
- batch and producing run;
- pipeline stage and UTC creation time;
- artifact checksum and record count;
- schema version;
- parent dataset version and parent batch;
- producer identity;
- portable repository-relative storage location;
- authoritative manifest path;
- transformation configuration hash.

Only one entry per dataset is marked `is_current`. Prior entries are retained.
Registration never edits an upstream manifest or dataset.

## Repository layout

```text
.dvc/
data/*.dvc
models.dvc
reports/*.dvc
dvc.yaml
dvc.lock
.dvcignore
configs/versioning.yaml
src/versioning/
reports/versioning/
```

`.dvc/config` contains non-secret repository configuration. Credentials never
belong in DVC metadata, Git, YAML, logs, or command arguments. Use environment
variables, cloud SDK credential chains, or local-only DVC configuration.

## Reproducibility identity

A reproducible execution is identified by:

1. Git commit for code, SQL, configuration, and DVC metadata;
2. DVC object hashes in `.dvc` files and `dvc.lock`;
3. batch/run IDs from existing manifests;
4. dataset semantic versions and SHA-256 values;
5. MLflow run IDs and model configuration hash.

Together these identify the exact bytes and transformations used to train a
model.
