# Font-gated activation of the 3033 v6 template

- Date: 2026-10-27
- Status: Accepted
- Clarifies: ADR-0041

## Context

ADR-0041 requires a licensed Calibri Regular TTF before v6 can render HTML or PDF. The standard
production image intentionally contains only the approved redistributable Carlito and Noto fonts,
and the Production cluster has no `CALIBRI_FONT_PATH` or licensed font layer. The database migration
in the same release activates `3033-v5`, not v6.

The initial v6 implementation nevertheless changed the generic document read/save adapter so every
editable v1-v5 report was silently restamped to v6. This bypassed the catalog migration and caused
ordinary preview, finalize and export requests to fail with `CALIBRI_FONT_UNAVAILABLE`.

## Decision

- The deployable default remains `3033-v5`, matching migration `c42e8f1a9d73`.
- Editable v1-v4 documents adapt to and persist v5. Existing v5 documents remain v5.
- Explicit v6 documents remain fully supported and retain the fail-closed licensed-font check.
- Activating v6 requires a later product-catalog migration plus an approved read-only Calibri font
  layer and `CALIBRI_FONT_PATH`; those changes must be deployed and verified together.
- The continuous-HTML reader sidebar remains enabled for every template under ADR-0042, so this
  gate does not remove the HTML reader metadata or related-product links from v5 downloads.

## Consequences

Production can deploy the shared footer and reader changes without pretending Carlito is Calibri or
breaking report workflows. v6 is an explicit environment capability rather than an accidental
side effect of saving an older report. No stored finalized document is rewritten.
