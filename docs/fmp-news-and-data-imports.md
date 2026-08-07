# FMP news and module CSV imports

## FMP configuration

FMP is called only by FastAPI. React never receives the API key.

Configure the runtime or approved secret store using `backend/.env.example` as the field reference. The key is sent in the `apikey` request header, never in the URL, audit log, exception text, or report artifact.

The key previously shared in chat must be rotated before live use.

Endpoints used:

- Constituent candidates: `GET /stable/news/stock`
- General candidates: `GET /stable/news/general-latest`

The report API derives constituent symbols from the active snapshot. General news is fetched only after the user selects the General scope. The default date range is the report month. Only title, snippet, source, URL, image URL, symbol, publication time, fetch evidence, and matching metadata are retained.

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
