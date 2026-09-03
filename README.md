# Monthly Commentary Report Platform

Implementation of the V2.1 Agent Execution Specification. The platform uses a React + TypeScript frontend, a Python FastAPI backend, an immutable report document, and shared design tokens for HTML, PDF, and editable DOCX output.

## Quick start

```powershell
python -m venv .venv
\.\.venv\Scripts\python -m pip install -e ".\backend[dev,render]"
npm ci
Push-Location backend
..\.venv\Scripts\python -m alembic upgrade head
Pop-Location
```

If `python` is not available on `PATH` but `uv` is installed, replace the first two commands with:

```powershell
uv venv --python 3.12 .venv
uv pip install --link-mode copy --python .\.venv\Scripts\python.exe -e ".\backend[dev,render]"
```

Start the API in one terminal:

```powershell
$env:TASK_MODE = "EAGER"
\.\.venv\Scripts\python -m uvicorn app.main:app --app-dir backend --reload --port 8000
```

Start the web application in a second terminal:

```powershell
npm run dev
```

The web application is served at `http://localhost:5173` and proxies `/api` to FastAPI.

For a checkout inside OneDrive, keep the SQLite database available offline. If an existing
`var/commentary.db` returns `disk I/O error`, preserve it and set `DATABASE_URL` to a new local SQLite
file before running both Alembic and the API.

