# ADR-0017: Continuous HTML and paged formal documents use separate layouts

- Status: Amended by ADR-0018
- Date: 2026-08-24

## Context

V2.1 requires HTML print CSS to reproduce the four-page reference. The approved product change
requires the online preview and downloaded HTML to read as one continuous white document without
running headers, footers, page numbers, fixed A4 heights or gaps. PDF and DOCX must retain the
formal four-page A4 presentation.

## Decision

The canonical Jinja renderer accepts an explicit `continuous` or `paged` layout mode while both
modes consume the same versioned `ReportDocument`, terminology and design tokens.

Preview and HTML artifacts always use `continuous`. Semantic section identifiers remain stable,
footnotes participate in normal document flow, and wide tables expose horizontal scrolling on
small screens. The template omits page chrome entirely in this mode.

PDF always uses `paged` and keeps A4 page geometry, running header/footer, logo, page number and
overflow checks. DOCX remains a four-section editable A4 document. Format-specific renderer
versions and language-tagged filenames prevent stale or cross-language artifact reuse.

## Consequences

- Downloaded HTML no longer prints as the same four-page layout described by V2.1; PDF/DOCX are
  the formal paged formats.
- Continuous and paged outputs share content but intentionally differ in page chrome and flow.
- Existing artifacts remain immutable and are not reused after the renderer-version change.
