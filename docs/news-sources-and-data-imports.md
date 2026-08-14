# News providers and logical dataset imports

## Provider selection

News is fetched through a registry (`backend/app/integrations/news.py`), not by importing a vendor
module directly. Every adapter exposes the same
`fetch_news(scope, symbols, from_date, to_date, page, limit, client=None)` signature, returns the same
normalized candidate shape, and raises `NewsProviderError`, so nothing downstream knows which vendor
answered.

| Key | Vendor | Secret | Auth style |
|---|---|---|---|
| `DA_REPORT` | Approved DA-Report SQLite snapshot | local read-only path or TOS presigned URL + SHA-256 | none |
| `MARKETAUX` | Marketaux | `MARKETAUX_API_KEY` | `api_token` query parameter |

`POST /api/v1/reports/{id}/news/candidates/fetch` takes an optional `provider` field; omitting it uses
`NEWS_PROVIDER` (default `DA_REPORT`). `GET /api/v1/news/providers` reports which providers hold a
credential in this environment — the boolean only, never the credential. An unknown key returns 422
`NEWS_PROVIDER_UNKNOWN` before any outbound call is made.

Each provider gets its own audit action, derived from the key: `news.da_report_fetched`,
`news.marketaux_fetched`. Manual entries stay `news.manually_added`.

## DA-Report configuration

The Company News screen uses `GET /api/v1/reports/{id}/news/catalog`. Every visit reads the approved SQLite snapshot directly and returns all `regional + Corporate` records through filter-bound keyset pagination. It does not require an active commentary snapshot and does not filter by fund, report month or report date. The first page includes source, sentiment, importance and date facets; keyword, source, sentiment, importance, date and sort filters execute on the server.

Catalog browsing never bulk-copies DA rows into the commentary database. Saving a selection sends `provider=DA_REPORT` plus the DA `external_id`; the backend re-reads that row, verifies that it remains a Regional Corporate record, then creates or reuses the local `NewsItem`. Already materialized selections subsequently use the local ID, so editing and rendering remain available during a DA outage. Manual entries and selected ordering remain report-specific.

The catalog intentionally includes the complete upstream date range, including backfilled records and items after the report date. A null `published_at` falls back to `fetched_at` and is labelled accordingly. Cross-period selection is allowed; a selected item later than `report_date` produces a non-blocking Review warning. See [ADR-0002](adr/0002-da-report-company-news-catalog.md).

`category=Corporate` means an item passed an upstream regional holding check; it does **not** prove that the item belongs to the selected commentary fund. Fund relevance is a user curation decision in this catalog workflow.

Development can set `DA_REPORT_SQLITE_PATH`; with it unset the API falls back to `da_report.sqlite` in the repository root, then `~/Downloads/da_report.sqlite`. Production sets `DA_REPORT_OBJECT_URL` to a short-lived TOS/S3-compatible presigned URL and must set `DA_REPORT_SQLITE_SHA256`. The API downloads to `DA_REPORT_CACHE_DIR` on ephemeral disk, enforces the size limit, verifies SHA-256, atomically renames the completed file, and opens SQLite with both `mode=ro` and `PRAGMA query_only=ON`. The object URL is never included in provider errors.

The legacy `POST /api/v1/reports/{id}/news/candidates/fetch` path remains available for constituent-scoped DA matching and optional providers. Its snapshot/window idempotency and report-month constraints are unchanged, but the Company News screen no longer invokes it automatically.

## Marketaux configuration

Endpoint used: `GET /v1/news/all`, for both scopes. `CONSTITUENTS` adds `symbols` plus
`must_have_entities=true`, so a holding merely name-checked in a market round-up does not enter the
constituent feed. Marketaux pages are 1-based; the shared interface is 0-based, and the adapter
converts. A single page is capped at 100 articles by the vendor.

Marketaux tags an article with every entity it mentions, so one article can carry several symbols. The
article is emitted once and bound to the **requested** symbol it matches — an item tagged `AAPL` first
and `0700.HK` second still binds to `0700.HK` when Tencent is the constituent asked for. The full
matched set is kept in `metadata_json.matched_symbols`.

### Documented deviation from the header-only credential rule

**Marketaux has no header authentication.** `api_token` is a query parameter or nothing, so the
credential necessarily appears in the outbound request URL. The rest of the rule is enforced and
tested (`backend/tests/test_marketaux_news.py`):

- No URL ever enters an exception message, audit record, log line, normalized candidate or artifact.
- Vendor error bodies are surfaced for diagnosis but passed through `_redact` first, because Marketaux
  quotes request parameters back in them.
- The httpx failure paths re-raise with `from None`: the chained exception holds `.request.url`, which
  would otherwise carry the token into every traceback downstream.

Prefer a header-authenticated provider where the choice exists. If Marketaux is used in a deployed
environment, treat the token as URL-exposed: it will reach the vendor's own access logs and any
intermediate proxy, so it must be rotated on the same schedule as any other transport-visible secret.


## Monthly report data inputs

The product workspace exposes one report-level upload. Historical Performance and fund-level Portfolio Analysis data are loaded automatically from the immutable DA-Report SQLite snapshot; Final Analytics is derived from the active constituent snapshot. Compatibility API slots remain readable for existing snapshots, but are not shown as user inputs.

| Slot | Template / accepted source | Required |
|---|---|---|
| `constituent_performance` | `docs/templates/constituent-performance-template.csv` | yes; only report upload |
| `total_return_series` | DA-Report SQLite `total_return_series` | automatic |
| `fund_kpi_daily` | DA-Report SQLite `fund_kpi_daily` | automatic |
| `trading_calendar` | DA-Report SQLite `trading_calendar` | automatic |
| `index_events` | DA-Report SQLite `index_events` | automatic; rows optional |
| `industry_master` | centrally managed `docs/templates/industry-master-template.csv` | yes |

`constituent_performance` carries `index_code`, as-of date, identity, price/currency, percent weight, HSICS industry code, a common period end, each period start, and either an explicit percent return or a missing reason. Percent fields are normalized to ratios by the backend. Once this file, automatic datasets and one report-date-effective HSICS master are present, the backend calculates Historical Performance and Final Analytics and persists dataset-specific MetricValue and ModuleSnapshot lineage. The browser does not calculate authoritative values.

The first constituent application uses **Use this data** and requires no reason. Replacing it requires a replacement reason. Apply, replace, clear and automatic refresh all create new snapshots; automatic refresh preserves the effective constituent upload while replacing every SQLite-owned dataset.

## Mapping profiles and HSICS

CSV/XLSX ingestion selects exactly one approved `MappingProfile`. Profiles own header aliases, sheet/header scanning, explicit units, transforms and confirmed unlabelled columns. No unique profile results in `NEEDS_MAPPING`; the parser does not fall back to sheet names or fixed columns. Duplicate Bloomberg return groups are detected and only the group selected by the approved profile is imported.

Import a formal report-date HSICS master through `POST /api/v1/industry-master/import` using `docs/templates/industry-master-template.csv`. Codes are text and restored to widths 2/4/6 for Industry/Sector/Subsector. Effective ranges cannot overlap. Uploaded production snapshots without a bound effective HSICS master cannot be calculated or finalized. The old Bloomberg GICS mapping and manual sector-override upload paths are retired.
