# Portfolio holdings own constituent prices, weights and sectors

Accepted 2026-10-13 following the user's clarification that report `Weighting` means the fund
portfolio holding weight, not the tracked index weight. This supersedes ADR-0011 and the V2.1
DS-03/QC-002 wording where it made the index constituent snapshot authoritative for the fund's
security set, price, weight or sector distribution. A later production-data review found that
borrowing HSTECH HSICS assignments still produced an index-shaped three-sector chart even after
weights moved to the fund. The automatic fund chart must use holding-level GICS instead.
It also supersedes ADR-0012's HSTECH/HSICS dependency for the automatic Final Analytics path;
explicit uploaded constituents retain that HSICS contract.

## Decision

- The automatic Production path maps the listed fund ticker through the approved class master to
  `tradar_code`, then independently selects the latest available holding observation not later
  than the report date and inside that report month from
  `view_ads_busi_valuation_holding_exposure_1_f_p`.
- Holding-date selection is independent from Historical Performance. A performance observation on
  an earlier business date cannot force Page 04 or Final Analytics back to that date, and a Page 02
  source failure does not suppress an otherwise valid holding snapshot.
- Rows are limited to positive `Equity` / `TRADING` positions and grouped by normalized Hong Kong
  security code. `price` owns `close_price`; `value_percent`, already stored as a ratio, owns
  `weight`; `gics_sector` owns the sector assignment. Multiple position rows for one security are
  summed without rounding and must agree on price, currency and sector.
- `value_percent` is the approved market-value/NAV contract. Its complete fund/date population
  must reconcile to 100% within 0.01 percentage points. Displayed equities retain their source NAV
  weights and are not renormalized to 100%, because cash and other net assets are real denominator
  components.
- The automatic holdings path does not query the HSTECH constituent view. It never selects
  `index_weight` or HSICS fields, so index membership and index taxonomy cannot alter the fund
  sector chart. HSTECH remains available only to independent features such as the Company News
  selector.
- Standard holding GICS sector names map to stable GICS sector codes. A blank source sector is
  retained as an explicit `Unclassified` slice and warning; the service does not guess from the
  issuer name or tracked index. An unknown non-blank label blocks the snapshot as taxonomy drift.
- Explicit constituent uploads retain their effective-dated HSICS workflow. The source branch is
  recorded per snapshot; GICS and HSICS assignments are never mixed within one automatic chart.
- FMP continues to own constituent period returns. Top 10, sector weights, holding count and
  return-ranking tie breakers consume the portfolio-backed `weight` through the existing pure
  calculation layer.
- The rule applies to every automatic report month and revision; it is not conditional on a report
  ID or a hard-coded month. `The Performance of <ticker> Constituents`, `Performers in <month>` and
  the holding-driven rows of `<ticker> Portfolio Analysis` all consume the same normalized holding
  rows. Portfolio Analysis AUM and turnover retain their separate fund-level sources because they
  are not security-position attributes.

## Traceability and release behavior

Lineage records the enriched holding view, listed share-class mapping, holding row keys,
`weight_field=value_percent`, `industry_field=gics_sector`, complete portfolio total,
selected-equity total, the report-month query window, the actual selected date and any unclassified
security codes. A blocking source check rejects automatic warehouse snapshots that still identify
`index_weight`, index sectors, or omit the latest-report-month-holdings selection policy. The
compatibility dataset key remains
`index_constituents` so existing APIs and explicit full-dataset uploads do not break; its automatic
CDB mapping version is `cdb-portfolio-holdings-gics-v2`.

Existing finalized reports remain immutable. A report receives portfolio weights only after a new
automatic snapshot and calculation (or a new revision of a finalized report). Tests cover source
ownership, cash residuals without renormalization, duplicate-position aggregation, GICS chart
ordering, explicit unclassified holdings and preservation of the existing upload HSICS contract.
