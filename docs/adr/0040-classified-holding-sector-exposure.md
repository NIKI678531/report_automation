# Classified holding sector exposure follows the approved SECT query

Accepted 2026-10-14 after the user supplied the operational `account_holdings` /
`account_holdings_data` exposure query and requested that report pages no longer display
`Unclassified`. This decision supersedes ADR-0039 and V2.1 FR-504 only where they require a blank
holding sector to appear as an explicit donut slice. It also supersedes the earlier rule that the
automatic donut displays unnormalised NAV weights.

## Decision

- Constituents, Top 10 and holding count continue to use the latest report-month physical fund
  holding snapshot and the source `value_percent` NAV weights. This decision changes only the
  automatic sector exposure calculation.
- The automatic sector exposure is calculated from raw position rows before rows for the same
  security are collapsed. Rows must be `class = Net Assets`, `position_class = Trading`, and have
  a classified GICS sector. `Mutual Fund`, `ETF`, `Futures`, `Call Option`, `Index Futures`, blank
  sectors and `Unclassified` are excluded, matching SQL `sector NOT IN (...)` / null semantics.
- The denominator is the sum of every eligible position weight rounded to one decimal percentage
  point. For operational account book `1015945`, mapped to product ticker `3033.HK` in the CDB
  adapter, each sector numerator is also the sum of those rounded position weights. Other account
  books retain the query's exact numerator over the rounded denominator.
- CDB stores `value_percent` as a ratio, so rounding to one decimal percentage point is implemented
  by quantizing the ratio to `0.001` with SQL-compatible half-up rounding.
- Blank GICS remains explicit on the constituent snapshot and produces
  `PORTFOLIO_GICS_UNCLASSIFIED`; it is not inferred from the tracked index. It is excluded only from
  `sector_exposures` and therefore never reaches HTML/PDF/DOCX or the React donut. React also hides
  the retired bucket when reading a legacy saved chart snapshot.
- The source adapter records the numerator, denominator, excluded values, operational account-book
  mapping and rounded denominator in lineage. Its mapping version is
  `cdb-portfolio-holdings-sector-v3`; the 3033 calculation profile is `hstech-2026.2`.
- Explicit uploaded constituents keep the effective-dated HSICS calculation. Replacing automatic
  identity data removes the automatic `sector_exposures` so source contracts cannot mix.

## Release behavior

Existing finalized reports remain immutable. Editable September reports are refreshed after the
release, which appends a new snapshot/document version and preserves editorial content. For the
2026-09-30 3033 source observation, the expected displayed sector values are 40.3%, 32.4%, 25.5%
and 1.9%, with no Unclassified legend entry.
