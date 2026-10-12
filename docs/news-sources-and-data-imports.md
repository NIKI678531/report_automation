# News providers and logical dataset imports

## Provider selection

News is fetched through the registry (`backend/app/integrations/news.py`). `DA_REPORT` is the only
supported provider (ADR-0031). Its adapter accepts
`fetch_news(scope, symbols, from_date, to_date, page, limit, constituents=None)`, returns normalized
candidates, and raises `NewsProviderError` when the source is unavailable.

| Key | Source | Configuration |
|---|---|---|
| `DA_REPORT` | Approved DA-Report data | Production read-only MySQL; UAT/local SQLite snapshot |

`POST /api/v1/reports/{id}/news/candidates/fetch` takes an optional `provider` field; omitting it uses
`NEWS_PROVIDER` (keep it set to `DA_REPORT`). `GET /api/v1/news/providers` reports whether the DA source
is configured — the boolean only, never its credentials. An unknown or retired key returns 422
`NEWS_PROVIDER_UNKNOWN` before any outbound call is made.

DA fetches use the audit action `news.da_report_fetched`. Manual entries stay `news.manually_added`.

## DA-Report configuration

The Company News screen uses `GET /api/v1/reports/{id}/news/catalog`. Every visit reads the approved DA source directly and returns `regional + Corporate` records through filter-bound keyset pagination. It does not require an active commentary snapshot. The workbench defaults `from_date` and `to_date` to January 1 and December 31 of the report year; API clients may still query another window or the complete catalog. The response exposes the report-month constituent company list from a valid same-context snapshot when available; otherwise it reads the latest CDB index observation within the selected report month without creating a snapshot. A configured expected constituent count must match before the `3033.HK constituents` scope is enabled. CDB failure or incomplete membership disables only that scope and does not block the news catalog.

The UI provides `All companies` (default) and `3033.HK constituents`. The latter sends `company_scope=CONSTITUENTS` and matches the title against the union of all 30 companies' controlled English, Traditional Chinese, derived Simplified Chinese and full-ticker aliases; summary-only mentions are excluded. Its sentiment control has the fixed order `All / Bullish / Neutral / Bearish` (`bull`, `neutral`, `bear`) and does not display facet counts; unknown sentiments are visible only under All. The workbench no longer exposes or sends Importance, although the backend parameter and facet remain compatible for other API clients. Keyword, scope, source, sentiment, date and sort filters execute together on the server, and the scope is bound into the keyset cursor. Clearing filters restores the report-year date range, which is not itself shown as an active filter. The legacy `company=<security_code>` contract remains available to API clients, but combining `company` and `company_scope` returns 422.

Catalog browsing never bulk-copies DA rows into the commentary database. Saving a selection sends `provider=DA_REPORT` plus the DA `external_id`; the backend re-reads that row, verifies that it remains a Regional Corporate record, then creates or reuses the local `NewsItem`. Already materialized selections subsequently use the local ID, so editing and rendering remain available during a DA outage. Manual entries and selected ordering remain report-specific. Rendered HTML, PDF and DOCX show the publisher name only; publication time and source URL remain stored for audit and visible in the editing workbench.

The catalog API continues to support the complete upstream date range, including backfilled records and items after the report date, while the workbench starts with the report-year window defined by [ADR-0034](adr/0034-company-news-annual-sentiment-filters.md). A null `published_at` falls back to `fetched_at` and is labelled accordingly. Cross-period selection is allowed; a selected item later than `report_date` produces a non-blocking Review warning. See [ADR-0002](adr/0002-da-report-company-news-catalog.md).

`category=Corporate` means an item passed an upstream regional holding check; it does **not** prove that the item belongs to the selected commentary fund. Fund relevance is a user curation decision in this catalog workflow.

Production configures `DA_REPORT_DATABASE_URL` to read the DA-Report MySQL database directly (ADR-0030). This is separate from the commentary `DATABASE_URL`: it never receives application migrations or writes. TLS certificate/hostname validation, read-only transactions, a bounded pool and query timeouts are enforced. Set `DA_REPORT_MYSQL_SSL_CA` to the approved CA bundle; the Production image includes AWS RDS ap-east-1 trust roots. No object URL or SQLite checksum is required in this mode. MySQL failure is surfaced without falling back to a stale snapshot.

