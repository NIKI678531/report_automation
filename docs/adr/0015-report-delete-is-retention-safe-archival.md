# ADR-0015: Report delete is retention-safe archival

- Status: Accepted
- Date: 2026-08-24

## Context

Users need a delete action for draft and finalized reports so obsolete report versions no longer
appear in the working list. The execution specification also requires draft retention, at least
seven years of finalized-report lineage, immutable artifacts, and append-only audit events.

## Decision

`DELETE /api/v1/reports/{report_id}` is a soft delete. It changes the report status to `ARCHIVED`,
records the prior state in a `report.deleted` audit event, and excludes the report from the normal
report list. Related documents, snapshots, imports, render jobs, artifacts, and audit events are
not physically removed. The endpoint accepts the current report version for optimistic locking.

The UI labels the action **Delete report** because it removes the report from the user's working
list. Its confirmation message states that retained records and finalized outputs remain subject
to the records policy.

## Consequences

- Draft and finalized reports can both be removed from routine use without breaking lineage.
- A repeated delete remains safe because an already archived report is left unchanged.
- Permanent erasure, retention expiry, and archive restoration remain administrator lifecycle
  operations and are outside this feature.
