# ADR 0004: Official Total Return series and atomic constituent import batches

- Status: Accepted
- Date: 2026-08-12

## Context

Historical Performance was coupled to an all-or-nothing DA-Report SQLite schema and could be
obscured by unrelated missing KPI/calendar tables. Constituent uploads were also bound to a
manually selected single dataset slot, so a valid HSTECH end-of-day file was parsed as the wrong
canonical layout and rejected.

## Decision

DA-Report owns versioned instrument bindings and official Total Return observations. Fund series
use Bloomberg `TOT_RETURN_INDEX_GROSS_DVDS`; approved net-total-return benchmark tickers use
`PX_LAST`. Report_Automation consumes only these official FUND/BENCHMARK series for Page 02. It
does not fall back to `market_snapshots`, synthetic values or golden fixtures. Total Return is
validated independently, so supporting-dataset failures keep the report pending without hiding
Historical Performance. A source checksum that has not changed produces no new snapshot or
document version.

Page 04 accepts a bounded in-memory batch of arbitrary files. Approved canonical or split layouts
are detected by content, unsupported files are recorded and skipped, and recognized invalid files
block the batch. Duplicate logical sources require explicit exclusion; canonical and split modes
cannot be mixed. The accepted files are composed in identity → returns → HSICS → full-QC order and
are applied in one transaction as one immutable snapshot and one document version.

## Consequences

Bloomberg mappings must be approved and pass a full 11-product dry run before release. Production
containers require no persistent volume: SQLite is published through object storage and uploads
are parsed from request memory. Existing single-file APIs remain available for compatibility, but
the constituent workspace uses the batch API.
