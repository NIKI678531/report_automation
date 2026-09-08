# ADR-0020: Report-month CDB fallback for the Company News company filter

Status: Superseded by ADR-0022

## Context

ADR-0002 allowed the Company News catalog to be browsed without an active report snapshot, but it
disabled the company selector in that state. Editors need the selector to contain the 30 companies
in the selected report month's HSTECH universe before the rest of the report data has been prepared.
They also require a selected company to return only news whose title directly identifies it.

## Decision

- A valid constituent snapshot for the same product and report date remains the first source for the
  company selector, including a valid snapshot shared by another language variant.
- When that snapshot is unavailable, the API reads the latest CDB index-constituent observation not
  later than the report date and within the same calendar month. It never borrows another month's
  membership and does not materialize this read into a report snapshot.
- The CDB fallback is exposed only when its row count matches the product catalog's configured
  expected constituent count. Successful reads are cached in-process for five minutes; failures are
  not cached.
- CDB failure or incomplete membership leaves the full DA-Report catalog available and disables only
  the company selector.
- `company=<security_code>` remains the public filter contract. Matching is boundary-aware and is
  limited to enriched English and Chinese titles plus the raw title. Controlled English, Traditional
  Chinese, derived Simplified Chinese, source-name aliases and the full ticker are eligible aliases;
  summary-only mentions do not match.

## Consequences

This decision supersedes ADR-0002 only where it said the selector is unavailable without a valid
constituent snapshot. Catalog scope, pagination, selection materialization and cross-period warning
behavior remain unchanged. No database migration or persistent media/storage dependency is added.
