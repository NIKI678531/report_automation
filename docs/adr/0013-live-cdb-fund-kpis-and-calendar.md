# ADR 0013: Live CDB fund KPIs and trading calendar

- Status: Accepted
- Date: 2026-08-24
- Supersedes: the fund-KPI and trading-calendar source decision in ADR-0003

## Context

Portfolio Analysis still obtained AUM and daily turnover from the optional DA-Report SQLite
snapshot. When that file was absent, the fixed AUM and Average Daily Turnover rows correctly showed
`N/A`, even though the production CDB connection was available.

The configured ADS database was inspected through its read-only identity. For 3033, fund-level
`actual_nav_fc` in `view_ads_busi_valuation_nav_fund_level_exposure_1_f_p` reconciles to the approved
2026-06-30 AUM of HKD 67,536.55 million. The available ADS views do not expose secondary-market ETF
turnover or a complete trading-calendar contract; primary-market subscription/redemption orders are
not an equivalent measure and must not be substituted.

## Decision

While the unified contract is being provisioned, `DATAWAREHOUSE_FUND_AUM_VIEW` points to the
existing approved fund-level valuation view. The connector resolves the listed 3033 share class to
its fund `tradar_code`, selects the latest non-null `actual_nav_fc` in the report month not later
than `report_date`, and records the effective date, record key, query window and checksum. This
bridge owns AUM only: it removes legacy automatic KPI/calendar rows and emits a blocking finding
for the absent turnover contract, so sources are not silently mixed.

Production may configure `DATAWAREHOUSE_FUND_KPI_VIEW` after the data owner provisions an approved
read-only view with one row per product and natural date. Its required fields are:

```text
product_code, as_of_date, is_trading_day,
aum, aum_currency, aum_unit,
daily_turnover, turnover_currency, turnover_unit,
source, updated_at
```

The view must be unique on `(product_code, as_of_date)`. Calendar rows must exist for every natural
date in the requested window; non-trading dates have `is_trading_day=false`, and missing trading-day
turnover remains `NULL`. Amounts are non-negative and carry explicit currency and unit.

When configured, this view is authoritative for the `fund_kpi_daily` and `trading_calendar` logical
datasets. The connector validates the identifier, schema, calendar completeness, uniqueness,
amounts, currencies and units before returning data. A failure removes both legacy DA-Report
datasets and creates a blocking provider finding; it never silently mixes sources. Explicit upload
overrides retain their existing dataset-level precedence.

AUM uses the latest valid observation in the report month not later than `report_date`, independent
of the constituent effective date. Average Daily Turnover is the arithmetic mean of non-null daily
turnover observations on authoritative trading days. Coverage below 95% blocks finalization;
coverage from 95% through less than 100% also creates a warning. Drafts may display the calculated
partial-period value with its coverage and latest observation date.

## Consequences

- Existing snapshots and finalized artifacts remain immutable; refresh creates new snapshots.
- The 2026-06-30 regression must display AUM `67,536.55 million` and, once the approved view is
  populated, Average Daily Turnover `12,882 million`.
- Future month-end reports can display provisional month-to-date facts but remain blocked while
  coverage is below the release threshold.
- Until the unified view is provisioned and configured, CDB `actual_nav_fc` supplies AUM while
  Average Daily Turnover remains unavailable and blocks finalization. No turnover is fabricated
  from closing price × volume, fund sale orders, or a test fixture.
- Credentials remain environment secrets and are excluded from logs, snapshots and artifacts.