UAT is not authorized to use the supplied Production connection and leaves `DA_REPORT_DATABASE_URL` empty. Without a MySQL URL, development can set `DA_REPORT_SQLITE_PATH`; only LOCAL auth can probe the repository root and Downloads fallback paths. A remotely supplied SQLite snapshot still uses `DA_REPORT_OBJECT_URL` plus `DA_REPORT_SQLITE_SHA256`, with size/checksum verification and a read-only temporary cache. Connection URLs and credentials are excluded from provider errors.

The legacy `POST /api/v1/reports/{id}/news/candidates/fetch` path remains available for constituent-scoped DA matching. Its snapshot/window idempotency and report-month constraints are unchanged, but the Company News screen no longer invokes it automatically.

## Monthly report data inputs

The product workspace exposes a constituent CSV override separately from automatic loading. Historical Performance comes from the read-only CDB warehouse. Page 04 can load HSTECH constituent identity from CDB and its returns from FMP without a CSV; Final Analytics is derived from the active constituent snapshot. Compatibility API slots remain readable for existing snapshots.

| Slot | Template / accepted source | Required |
|---|---|---|
| `constituent_performance` / `index_constituents` | report-month CDB HSTECH identity, price, weight and HSICS data; approved CSV is an explicit override | automatic |
| `constituent_returns` | FMP dividend-adjusted EOD history; approved upload remains an explicit override | automatic |
| `total_return_series` | CDB fund/index performance views (`CO-CHST`, listed `CLS00178`, `HSTECHN Index`) | automatic |
| `fund_kpi_daily` | CDB fund-level AUM plus the configured unified daily KPI view when available | automatic |
| `trading_calendar` | Configured unified CDB daily KPI/calendar view | automatic |
| `fund_turnover_monthly` | DA-Report `market_monthly_turnovers` (Production MySQL; SQLite compatibility); audited fallback for completed months | automatic |
| `index_events` | DA-Report `index_events` (Production MySQL; SQLite compatibility) | automatic; rows optional |
| `industry_master` | centrally managed `docs/templates/industry-master-template.csv` | yes |

The automatic Page 04 path reads the HSTECH identity, ticker, names, price/currency, weight and HSICS codes from CDB at the same effective date used by Historical Performance. The backend then maps each `.HK` ticker (falling back to a zero-padded local code), obtains dividend-adjusted FMP EOD prices through the selected report date, resolves common 1M/3M/6M/YTD boundaries and stores decimal-ratio returns. Exact source observations and dates are retained in dataset lineage. An approved identity or return upload remains supported and is never silently overwritten. Once the identity source, return source, other automatic datasets and one report-date-effective HSICS master are present, the backend calculates Historical Performance and Final Analytics and persists dataset-specific MetricValue and ModuleSnapshot lineage. The browser does not calculate authoritative values.

The first constituent CSV application uses **Use this data** and requires no reason. Replacing it requires a replacement reason. Apply, replace, clear and automatic refresh all create new snapshots; automatic refresh preserves an effective constituent upload, otherwise it uses CDB identity before loading FMP returns.

## Mapping profiles and HSICS

CSV/XLSX ingestion selects exactly one approved `MappingProfile`. Profiles own header aliases, sheet/header scanning, explicit units, transforms and confirmed unlabelled columns. No unique profile results in `NEEDS_MAPPING`; the parser does not fall back to sheet names or fixed columns. Duplicate Bloomberg return groups are detected and only the group selected by the approved profile is imported.

Import a formal report-date HSICS master through `POST /api/v1/industry-master/import` using `docs/templates/industry-master-template.csv`. Codes are text and restored to widths 2/4/6 for Industry/Sector/Subsector. Effective ranges cannot overlap. Uploaded production snapshots without a bound effective HSICS master cannot be calculated or finalized. The old Bloomberg GICS mapping and manual sector-override upload paths are retired.
