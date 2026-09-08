# ADR 0012: Module-ready Final Analytics and bottom-performer order

- Status: Accepted
- Date: 2026-08-24

## Context

The HSTECH constituent identity, weight, 1M returns, and report-date-effective HSICS mapping can
all be valid while unrelated report inputs such as fund KPI or trading-calendar rows are still
pending. The calculation endpoint previously required the entire report snapshot to be valid, so
module 05 stayed empty even though every input needed by Top 10, the sector donut, and performer
rankings was already available.

The requested Bottom Performers presentation also places the smallest 1M return first. The prior
3033 reference layout reversed the selected bottom-three set for display.

## Decision

Module 05 is calculated and bound as soon as its approved constituent bundle and effective HSICS
mapping pass QC-001 through QC-004. Missing fund KPI and calendar data keeps the report in DRAFT.
The Portfolio Analysis presentation still emits its fixed three-row contract, with unavailable AUM
or turnover values shown as `N/A`; it never substitutes or infers a financial value. This makes a
missing upstream dataset visible instead of making the corresponding feature appear absent.
Full report readiness and finalization continue to require the complete snapshot.

Selecting any report month also repairs a legacy document whose active snapshot already has those
module inputs but whose Final Analytics section was never bound. If the existing snapshot and
document are already current, refresh remains idempotent and creates no extra version.

Top 10 remains ordered by weight descending. Top Performers remains ordered by 1M return
descending. Bottom Performers is now ordered by 1M return ascending, with weight descending and
security code ascending as deterministic tie-breakers.

## Consequences

- Users see valid module 05 outputs immediately after module 04 and HSICS inputs are ready.
- Switching to an older report month self-heals an empty legacy Final Analytics section.
- Partial calculations remain traceable through MetricValue and ModuleSnapshot records.
- An incomplete report cannot be finalized or presented as data-ready.
- The Bottom Performers display intentionally differs from the earlier 3033 PDF ordering.
