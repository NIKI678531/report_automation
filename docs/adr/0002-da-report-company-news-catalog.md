# ADR-0002: DA-Report Company News catalog

Status: Accepted

## Context

V2.1 describes Company News as report-period news matched to the current constituent snapshot. The approved DA-Report SQLite snapshot also contains a curated Regional Corporate catalog spanning all covered ETFs. The business workflow now requires that catalog to appear immediately whenever the Company News module opens, including older backfilled records and records published after the selected report date.

Copying the full catalog into the commentary database on every visit would create duplicate mutable state and unnecessary storage. Requiring an active commentary snapshot would also prevent browsing before report data preparation is complete.

## Decision

- The Company News browser reads every row satisfying `news_sources.report_type = 'regional'` and `news_enrichments.category = 'Corporate'` directly from the approved read-only DA-Report SQLite snapshot.
- Catalog browsing is not filtered by commentary product, active constituent snapshot, report month, or report date.
- The default range is the full available snapshot, including upstream backfilled dates. A missing `published_at` uses `fetched_at` for ordering and is identified as such.
- The API applies server-side filters and opaque keyset pagination ordered by effective timestamp and DA item ID. Cursors are bound to the active filter and sort contract.
- Opening the module never copies catalog rows into the commentary database. A DA row is re-read by trusted external ID and materialized as a local `NewsItem` only when the user saves it into a report.
- Selected rows retain the DA external ID, source code, fetch time, region, sentiment, importance score, model, and catalog verification evidence. User title and summary edits remain versioned in `ReportDocument`.
- News before or after the report period may be selected. A selected item after `report_date` produces the non-blocking `NEWS_AFTER_REPORT_DATE` review warning.
- The existing constituent/provider fetch API remains available for compatibility and optional providers, but it is not the automatic Company News screen data path.

This intentionally deviates from the V2.1 current-constituent matching and report-month window described by FR-403 and the news freshness guidance in section 5.6.

## Consequences

The screen is useful before an active snapshot exists and reflects the approved DA snapshot on every entry. All 2,296 Regional Corporate rows in the 2026-08-07 snapshot are addressable without bulk duplication. The user must curate fund relevance and date appropriateness; the upstream Corporate classification does not imply relevance to the selected commentary product.

DA availability is required to browse or newly select catalog rows. Already materialized selections remain editable and renderable if DA is temporarily unavailable. Missing files, checksum failures, schema drift, invalid cursors, and query failures continue to fail closed with structured errors.

## Rollback

Restore the Company News frontend to `/news/candidates` and the provider `ensure` flow, then reinstate report-month selection validation. Existing materialized `NewsItem` and `ReportDocument` records remain valid and require no migration.
