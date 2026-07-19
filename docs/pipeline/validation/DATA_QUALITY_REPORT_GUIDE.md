# RecoMart Data Quality Report Guide

## Report Artifacts

Every completed run publishes three files beneath the same UTC validation
partition and batch ID:

- `data_quality_summary.json`: authoritative complete automation payload.
- `data_quality_report.pdf`: human-readable multi-page representation.
- `validation_manifest.json`: execution, lineage, status, and destination index.

The PDF contains a cover, executive summary, dataset summary table, detailed
profiles, grouped issues, cross-dataset integrity results, recommendations,
and an appendix. Tables repeat headers across pages; samples are limited by
`validation.sample_error_count` and should not be treated as complete extracts.

## Interpreting Scores and Status

Scores range from 0 to 100 and combine completeness (30%), uniqueness (20%),
validity (30%), and consistency (20%). A high score is not proof that every
rule passed: always inspect the failed-rule section. `SUCCESS` has no ERROR
failures. `COMPLETED_WITH_QUALITY_ISSUES` means the report is complete but
invalid records or ERROR failures exist. `FAILED` means validation could not
complete reliably because of a technical or critical schema problem.

Dataset tables show total, valid, and invalid records plus missing, duplicate,
schema, range, format, and referential issue counts. Detailed sections show
expected versus inferred schema, descriptive statistics, timestamps, and every
rule outcome. Cross-dataset sections summarize orphan references, ratings,
purchase-price consistency, and popularity/product agreement.

## JSON Structure

The summary top level contains batch and run identifiers, status, execution
times, configuration identity, aggregate counts and score, dataset entries,
cross-dataset results, recommendations, and errors. Each dataset entry contains
source lineage, destinations, component scores, a full profile, and structured
rules. Each rule exposes its ID, category, severity, status, records checked,
failure count/percentage, message, and bounded samples.

The validation manifest is the compact operational index. Downstream jobs
should read it first, require a non-`FAILED` status according to their policy,
then follow its summary/report and dataset paths rather than scanning folders.

