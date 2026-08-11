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

## Product catalog

The report title is an effective-dated fund selector backed by the API product catalog. The initial migration contains only the approved 3033 project baseline. Import the business-approved current fund list using [docs/product-catalog-import.md](docs/product-catalog-import.md); funds are not hardcoded in React.

The workspace is organized around six report modules: Month in Review, Historical Performance, Company News, Constituent Performance, Final Analytics, and Footnotes & Disclosures. Snapshot loading, recalculation, assisted drafting, review, and finalization now live in their relevant module or report stage.

The first module defaults to `<Month> in Review` in `3033-v2`. Its report title and every 12-column block title are editable and versioned in the same `ReportDocument` used by HTML, PDF, and DOCX. The workspace navigation displays physical PDF pages (`01`, `01`, `02`, `03`, `04`); Footnotes & Disclosures shows `01/03/04` because its content is embedded across those pages.

Final Analytics takes its displayed month and fund ticker from the canonical report document. Changing the top report date navigates to the latest report for that fund and date, or opens the create-report state when none exists. Company News loads HKT report-month candidates matched to the active constituent snapshot. Historical Performance, constituents and analytics use separate auditable logical-dataset slots; the last required slot automatically triggers server calculations. Finalization generates HTML, PDF and DOCX outputs with download controls. See [docs/news-sources-and-data-imports.md](docs/news-sources-and-data-imports.md).

## Verification

```powershell
\.\.venv\Scripts\python -m pytest backend/tests
npm test
npm run build
```

The checked-in 3033 visual baseline is under `backend/tests/fixtures/3033_202606`.
