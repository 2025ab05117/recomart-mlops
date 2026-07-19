# DVC Guide

## Prerequisites and initialization

Use the project virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
dvc version
```

The repository is already initialized. For a new clone, `.dvc/`, `dvc.yaml`,
`dvc.lock`, `.dvcignore`, and the committed `.dvc` artifact files are restored
by Git. Do not run `dvc init` again.

## Normal workflow

Inspect state:

```powershell
dvc status
python -m src.versioning.cli --verify
```

Refresh metadata after an upstream stage creates new immutable output:

```powershell
dvc add data/raw
dvc repro
git add data/raw.dvc dvc.lock reports/versioning
```

Use the corresponding `.dvc` target for validated, prepared, features, models,
EDA reports, or model reports. Never `git add` the generated directory itself.

## Pipeline

`dvc.yaml` represents:

`generator → ingestion → validation → preparation → feature_engineering → training → registry_and_lineage`

The first six stages snapshot existing, authoritative stage output and manifest
metadata. This adapter deliberately does not duplicate generator, validation,
feature, or modeling business logic. The final stage registers semantic
versions, builds lineage, verifies checksums, renders the graph, and publishes
DVC metrics.

Run:

```powershell
dvc repro
dvc metrics show
```

The virtual environment must be active so the portable `python -m` stage
commands resolve project dependencies.

## CLI examples

Default full registration, lineage, summary, graph, and verification:

```powershell
python -m src.versioning.cli
```

Register or verify a selected stage:

```powershell
python -m src.versioning.cli --stage prepared --register
python -m src.versioning.cli --stage prepared --verify
```

Select an upstream batch:

```powershell
python -m src.versioning.cli `
  --batch-id RECO_20260718_211004_2ec353 `
  --generate-registry
```

Generate lineage after registration:

```powershell
python -m src.versioning.cli --generate-lineage
```

## Local and remote storage

DVC always uses its local content-addressed cache. A remote is optional and
must contain no embedded credentials.

Local NAS or development directory:

```powershell
dvc remote add -d artifact-store D:\dvc-storage\recomart
```

S3:

```powershell
pip install "dvc[s3]"
dvc remote add -d artifact-store s3://recomart-data/dvc
```

MinIO uses the S3 backend. Put the endpoint in local DVC configuration:

```powershell
dvc remote add -d artifact-store s3://recomart-data/dvc
dvc remote modify --local artifact-store endpointurl http://localhost:9000
```

Azure Blob:

```powershell
pip install "dvc[azure]"
dvc remote add -d artifact-store azure://recomart/dvc
```

Use the standard AWS/Azure environment variables, profiles, managed identity,
or secret manager. Prefer `--local` for machine-specific endpoints. Never
commit access keys, secrets, session tokens, connection strings, or signed
URLs.

## Push, pull, and checkout

```powershell
dvc push
dvc pull
dvc checkout
```

`push` copies cache objects to the configured remote. `pull` downloads missing
objects and checks them out. `checkout` changes the workspace to the data
versions referenced by current Git/DVC metadata.

## Restore a previous dataset version

Data versions are paired with Git commits containing `.dvc` files and
`dvc.lock`. To restore a previous prepared dataset:

```powershell
git log -- data/prepared.dvc
git checkout <commit> -- data/prepared.dvc dvc.lock
dvc pull data/prepared.dvc
dvc checkout data/prepared.dvc
python -m src.versioning.cli --stage prepared --verify
```

To restore the entire pipeline at a release:

```powershell
git checkout <tag-or-commit>
dvc pull
dvc checkout
dvc status
```

Create a new branch before continuing development; do not rewrite immutable
historical artifacts.

## Metrics

`reports/versioning/dvc_metrics.json` exposes scalar values compatible with
`dvc metrics show`:

- registered dataset versions;
- current artifacts;
- lineage edge count;
- verification failure count.

EDA summaries, feature summaries, and training metrics remain independently
versioned in their DVC artifacts and referenced from stage manifests.

## Troubleshooting

- **System Python cannot import a dependency:** activate `.venv` before
  `dvc repro`.
- **Output is Git-tracked:** remove it from the Git index with
  `git rm --cached`, preserve the local file, then run `dvc add`.
- **Checksum mismatch:** restore the DVC version; never edit immutable raw data.
- **Missing manifest:** rerun the producing stage or restore its DVC artifact.
- **No remote configured:** local tracking still works; configure a remote
  before `dvc push`.
- **Credential failure:** inspect the standard provider credential chain
  without printing secrets.
