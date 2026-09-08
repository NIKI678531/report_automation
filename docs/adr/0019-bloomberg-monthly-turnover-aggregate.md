# ADR 0019: Accept audited Bloomberg monthly turnover aggregates

- Status: Accepted
- Date: 2026-08-31

DA Report now publishes `market_monthly_turnovers` with the two inputs used by the approved
Bloomberg formula: monthly `INTERVAL_SUM` turnover and an authoritative trading-day count. When
the unified CDB daily-turnover view is not configured, the platform may combine CDB AUM with this
separately-lineaged monthly turnover observation and recompute Average Daily Turnover as
`total_turnover / trading_days`. It must not manufacture daily rows; the period must exactly match
the report month, the row must be unique, and the recomputed value must reconcile to the source
average within the precision of the upstream `DOUBLE` field. A configured unified CDB daily view
remains authoritative and supersedes the monthly aggregate.

This revises ADR 0013 only at the metric-source boundary: AUM and turnover may come from different
approved datasets because they are independent facts with separate lineage. Existing snapshots
and finalized reports remain immutable; refresh creates a new snapshot and document version.
