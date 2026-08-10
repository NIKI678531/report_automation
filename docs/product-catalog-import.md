# Product catalog import

The fund selector reads effective-dated records from `GET /api/v1/products`. Production entries must come from a business-approved UTF-8 CSV based on `docs/product-catalog-template.csv`.

## Required fields

- `product_code`, `ticker`, `name_en`
- `constituent_index_code`: defines the constituent universe, for example `HSTECH`
- `benchmark_instrument_code`: official Total Return instrument, for example `HSTECHN`
- `valid_from` in `YYYY-MM-DD` format
- `template_version`, `design_token_version`, `formula_profile`

Optional fields include Traditional Chinese name, the two index display names, currency, timezone, `valid_to`, active state, display order, and expected constituent count. The two index roles must not be collapsed into one physical field.

The pair `product_code + valid_from` identifies one effective product version. The importer validates the complete file before writing anything. Repeated versions, invalid dates, invalid booleans, or missing required fields reject the entire import.

## Import

The endpoint requires the administrator role:

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/products/import `
  -H "X-User-Role: ADMIN" `
  -H "X-Request-ID: approved-catalog-20260806" `
  -F "file=@docs/product-catalog-approved.csv;type=text/csv"
```

Imports upsert supplied effective versions and do not silently deactivate omitted products. A separate approved row with `is_active=false` or an applicable `valid_to` is required to remove a product from the current selector.

Reports snapshot the resolved product name, constituent index, return benchmark, template, and formula profile at creation time. Later catalog changes do not rewrite old reports.