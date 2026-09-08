# ADR 0005: 3033-only workspace and upload-gated analytics

- Status: Accepted
- Date: 2026-08-13
- Supersedes: the Page 02 upload-free and multi-product UI portions of ADR-0003/ADR-0004

## Context

The current product release covers only 3033 / HSTECH. The expanded fund selector exposed
unapproved catalog entries. Page 02 did not expose its existing Total Return input slot, while
Page 04 waited for unrelated KPI and Historical Performance slots before showing any analysis.
That made a valid constituent upload appear to do nothing. The business also confirmed the five
top-level industry mappings used by this report.

## Decision

The report workspace fixes its product context to 3033 and does not render a fund selector.
Screenshot-derived catalog entries other than 3033 are inactive.

Page 02 exposes one audited `total_return_series` CSV slot. It accepts official FUND and BENCHMARK
Total Return observations; the server derives 1M, 3M, 6M and YTD endpoints from the selected report
date. An approved provider can still fill the same slot, but an automatic refresh preserves an
explicit upload. No public website fallback is adopted because it cannot guarantee the required
official Total Return definition and lineage.

Page 04 requires an explicit canonical or paired constituent upload in production. Once the
bundle passes identity, weight, return and HSICS checks, Page 05 immediately derives Top 10,
sector weights, Top/Bottom and holding count from that bundle. Missing AUM or turnover stays empty;
full report calculation and finalization continue to require every production slot.

The effective 3033 HSICS baseline is versioned reference data with these top-level mappings:
`10 Industrials`, `23 Consumer Discretionary`, `28 Healthcare`, `50 Financials`, and
`70 Information Technology`.

## Consequences

- No draft, fixture or hard-coded analytical value is substituted in the production lane.
- A successful Page 04 upload becomes visible and useful even while Page 02/KPI inputs are pending.
- The golden fixture remains available only in the explicitly marked TESTING lane for regression.
- Re-enabling another product or a public data provider requires approved catalog/source data and a
  new decision record.
