# Report Metadata Configuration

## Purpose

`config/report_metadata.yaml` is the single source of truth for static report
metadata. It contains the report identity, project description, and team roster
needed by future report generators. Keeping these values separate from rendering
code makes them easy to review and update without changing an implementation.

## Structure

The configuration has three top-level sections:

- `report` contains title-page fields such as the title, institution,
  assignment, version, and academic year.
- `project` identifies the repository, project domain, and objective.
- `team` is an ordered list of team-member records. Every record contains a
  unique `serial_no`, a `name`, and a `bits_id`.

## Maintaining the Team Roster

To add a member, append one complete mapping to `team` and assign the next
unique serial number. To remove a member, delete that member's complete list
item. After either change, renumber the remaining entries sequentially so the
display order is explicit and stable.

Names and BITS IDs must be maintained only in `config/report_metadata.yaml`.
Do not copy the roster into generator code, templates, or other documentation.

## Use by Future Report Generators

A future PDF report generator will load this YAML, validate the required keys,
and use `report` and `project` values on the title page. It will iterate over the
`team` list in `serial_no` order to build the Team Member Details section.

Generators should treat the file as input only, fail clearly when required
metadata is missing or malformed, and avoid embedding fallback copies of team
details. Updating this single file should therefore update every subsequently
generated report consistently.
