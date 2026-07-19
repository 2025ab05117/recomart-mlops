# RecoMart Feature Execution Guide

## Prerequisites

Install `requirements.txt` and complete preparation. Configure the database only
through `RECOMART_DATABASE_URL` or the masked CLI override.

SQLite:

```powershell
$env:RECOMART_DATABASE_URL = "sqlite:///data/recomart_features.db"
python -m src.feature_engineering.cli --initialize-database
python -m src.feature_engineering.cli
```

PostgreSQL:

```powershell
$env:RECOMART_DATABASE_URL = `
  "postgresql+psycopg://recomart_user:replace_me@localhost:5432/recomart"
python -m src.feature_engineering.cli --initialize-database
python -m src.feature_engineering.cli
```

Use `--batch-id`, `--feature-batch-id`, `--source-split train|all`,
`--skip-parquet`, `--prepared-path`, or `--output-path` as documented by
`--help`. Default source split is leakage-safe `train`.

Snapshots and summary/manifest files are under `data/features` partitions.
Inspect SQL tables/views with a PostgreSQL client or SQLite:

```powershell
python -c "import sqlite3; c=sqlite3.connect('data/recomart_features.db'); print(c.execute(\"SELECT name,type FROM sqlite_master WHERE type IN ('table','view')\").fetchall())"
```

Structured logs are at
`logs/feature_engineering/feature_engineering.log`; URLs/passwords are never
logged. Missing manifests/files fail clearly. A conflict means immutable
identity differs—use a new feature batch rather than overwriting. PostgreSQL
connection failures require verifying service, role, database, network, and
secret injection without printing credentials.

