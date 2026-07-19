# Architecture Documentation

This folder defines RecoMart's system boundaries, repository ownership, data
movement, storage zones, and operational metadata design.

## Reading Order

1. [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md)
2. [SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md)
3. [DATA_FLOW_ARCHITECTURE.md](DATA_FLOW_ARCHITECTURE.md)
4. [REPOSITORY_STRUCTURE.md](REPOSITORY_STRUCTURE.md)
5. [S3_DATA_LAKE.md](S3_DATA_LAKE.md)
6. [DATABASE_DESIGN.md](DATABASE_DESIGN.md)

## Related Implementation

- Application services: `src/`
- DAGs: `dags/`
- SQL assets: `sql/`
- Configuration: `configs/`

Architecture applies across all stages; stage-specific details live under
`docs/pipeline/`.

[Back to Documentation Home](../README.md)
