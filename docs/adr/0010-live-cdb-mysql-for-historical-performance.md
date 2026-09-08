# ADR 0010: Live read-only CDB MySQL for Historical Performance

- Status: Accepted
- Date: 2026-08-21
- Supersedes: the production TOS/SQLite transport decision in ADR-0006

## Context

ADR-0006 selected the warehouse's precomputed 1M, 3M, 6M and YTD fields for Page 02, but its
initial adapter read an exported SQLite copy. The V2.1 execution specification names CDB as the
production fact source and requires private TLS, a dedicated read-only identity, parameterized SQL,
view whitelisting and timeouts.

The production CDB contract was verified against the configured ADS database. The listed 3033 share
class maps to `CO-CHST / CLS00178 / 3033 HK EQUITY`, while `CLS00199` is unlisted and excluded. The
fund and `HSTECHN Index` performance views contain matching daily rows from 2024-01-02 through
2026-08-20 at the time of verification.

## Decision

When all `DATAWAREHOUSE_MYSQL_*` settings are present, Page 02 queries the configured CDB views over
TLS using SQLAlchemy and PyMySQL. The connector:

- sets the database session to read-only and applies a query execution timeout;
- validates configured view names and their required columns before reading data;
- resolves the unique listed share class from the product ticker, then filters performance rows by
  its `tradar_code` and `class_id`;
- filters both views independently, then matches fund and benchmark rows on `tradar_code`,
  `class_id` and `trade_date` to avoid an expensive full-view database join;
- selects the latest common observation within the report's selected month; and
- stores source view names, record keys, query window, field mapping and checksums in snapshot
  lineage without storing connection credentials.

SQLite/TOS remains an offline development and test fallback only when no MySQL host is configured.
A partial MySQL configuration is a blocking error and never silently falls back to stale SQLite.
Physical view names remain deployment configuration rather than business-code assumptions.

## Consequences

- Selecting any report month covered by the CDB views returns the corresponding latest common fund
  and benchmark observation automatically.
- A report month may use an earlier trading day within that same month, such as 2026-08-20 for an
  August 2026 report that is refreshed before month-end; it never uses a prior month's value.
- Credentials must be injected by the company secret store. They are not committed, logged, placed
  in snapshots or exposed to the frontend.
- Missing mappings, schema drift, unavailable months and query failures remain blocking provider
  findings rather than zero-filled output.
