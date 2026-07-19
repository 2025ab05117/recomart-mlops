# Ingestion Documentation

This folder covers file and REST ingestion, immutable raw storage, manifests,
retry behavior, and execution.

## Reading Order

1. [INGESTION_DESIGN.md](INGESTION_DESIGN.md)
2. [RAW_STORAGE_STRUCTURE.md](RAW_STORAGE_STRUCTURE.md)
3. [INGESTION_EXECUTION_GUIDE.md](INGESTION_EXECUTION_GUIDE.md)

## Related Implementation

- Code: `src/ingestion/`, `src/api/`
- Configuration: `configs/ingestion.yaml`
- CLI: `python -m src.ingestion.cli`
- Previous stage: Generator / incoming data
- Next stage: [Validation](../validation/README.md)

[Back to Documentation Home](../../README.md)
