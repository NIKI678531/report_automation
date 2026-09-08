# ADR-0022: Binary Company News catalog scope

- Status: Accepted
- Date: 2026-08-31
- Supersedes: ADR-0020

## Context

The single-company selector made editors choose one of 30 HSTECH companies at a time. The intended
workflow is instead to compare the complete regional Corporate catalog with the combined news set
for every constituent of 3033.HK in the selected report month.

## Decision

- The Company News workbench exposes a two-state segmented control: `All companies` and
  `3033.HK constituents`. The complete DA-Report Regional Corporate catalog is the default.
- `GET /reports/{id}/news/catalog?company_scope=CONSTITUENTS` matches a news item when its title
  contains an alias of any company in the complete report-month constituent universe. English,
  Simplified Chinese, Traditional Chinese, full ticker and controlled source aliases participate in
  boundary-aware matching. Summary-only mentions do not match.
- Search, source, sentiment, importance, date, ordering and keyset pagination compose with the scope,
  and the scope is included in the cursor signature. Clearing filters restores `All companies`.
- The constituent control is unavailable when no complete valid report/sibling snapshot or complete
  report-month CDB list exists. Catalog browsing remains available.
- `company=<security_code>` remains supported for API compatibility. Submitting it together with
  `company_scope` returns structured 422 `DA_REPORT_COMPANY_FILTER_CONFLICT`.

## Consequences

Editors can inspect the entire investable-universe news set with one action without changing the
default catalog or materializing browsing results. No schema migration or persistent storage is
introduced.
