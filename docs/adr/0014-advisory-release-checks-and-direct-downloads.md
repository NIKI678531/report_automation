# ADR 0014: Advisory release checks and direct format downloads

- Status: Accepted
- Date: 2026-08-24

## Context

The original workflow made every failed blocking quality check prevent finalization. This left the
Downloads control disabled when a source such as the trading calendar was unavailable, even though
the canonical document could still render its available content and explicit `N/A` values.

The product owner requested a direct workflow: Review & finalize must unlock downloads without
showing blocking or warning messages, and Downloads must offer PDF, editable Word and HTML.

## Decision

Release checks remain available from the review API for diagnostics, but are advisory during
finalization. A matching document version and the existing authorization policy remain mandatory.
Finalization records the IDs of failed advisory checks in the audit event without exposing them in
the main workflow.

After finalization, the frontend opens a Downloads menu with PDF, Word (`.docx`) and HTML options.
Selecting a format reuses an existing artifact or creates that single render and downloads it as
soon as the render succeeds. Signed, time-limited artifact URLs remain unchanged.

## Consequences

- Missing or incomplete datasets no longer prevent a report from being finalized and downloaded.
- Rendered reports may contain explicit empty or `N/A` content when source data is unavailable.
- Review findings remain queryable and auditable, but are not displayed in the direct download flow.
- This intentionally relaxes FR-602/FR-603 release-gate behavior while preserving version locking,
  access control, immutable finalized documents and the shared PDF/HTML/DOCX content model.
