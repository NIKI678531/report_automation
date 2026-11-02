# ADR-0045: Two-line report title and current compliance copy

- Date: 2026-10-28
- Status: Accepted
- Supersedes in part: ADR-0032 and ADR-0043

Every on-demand export, including a re-export of an already finalized or archived document, now
renders the report title as two explicit lines. The first line is the resolved product name with its
ticker exactly once; the second line is the localized Monthly Commentary label. HTML and Chromium
PDF share the canonical heading markup, while DOCX writes the same two values into one editable
Title paragraph separated by a line break. This presentation rule is renderer-owned: stored
ReportDocument content, checksum and template identity are not rewritten.

The continuous-HTML reader date is the last calendar day of the report month, formatted as
`D Mon YYYY`. It is no longer the day on which the HTML happened to be downloaded. For 3033 only,
continuous HTML also places the approved English `IMPORTANT INFORMATION` notice above the report
title. The notice is reader chrome, not report content: paged preview, official PDF and DOCX do not
include it. Its copy is an immutable resource with a compiled version and checksum, and HTML export
audits record both fields. A missing or modified notice blocks that HTML export and returns a
specific safe error without exposing resource paths.

The fifth/final compliance page now uses `csop-hk-disclaimer-v2`, including the `Disclaimer:` title,
five approved paragraphs and issuer line. As with ADR-0032, the current resource is appended at
render time and cannot be overridden by editable or historical document JSON. Its version and
checksum remain part of every export manifest and audit record. The prior v1 resource remains in
the repository as historical evidence but is no longer selected by the renderer.

Renderer identities advance to `html-reader-compliance-v10`,
`chromium-v1-paged-compliance-v7` (using the configured Chromium prefix), and
`docx-compliance-v8`; the layout policy advances to `paged-layout-advisory-v4`. New reader-only
spacing and colour values live in `3033-reader-v2` tokens. On-demand regeneration therefore changes
artifact bytes and checksums but not the locked source document, consistent with ADR-0029.

Rollback restores the previous renderer identities, reader date/title markup, and selected legal
resource. It does not require a database migration or an immutable document rewrite.
