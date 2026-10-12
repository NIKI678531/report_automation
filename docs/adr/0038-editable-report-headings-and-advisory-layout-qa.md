# Editable report headings and advisory layout QA

Accepted 2026-10-12, following the user's request to edit report headings and their default footnote markers, and to download reports despite red overflow indicators. Report heading overrides are versioned editorial content; measured layout defects remain visible and audited but no longer veto finalization or HTML/PDF/DOCX generation. This supersedes the release-time layout blocking policy in ADR-0033/0035 and the corresponding rendering-release restriction in V2.1; it does not change the fixed disclaimer contract in ADR-0032 or download security in ADR-0029.

## Heading Contract

- Optional `ReportDocument.content.title_overrides` maps stable heading IDs to plain text of 1-200 characters. Omitted keys use existing localized defaults, including `*`, `**`, `^` and `^^`; deleting a suffix removes its marker, and restoring the default removes the override. Footnote bodies are not removed or renumbered automatically.
- IDs cover Historical Performance, Company News, Constituent Performance, Top 10, sector breakdown, the performer group and its top/bottom subheadings, Portfolio Analysis and its AUM/turnover/holding-count labels. Review block titles remain in `blocks[].title`; the product display heading keeps its existing `terminology_overrides.product_name` source. Financial values, dates, units, navigation and approved legal copy are not made editable by this change.
- The existing report detail response supplies `report_title_defaults`. Review edits share the current document draft, preview and pending-save callback. Existing document PATCH, optimistic locking, checksums and append-only versions apply; no schema migration or new endpoint is required.
- HTML/PDF and DOCX use the same pure title resolver after portfolio normalization/localization. Titles are escaped text, never trusted HTML. Snapshot rebinding/recalculation preserve overrides; each language variant retains its own overrides, and Review translation does not transmit or replace them.

## Release Policy

- `paged-layout-advisory-v3` retains raw geometry detection, including the prior 3 mm threshold, while release/export findings become `WARNING`; originally severe findings retain `original_severity=BLOCKING`. Successful finalization and exports include these findings in `layout_warning_findings` audit metadata.
- The historical `assert_page_one_layout_fits` entry point remains compatible with callers but no longer raises because of measured layout defects. Legacy all-page footer measurement now joins the shared preflight; the second PDF-only veto is removed. Frontend red/yellow markers and diagnostic geometry tests remain.
- Roles, product scope, optimistic versions, the fixed finalized document, checksums, subject-bound signed download grants, approved disclaimer validation, actual renderer errors and temporary-file cleanup are unchanged. Draft-only download is not introduced. Existing advisory data-release checks remain advisory.
- A successful download does not establish that overflowed content is fully visible. Clipping, overlap or footer contact may remain in the generated file; reviewers retain responsibility for its presentation. Geometry validity at document-save time is still enforced.

## Verification

Existing content-workflow, report API, translation, layout, disclaimer, security and visual-QA tests cover the change. New acceptance cases save/remove/reset markers, preserve independent language edits, compare actual HTML/PDF/DOCX headings in English/Simplified/Traditional Chinese, and finalize/download real overflowing content with audited findings. Frontend tests exercise pending-save-before-finalize and read-only behavior. Isolated Chromium checks against the production build verify edit/reload/reset, viewport bounds and retained red markers at 1440x1000 and 390x844 without starting application services or accessing real reports.
