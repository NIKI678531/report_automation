# ADR 0009: Financial Modeling Prep for Page 04 constituent period returns

- Status: Accepted
- Date: 2026-08-21
- Amends: the Page 04 source decision in the V2.1 execution specification and ADR-0004/ADR-0005

## Context

Page 04 previously required a Bloomberg workbook or a canonical combined CSV to supply 1M, 3M,
6M and YTD constituent Total Returns. The business has requested that these values be obtained
automatically from Financial Modeling Prep (FMP), using the selected report month and each
constituent's ticker/security code. The effective HSTECH constituent identity, price, weight and
HSICS code remain owned by the approved constituent snapshot source.

This introduces an external source that is not named in the original V2.1 source hierarchy, so the
deviation is recorded here rather than silently changing the production contract.

## Decision

The Page 04 return adapter calls FMP's
`historical-price-eod/dividend-adjusted` endpoint with the API key in the `apikey` request header.
For Hong Kong securities it uses the normalized `.HK` ticker and falls back to a zero-padded local
security code when the ticker is absent or not in FMP form.

The selected report date controls all windows. The adapter resolves the latest available Hong Kong
market date on or before the report date and on or before the 1M, 3M, 6M and prior-year-end targets.
It calculates each decimal return as:

```text
adjClose(period_end) / adjClose(period_start) - 1
```

The API documentation describes this series as dividend-adjusted and suitable for total-return
analysis. The exact FMP symbol, adjusted close, observation date, query window, formula, endpoint,
fetch time and response-derived checksum are retained in `SnapshotDataset.lineage`. API keys are
never persisted. A pre-listing period is stored as `N/A` with `INSUFFICIENT_HISTORY`, never zero.

An explicitly uploaded return dataset remains authoritative and is not silently overwritten by an
automatic refresh. An uploaded constituent identity dataset may be combined with an FMP return
dataset because they are separate logical datasets with independent lineage.

## Consequences

- Selecting a report month and applying/refreshing constituent identity can populate all Page 04
  return columns without a Bloomberg workbook.
- FMP availability, entitlement and rate limits become production dependencies for this slot;
  failures remain visible as provider findings and do not fabricate values.
- Historical constituents are not inferred from FMP. The report still requires an effective,
  approved HSTECH constituent snapshot for the selected month.
- FMP values may differ slightly from Bloomberg because each vendor maintains its own corporate
  action history. The snapshot's source and price observations make those differences auditable.

## Reference

- [FMP Historical Price EOD Dividend Adjusted API](https://site.financialmodelingprep.com/developer/docs/stable/historical-price-eod-dividend-adjusted)
