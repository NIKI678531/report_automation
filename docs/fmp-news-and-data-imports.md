# News providers and module CSV imports

## Provider selection

News is fetched through a registry (`backend/app/integrations/news.py`), not by importing a vendor
module directly. Every adapter exposes the same
`fetch_news(scope, symbols, from_date, to_date, page, limit, client=None)` signature, returns the same
normalized candidate shape, and raises `NewsProviderError`, so nothing downstream knows which vendor
answered.

| Key | Vendor | Secret | Auth style |
|---|---|---|---|
| `FMP` | Financial Modeling Prep | `FMP_API_KEY` | `apikey` request header |
| `MARKETAUX` | Marketaux | `MARKETAUX_API_KEY` | `api_token` query parameter |

`POST /api/v1/reports/{id}/news/candidates/fetch` takes an optional `provider` field; omitting it uses
`NEWS_PROVIDER` (default `FMP`). `GET /api/v1/news/providers` reports which providers hold a credential
in this environment — the boolean only, never the credential. An unknown key returns 422
`NEWS_PROVIDER_UNKNOWN` before any outbound call is made.

Each provider gets its own audit action, derived from the key: `news.fmp_fetched`,
`news.marketaux_fetched`. Manual entries stay `news.manually_added`.

## FMP configuration

FMP is called only by FastAPI. React never receives the API key.

Configure the runtime or approved secret store using `backend/.env.example` as the field reference. The key is sent in the `apikey` request header, never in the URL, audit log, exception text, or report artifact.

The key previously shared in chat must be rotated before live use.

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

Use `docs/final-analytics-template.csv`. The file is a mixed long-form dataset.

`CONSTITUENT` rows require security identity, date, price, currency, weight, sector, and period returns.

`KPI` rows support:

- `AUM`
- `DAILY_TURNOVER`

`value_scale` is required for unambiguous constituent ratios:

- `DECIMAL`: `0.1015` means 10.15%
- `PERCENT`: `10.15` means 10.15%

Never infer the scale from the magnitude. This preserves valid returns above 100% and weights below 1%.

After validation and an approved reason, Apply creates a new immutable snapshot. Final Analytics then calculates Top 10, sector weights, Top/Bottom performers, AUM, average turnover, and holding count on the server. Existing snapshots are not changed.
