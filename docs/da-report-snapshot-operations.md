# DA-Report snapshot operations

The DA-Report database is an immutable, read-only external snapshot. It is not part of the commentary Alembic database and must never be copied into the container image or a PVC.

## Development

Set `DA_REPORT_SQLITE_PATH` to the absolute SQLite path. The provider opens it with SQLite URI `mode=ro` and applies `PRAGMA query_only=ON` to every connection.

```powershell
$env:DA_REPORT_SQLITE_PATH = "C:\Users\you\Downloads\da_report.sqlite"
$env:NEWS_PROVIDER = "DA_REPORT"
```

`GET /api/v1/news/providers` reports `DA_REPORT.configured=true` when the file is accessible.

## Production publication

1. Export and validate the DA-Report SQLite snapshot outside the application.
2. Upload it under an immutable, versioned TOS object key.
3. Record its byte size and SHA-256 in the release record.
4. Generate a short-lived TOS/S3-compatible presigned GET URL.
5. Inject `DA_REPORT_OBJECT_URL` and the mandatory `DA_REPORT_SQLITE_SHA256` through the approved secret/configuration store.
6. Set `DA_REPORT_CACHE_DIR=/tmp/commentary-da`; do not mount a persistent volume.
7. Roll the API deployment. Each pod downloads the object to a `.part` file, enforces `DA_REPORT_MAX_BYTES`, validates SHA-256, and atomically renames it before opening SQLite.

The presigned URL is never returned by the API or included in provider errors. The cache filename is derived from the checksum, so a new object version cannot overwrite a running version.

## Rotation and rollback

- Rotation: publish a new immutable key and checksum, then roll pods with the new URL/checksum pair.
- Rollback: restore the previous URL/checksum pair and roll pods. Existing reports retain their persisted news candidates and source metadata.
- Never replace an object in place under the same versioned key.

## Health and failure behavior

- Missing local file or object settings: `DA_REPORT_NOT_CONFIGURED`.
- Download transport failure: `DA_REPORT_DOWNLOAD_FAILED` (retryable).
- Oversized object: `DA_REPORT_TOO_LARGE`.
- SHA mismatch: `DA_REPORT_CHECKSUM_MISMATCH`; the partial file is deleted.
- Missing required SQLite columns: `DA_REPORT_SCHEMA_MISMATCH`.
- Query failure: `DA_REPORT_UNAVAILABLE`.

These failures affect only the DA news provider. The primary report API and business database remain available. Automatic Company News loading is idempotent per report, active snapshot, provider, scope and report-month window; manual Refresh remains available after recovery.

## Data boundary

DA-Report does not expose a durable news-to-security or news-to-product relation. `category=Corporate` alone is not sufficient for this application. Automatic candidates require a unique title match against names from the report's active constituent snapshot. Summary-only, ambiguous and unmatched records are not shown automatically.
