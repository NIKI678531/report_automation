# ADR-0023: Product ticker in constituent and sector headings

- Status: Accepted
- Date: 2026-09-08

## Context

The 3033 monthly report previously used the constituent index identifier `HSTECH` or the generic
word `Index` in three reader-facing headings. Those labels describe the report's fund analysis, so
Marketing requires the listed product ticker `3033.HK` instead. The index identifiers remain
necessary for data ingestion, validation and benchmark lineage.

## Decision

- Web, HTML, PDF and DOCX headings use the report's canonical `product_ticker`.
- For product 3033 the English headings are `The Performance of 3033.HK Constituents`,
  `Top 10 3033.HK Constituents` and `3033.HK Sectors Breakdown`.
- Simplified and Traditional Chinese use `3033.HK 成分股表现` and `3033.HK 成分股表現`
  respectively. The Top 10 and sector headings also replace the generic index label with the
  product ticker.
- `constituent_index_code` and `benchmark_instrument_code` remain unchanged because they identify
  the authoritative HSTECH constituent universe and HSTECHN return series.

## Consequences

The visible headings consistently identify the fund across all languages and output formats,
while data acquisition and lineage continue to use the correct index identifiers. Other products
automatically receive their own ticker in the same headings.
