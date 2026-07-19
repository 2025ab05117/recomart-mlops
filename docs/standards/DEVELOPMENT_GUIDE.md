# RecoMart Development Guide

## Purpose

This guide provides the common workflow for making repository changes. Detailed
rules remain authoritative in the linked documents.

## Required Reading

1. [Documentation Home](../README.md)
2. [Codex Instructions](../instructions/CODEX_INSTRUCTIONS.md)
3. [System Architecture](../architecture/SYSTEM_ARCHITECTURE.md)
4. [Coding Standards](CODING_STANDARDS.md)
5. The complete documentation folder for the stage being changed

Also read [Mandatory Project Rules](../instructions/PROJECT_RULES.md) for layer,
security, lineage, and completion requirements.

## Development Workflow

1. Inspect the current implementation, configuration, manifests, tests, and
   relevant generated contracts before editing.
2. Identify the owning package and preserve the canonical layer sequence.
3. Keep business logic under `src/`; keep routes, DAGs, notebooks, and scripts
   thin.
4. Externalize non-secret behavior in validated YAML and inject secrets through
   environment variables or approved secret stores.
5. Implement focused, typed, documented, observable, and idempotent behavior.
6. Add deterministic unit tests and proportionate integration tests.
7. Update the authoritative documentation in the same change.
8. Run relevant tests and `python scripts/validate_docs.py`.

## Change Boundaries

Do not modify earlier pipeline stages unless compatibility requires it. Do not
mutate immutable runtime artifacts. Preserve unrelated work and avoid broad
refactors that are not necessary for the requested outcome.

## Completion

A change is complete only when code and documentation agree, relevant tests
pass, failure modes are explicit, credentials remain protected, lineage is
preserved, and no runtime output is unintentionally committed.

[Back to Documentation Home](../README.md)
