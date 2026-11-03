# Unified data-footnote format with movable Review geometry

- Date: 2026-11-03
- Status: Accepted
- Supersedes in part: ADR-0039, ADR-0041 and ADR-0042

## Decision

The existing Constituents and Analytics data-footnote typography is the output contract for all
three data footnotes: Calibri/Carlito-compatible regular black text at 8pt, 1.2 line height, left
aligned, without inline emphasis and with zero authored paragraph spacing. Review's Historical
Performance footnote may no longer override that typography.

Review retains independent geometry: its opening page follows Historical Performance, while its
twelve-column `x`/`w` and 16-36mm `footer_bottom_mm` controls remain editable. Constituents and
Analytics retain their fixed footer placement. Structural footer space used to clear the logo and
folio is geometry, not authored paragraph formatting.

HTML, paged HTML/PDF and DOCX consume the same logical style. Legacy saved Review styles are
accepted for compatibility but ignored by renderers; editable documents canonicalize them on the
next successful save. Existing finalized content, checksums and version selection remain
immutable, while re-downloads receive the shared exporter presentation and a new renderer version.
