# ADR-0003: Automatic monthly data and SVG sector chart

## Status

Accepted on 2026-08-11.

## Decision

Monthly reports automatically load official fund/benchmark Total Return, fund KPI, trading calendar and index events from the immutable DA-Report SQLite snapshot. Effective-dated ProductCatalog fields bind each report product to those records. The only report-level upload is one canonical `constituent_performance` CSV, materialized as separate constituent snapshot and period-return logical datasets.

Final Analytics rankings and sector aggregation derive from that exact constituent snapshot checksum. AUM and turnover remain separate KPI facts. MetricValue and ModuleSnapshot records reference only their actual source datasets.

Sector breakdowns use a versioned static SVG donut in React and canonical HTML/PDF. No browser chart library, canvas, or CSS conic gradient is used. DOCX retains an editable table sourced from the same sector rows.

## Consequences

- Missing SQLite tables, product bindings or coverage produce auditable PENDING/blocked snapshots; no PDF or market-snapshot value is substituted.
- Refresh creates a new snapshot and preserves the active constituent upload rather than mutating it.
- Existing split upload records remain readable for compatibility, but the user workspace exposes only the merged CSV.
- DA-Report schema and ETL changes remain an external delivery until its repository is added to the workspace.