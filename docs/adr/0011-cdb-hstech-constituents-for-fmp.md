# ADR 0011: CDB HSTECH constituents as the automatic FMP identity source

- Status: Accepted
- Date: 2026-08-21
- Extends: ADR-0009 and ADR-0010

## Context

Page 04 needs the selected month's HSTECH membership, ticker, names, closing price, currency,
weight and HSICS codes before FMP can calculate constituent returns. Requiring a CSV for those
identities made the automatic FMP path unavailable on a new report and allowed the report month to
drift from the constituent effective date.

The approved CDB view `view_ads_busi_market_index_constituent_price_daily_f_p` was verified to
contain the required HSTECH fields. For 2026-06-30 it returns 30 constituents whose weights total
1.0. FMP's dividend-adjusted EOD history successfully resolves the four requested periods from the
normalized `.HK` tickers.

## Decision

- The automatic refresh uses the same effective date selected for Page 02, then reads HSTECH
  constituents from the configured CDB view at that exact date.
- CDB owns constituent identity, ticker, names, closing price, currency, weight and source codes;
  FMP owns 1M, 3M, 6M and YTD Total Return values and their observed boundaries.
- A constituent CSV remains a separate, explicit identity override. Automatic refresh preserves an
  effective upload instead of silently replacing it.
- Both sources are normalized into the existing immutable snapshot and lineage model. Credentials
  are provided only through deployment secrets and never enter API responses, logs or snapshots.
- Missing CDB coverage, missing FMP coverage or an index/date mismatch is reported explicitly; the
  system does not substitute zeroes or borrow data from another month.

## Consequences

- A new 3033 report can populate Page 04 without waiting for a CSV.
- The UI presents CSV override and automatic CDB + FMP as separate actions.
- Page 02 and Page 04 share one report-month-effective CDB date, improving reproducibility.
- The automatic route remains dependent on CDB and FMP availability; approved uploads remain the
  auditable fallback.