Local development runs with `AUTH_MODE=LOCAL`, where the caller's identity comes from the
`X-User-Role`, `X-User-ID` and `X-Product-Scope` request headers and defaults to an unrestricted
administrator. That is a workstation convenience, not security — see
[Deployment](#deployment) before exposing the API to anyone else.

## Deployment

Production runs on MySQL 8, object storage and a validated access token. The application refuses to
start otherwise: `Settings.deployment_problems()` is evaluated before the FastAPI app is built, and
a process outside `AUTH_MODE=LOCAL` will not boot with the repository's default signing secret, an
unpinned token issuer, the fixture lane enabled, a SQLite `DATABASE_URL`, or artifacts still
configured to land on container-local disk. Each refusal is logged by name.

Copy the two templates and fill them in — neither has a working default, and `compose.yaml`
references its secrets as `${VAR:?message}` so a missing one stops `docker compose up` with that
message instead of publishing a database with a known password:

- [`.env.example`](.env.example) → `.env` beside `compose.yaml`: MySQL passwords, `DOWNLOAD_SECRET`,
  the Entra settings, `CORS_ALLOW_ORIGINS`, pool and upload sizing.
- [`backend/.env.example`](backend/.env.example) → `backend/.env`: service settings — news provider,
  CDB views, FMP, and the full list of database and token options with their defaults.

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"   # DOWNLOAD_SECRET
docker compose up --build
```

Then check the environment before anyone depends on it:

```powershell
.\.venv\Scripts\python scripts/check_deployment.py --token "$env:ACCESS_TOKEN"
.\.venv\Scripts\python scripts/check_deployment.py --env-file deploy\production.env   # from anywhere
```

The preflight runs the same checks that would refuse startup, then the ones the application only
reaches at first use: the database is connectable and at head, every text column is utf8mb4, the
tenant's key endpoint answers, the artifact bucket is addressable, and — with `--token` — a real
access token resolves to the subject, role and product scope the API will act on. The token is
never logged. A non-zero exit means the environment must not serve traffic.

`--env-file` checks the environment a file describes rather than the current one. The production
settings exist as a file long before any production process reads them, and every guard is a pure
function of those settings, so a workstation can prove the deployment configuration is clean
without being the deployment.

Connecting the API to Microsoft Entra ID — app registration, the four app roles, how product scope
is carried, and what each rejection `error_code` means — is documented in
[docs/entra-setup.md](docs/entra-setup.md).

The stack is `db` (MySQL 8.4) + `redis` + `api` + `worker` (Celery) + `web` (nginx on
`http://localhost:8080/`, reaching the API same-origin at `/api/v1`). `web` waits for the API's
health check, so a rolling deploy cannot route traffic at an instance whose migrations are still
running.

Points worth knowing before the first deploy:

- **utf8mb4 everywhere.** The server starts with `--character-set-server=utf8mb4` and the connection
  string carries `?charset=utf8mb4`. MySQL's legacy three-byte `utf8` truncates the Traditional and
  Simplified Chinese a report is made of.
- **Token validation needs an extra.** `AUTH_MODE=ENTRA` requires `pip install -e "./backend[entra]"`
  (PyJWT with cryptography). Its absence fails the boot rather than the first authenticated request.
  The published image already carries `[render,entra,storage]`, so switching modes is configuration
  only — nothing has to be installed into a running container.
- **Artifacts belong in object storage.** There is no persistent volume, so `STORAGE_BACKEND=LOCAL`
  means every rendered report is lost at the next restart and invisible to the other replicas. Set
  `STORAGE_BACKEND=S3` plus `S3_BUCKET` (Volcengine TOS, MinIO and AWS S3 all speak this API) in
  **both** the API and the worker — the worker writes the artifact the API later serves.
- **Pool settings track the database.** Keep `DB_POOL_RECYCLE_SECONDS` below the server's
  `wait_timeout`, or the pool eventually hands out a connection MySQL has already closed.
- **Upload limits are enforced twice.** Keep `UPLOAD_MAX_BYTES` at or below nginx's
  `client_max_body_size` in `frontend/nginx.conf`; a 413 from the proxy carries none of the
  structured error envelope the UI reads.
- **Verify the migrations against MySQL, not just SQLite.** Point `TEST_MYSQL_URL` at a throwaway
  schema and run `backend/tests/test_migrations.py`; it downgrades the target to base first, so it
  must not be a database with data in it.

## Product catalog

The report title is an effective-dated fund selector backed by the API product catalog. The initial migration contains only the approved 3033 project baseline. Import the business-approved current fund list using [docs/product-catalog-import.md](docs/product-catalog-import.md); funds are not hardcoded in React.

The workspace is organized around six report modules: Month in Review, Historical Performance, Company News, Constituent Performance, Final Analytics, and Footnotes & Disclosures. Snapshot loading, recalculation, assisted drafting, review, and finalization now live in their relevant module or report stage.

The first module defaults to `<Month> in Review` in `3033-v2`. Its report title and every 12-column block title are editable and versioned in the same `ReportDocument` used by HTML, PDF, and DOCX. The workspace navigation displays physical PDF pages (`01`, `01`, `02`, `03`, `04`); Footnotes & Disclosures shows `01/03/04` because its content is embedded across those pages.

Final Analytics takes its displayed month and fund ticker from the canonical report document. Changing the top report date navigates to the latest report for that fund and date, or opens the create-report state when none exists. Company News loads HKT report-month candidates matched to the active constituent snapshot.

Report creation loads Historical Performance directly from the read-only CDB warehouse. Page 04 can load report-month HSTECH identity, closing price, weight and HSICS codes from CDB, then calculate 1M/3M/6M/YTD returns from FMP dividend-adjusted EOD history without waiting for a CSV; a constituent CSV remains a separate explicit override. Applying or refreshing data creates a new immutable mixed-source snapshot and derives Final Analytics on the server. Finalization generates HTML, PDF and DOCX outputs with download controls. See [docs/news-sources-and-data-imports.md](docs/news-sources-and-data-imports.md).

## Verification

```powershell
\.\.venv\Scripts\python -m pytest backend/tests
npm test
npm run build
```

The checked-in 3033 visual baseline is under `backend/tests/fixtures/3033_202606`.
`scripts/verify_visual.py` selects the most recently generated PDF and records page-4 text and donut-presence checks in `var/artifacts/visual/latest/manifest.json` in addition to the strict pixel comparison.
