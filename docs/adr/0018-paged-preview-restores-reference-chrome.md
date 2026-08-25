# ADR-0018: Online preview restores the paged reference presentation

- Status: Accepted
- Date: 2026-08-25

## Context

ADR-0017 made both the online preview and downloaded HTML continuous. Product feedback now
requires the Preview action to reproduce the approved `3033_LCD_20260630` visual contract,
including four A4 pages, the running header and rule, the CSOP footer logo, and page numbers.
The downloaded HTML remains intended for continuous on-screen reading.

## Decision

The preview endpoint renders the canonical Jinja template with `preview=True` and
`layout_mode="paged"`. It therefore uses the same page geometry, header, footer, embedded logo,
page numbering, and content CSS as the PDF renderer; the frontend does not add separate preview
chrome.

Downloaded HTML artifacts continue to use `continuous`. PDF uses `paged`, and DOCX retains its
four-section A4 presentation.

## Consequences

- Preview again provides a faithful four-page representation of the approved reference PDF.
- Page chrome remains sourced from the canonical renderer and the approved embedded logo asset.
- The responsive continuous layout is still available in downloaded HTML, so this decision
  supersedes only the preview portion of ADR-0017.
