# RecoMart Preparation Execution Guide

## Prerequisites

Use the project Python environment, install `requirements.txt`, and complete
validation. At least users, products, clickstream, and purchase validated files
must be readable from an eligible validation manifest. Empty optional
popularity is allowed and reported.

Run the latest validated batch:

```powershell
python -m src.preparation.cli
```

Run a specific batch:

```powershell
python -m src.preparation.cli --batch-id RECO_20260719_010203_ab12cd
```

Override roots or skip plots:

```powershell
python -m src.preparation.cli `
  --output-path data/prepared `
  --report-path reports/eda `
  --no-run-eda
```

## Notebook

Interactive:

```powershell
jupyter notebook notebooks/data_preparation_and_eda.ipynb
```

Non-interactive:

```powershell
jupyter nbconvert --to notebook --execute `
  notebooks/data_preparation_and_eda.ipynb `
  --output data_preparation_and_eda_executed.ipynb
```

The notebook robustly resolves the repository root and delegates to production
functions. `BATCH_ID = None` selects the latest batch.

## Outputs and Inspection

Prepared data is under
`data/prepared/processing_date=.../processing_hour=.../batch_id=...`.
EDA is under the matching `reports/eda` partition. Inspect
`preparation_manifest.json` for lineage/checksums/status, then
`preparation_summary.json` and `eda_summary.json` for counts and statistics.
Structured rotating logs are at `logs/preparation/preparation.log`.

If a validated file is missing, restore/re-run validation rather than reading
raw or quarantine. If an immutable conflict occurs, verify source checksums,
configuration, and transformation version; never silently overwrite. A missing
plot dependency is a technical failure. Runtime data, executed notebooks,
plots, and logs are Git-ignored.

