# Advisory quality lifecycle without QA_BLOCKED

- Date: 2026-11-03
- Status: Accepted
- Supersedes in part: the V2.1 lifecycle table and ADR-0035
- Clarifies: ADR-0014

## Decision

`QA_BLOCKED` is removed from the runtime report lifecycle. Existing rows migrate to `EDITING`.
Once calculation has produced an editable document, failed data, calculation, content or release
checks remain visible through `quality_results`, the review API and audit events, but do not change
the report status and do not prevent editing, finalization or finalized-format downloads. The
review API therefore returns `ready=true`, an empty compatibility `blocking` list, and all failed
checks as advisories in `warnings` and `checks`.

This does not relax authorization, product scope, optimistic versions, finalized immutability,
upload/schema safety, fixed-finalized-version downloads, required compliance resources or actual
renderer failures. Incomplete inputs that cannot form an editable document remain `DRAFT`.

## Compatibility

Migration `f04c7b1e9a62` maps stored `QA_BLOCKED` rows to `EDITING` before narrowing the database
enum. Downgrade restores the enum member but cannot infer which later `EDITING` rows would
previously have been blocked. Historical migrations retain the old string so a database can still
be built from base.
