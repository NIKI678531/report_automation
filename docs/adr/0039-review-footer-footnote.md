# Review historical footnote uses the shared footer band

- Date: 2026-10-21
- Status: Accepted
- Supersedes in part: [ADR-0035](0035-paged-freeform-opening-presentation.md)
- Related: [ADR-0038](0038-editable-report-headings-and-advisory-layout-qa.md)

## Context

`3033-v4` rendered the Historical Performance footnote directly after its table. The other data
footnotes use the page footer band, so their default size, vertical anchor and DOCX structure
diverged. Editors still need to position the Review footnote without making every report page
footnote editable.

## Decision

- `3033-v5` uses `presentation.schema_version=3`. The Historical footnote remains on the same
  opening page as Historical Performance but renders in that page's footer layer.
- Its default and locked brand typography is Calibri/Carlito 8pt, black and regular. Editors may
  change line height, paragraph spacing and alignment, plus its twelve-column `x/w` and a
  `footer_bottom_mm` value from 16 through 36mm. The default is 20mm.
- Constituents and Analytics footnotes use the same base typography and retain fixed placement.
  Paged HTML/PDF and DOCX use page/section footers; continuous HTML keeps the semantic footnote
  after Historical Performance because it has no running chrome.
- Editable v1-v4 documents adapt to v5 in memory and persist v5 on first successful save. Their
  footnote content, page and width are retained; the obsolete table-relative gap resets to 20mm.
  Existing FINALIZED and ARCHIVED documents keep their original template behavior.
- Geometry findings remain advisory under ADR-0038. Invalid schema bounds are still rejected at
  document save time.

## Consequences

The three export formats share one footnote hierarchy and token while Review retains bounded
placement freedom. The version boundary prevents the corrected footer model from reflowing old
locked artifacts.
