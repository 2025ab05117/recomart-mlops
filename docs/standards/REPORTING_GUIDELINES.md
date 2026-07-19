# Reporting Guidelines

## Purpose

RecoMart reports communicate pipeline health, data quality, feature quality,
model performance, and lineage. Reports are generated from registered metadata
and immutable artifacts; they do not recompute undocumented business logic.

## Report Types

### Batch Ingestion Report

Includes batch identity, source, object checksums, expected and observed files,
record counts, ingestion duration, raw assets, and final batch status.

### Data Quality Report

Includes validation rule results, severities, accepted/rejected counts,
quarantine references, threshold decisions, schema versions, and bounded
diagnostic samples.

### Preparation and Feature Report

Includes reconciliation counts, transformation versions, join coverage, feature
schema, missingness, distribution summaries, drift indicators, and
materialization references.

### Model Evaluation Report

Includes experiment identity, input feature versions, split composition,
baseline comparison, overall and segment metrics, threshold results, model
artifact reference, limitations, and promotion decision.

### Lineage Report

Traces source batch through data assets, feature materialization, model run,
MLflow record, and report. It includes code/configuration versions and
checksums.

## Required Metadata

Every report contains:

- report title, type, and immutable report version;
- generation timestamp in UTC;
- environment and producer version;
- `batch_id`, `run_id`, and correlation ID where applicable;
- source asset/model IDs, URIs, versions, and checksums;
- configuration/schema/feature versions;
- status, conclusions, and explicitly stated limitations.

## Formats

JSON is the canonical machine-readable result. HTML or Markdown is the standard
human-readable rendering. PDF may be generated when required for submission or
distribution. All formats for one report share the same report ID and source
facts.

Tabular artifacts may be attached as CSV only for small human-facing extracts;
canonical pipeline data remains Parquet.

## Visual Standards

Charts must have descriptive titles, labeled axes, units, legends when needed,
and accessible color choices. Scales and truncation must not mislead. Display
the sample size and evaluation period. Comparisons use consistent axes and
definitions. Tables indicate null or unavailable values explicitly.

## Publication

Reports are rendered to a run-scoped temporary location, verified, uploaded to
the reports zone, and committed with a checksum. PostgreSQL registers the report
only after object publication succeeds. Published versions are immutable.

File names and object keys use stable identifiers, not user-supplied free text.
Bucket names and public URLs are not hardcoded.

## Data Safety

Reports must not contain credentials, connection strings, full environment
variables, stack traces, or unnecessary row-level user data. Diagnostic samples
are bounded and sanitized. User identifiers should be aggregated or masked in
human-facing output unless essential to an authorized technical investigation.

## Accuracy and Reproducibility

Report values come from persisted validation results, feature statistics, model
metrics, and lineage records. Metric definitions and units are explicit.
Rounding is presentation-only; machine-readable results preserve suitable
precision. A report can be regenerated from its registered source versions.

## Failure Handling

Rendering, upload, registration, and source-completeness failures are distinct.
A partial report is never published as successful. Failure is logged with report
and run context, and temporary output is retained or removed according to the
configured diagnostic policy.

## Testing

Tests verify required sections, metadata, deterministic rendering, empty and
boundary cases, escaping of untrusted text, checksum creation, and publication
semantics. Visual formats receive smoke or snapshot tests where stable, while
the canonical JSON receives exact schema validation.

## Academic Submission Quality

Submission reports must state dataset edition, experimental setup, assumptions,
limitations, and comparison baseline. Claims must be supported by recorded
metrics and reproducible artifacts. Generated charts and tables must identify
their source run.
