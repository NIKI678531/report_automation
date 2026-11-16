# Editable finalized reports and marker-free Page 05

- Date: 2026-11-16
- Status: Accepted
- Supersedes in part: the V2.1 lifecycle table, ADR-0029, ADR-0038 and ADR-0047

## Decision

`FINALIZED` records are no longer a permanent editing lock. A non-archived report may append a new
working `ReportDocument` after finalization. The first mutation moves the report back into the
appropriate editable lifecycle state, but does not clear or overwrite `finalized_document_version`.
Downloads remain available throughout editing and continue to read that prior immutable version.
Only a later reviewer/admin finalization advances the download baseline to the latest document.
Reports that have never had a finalized version remain non-downloadable; `ARCHIVED` remains
read-only.

This deliberately separates the published baseline from the current working version. Append-only
documents, optimistic version checks, checksums, authorization, signed download grants, product
scope and export audit events remain unchanged. A grant is still bound to the current finalized
version and becomes invalid if re-finalization advances that version before the content request.

Page 05 Final Analytics no longer uses publication-marker suffixes. Localized defaults, calculated
portfolio labels and heading overrides remove trailing `*`, `**`, `^` and `^^`; render-time
normalization also covers already-finalized historical documents without rewriting their stored
content or checksum. HTML, PDF, DOCX, preview and the editor therefore agree. Page 05 heading
editors no longer offer the superscript-marker insertion control. Markers and footnote editing on
other report pages are outside this decision.

## Compatibility and verification

No database migration is required. Existing `finalized_document_version` values already identify
the stable downloadable baseline, and document versions remain append-only. Existing Page 05
overrides are normalized in memory and become marker-free when next saved; older finalized exports
receive the marker-free renderer presentation under ADR-0029's re-generation model.

Regression coverage verifies editing after finalization, downloading the prior version while edits
are pending, advancing the baseline on re-finalization, archived immutability, marker-free Page 05
API defaults/calculation payloads/editor output, and marker-free HTML/PDF/DOCX rendering.
