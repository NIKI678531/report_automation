# News providers and module CSV imports

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

Company News automatically ensures DA-Report candidates once when a mutable report has a valid active snapshot and no candidates. The window is the report month. It never auto-selects items into the report.

DA-Report has no news-to-security or news-to-product relation. `category=Corporate` means an item passed a regional holding check somewhere upstream; it does **not** prove that the item belongs to the current fund. This adapter therefore requires a unique title match against the active snapshot's controlled English/Traditional Chinese constituent names. Summary-only, ambiguous and unmatched items are excluded from automatic candidates.

Development can set `DA_REPORT_SQLITE_PATH`; with it unset the API falls back to `da_report.sqlite` in the repository root, then `~/Downloads/da_report.sqlite`. Production sets `DA_REPORT_OBJECT_URL` to a short-lived TOS/S3-compatible presigned URL and must set `DA_REPORT_SQLITE_SHA256`. The API downloads to `DA_REPORT_CACHE_DIR` on ephemeral disk, enforces the size limit, verifies SHA-256, atomically renames the completed file, and opens SQLite with both `mode=ro` and `PRAGMA query_only=ON`. The object URL is never included in provider errors.

Endpoints used:

- Constituent candidates: `GET /stable/news/stock`
- General candidates: `GET /stable/news/general-latest`

The report API derives constituent symbols from the active snapshot. General news is fetched only after the user selects the General scope. The default date range is the report month. Only title, snippet, source, URL, image URL, symbol, publication time, fetch evidence, and matching metadata are retained.

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


## Historical Performance CSV

Use `docs/historical-performance-template.csv`.

Required columns:

- `instrument_role`: `FUND` or `BENCHMARK`
- `instrument_code`
- `trade_date`: `YYYY-MM-DD` or `YYYYMMDD`
- `total_return_value`: positive official Total Return index level
- `series_type`: `Total Return`
- `currency`
- `source`

The server selects common trading-date endpoints and calculates 1M, 3M, 6M, and YTD returns. The browser does not calculate authoritative returns.

## Final Analytics CSV

Use `docs/templates/final-analytics-template.csv`. The file is a mixed long-form physical source that normalizes into separate logical datasets.

`CONSTITUENT` rows require security identity, date, price, currency, weight, sector, and period returns.

`KPI` rows support:

- `AUM`
- `DAILY_TURNOVER`

`CALENDAR` rows require `market`, `calendar_date`, `is_trading_day`, and `source`. Average turnover uses only authoritative trading days; duplicate dates fail and coverage below 95% blocks the calculation quality gate.

`EVENT` rows require `index_code`, `event_type=REBALANCE`, `effective_date`, and `source`; `announcement_date` is optional. The next rebalancing date is the earliest effective event after the report date for the configured constituent index. The server never guesses this date from a calendar rule.

`value_scale` is required for unambiguous constituent ratios:

- `DECIMAL`: `0.1015` means 10.15%
- `PERCENT`: `10.15` means 10.15%

Never infer the scale from the magnitude. This preserves valid returns above 100% and weights below 1%.

After validation and an approved reason, Apply creates a new immutable snapshot. Final Analytics then calculates Top 10, sector weights, Top/Bottom performers, AUM, average turnover, and holding count on the server. Existing snapshots are not changed.

## Mapping profiles and HSICS

CSV/XLSX ingestion selects exactly one approved `MappingProfile`. Profiles own header aliases, sheet/header scanning, explicit units, transforms and confirmed unlabelled columns. No unique profile results in `NEEDS_MAPPING`; the parser does not fall back to sheet names or fixed columns. Duplicate Bloomberg return groups are detected and only the group selected by the approved profile is imported.

Import a formal report-date HSICS master through `POST /api/v1/industry-master/import` using `docs/templates/industry-master-template.csv`. Codes are text and restored to widths 2/4/6 for Industry/Sector/Subsector. Effective ranges cannot overlap. Uploaded production snapshots without a bound effective HSICS master cannot be finalized; the old Bloomberg GICS table remains reference-only.
