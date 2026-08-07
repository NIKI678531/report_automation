# Monthly Commentary Report Platform

Implementation of the V2.1 Agent Execution Specification. The platform uses a React + TypeScript frontend, a Python FastAPI backend, an immutable report document, and shared design tokens for HTML, PDF, and editable DOCX output.

## Repository layout

```
backend/    FastAPI service: app/, migrations/, tests/ (with the golden fixtures) and design tokens
frontend/   React + TypeScript editor, preview and admin surface
docs/       ADRs, the V2.1 specification, import guides and CSV templates
scripts/    Operational one-offs such as visual QA
var/        Runtime products only (rendered output, QA evidence, local databases) — gitignored
```

`DESIGN.md` is the authoritative UI specification, `CLAUDE.md` the working guide for Claude Code, and
`AGENTS.md` the non-negotiable execution constraints distilled from the V2.1 specification.

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".\backend[dev,render]"
npm install
Push-Location backend
..\.venv\Scripts\python -m alembic upgrade head
Pop-Location
npm run dev
```

Run the API separately with:

```powershell
.\.venv\Scripts\python -m uvicorn app.main:app --app-dir backend --reload --port 8000
```

The web application is served at `http://localhost:5173` and proxies `/api` to FastAPI.

## Product catalog

The report title is an effective-dated fund selector backed by the API product catalog. The initial migration contains only the approved 3033 project baseline. Import the business-approved current fund list using [docs/product-catalog-import.md](docs/product-catalog-import.md); funds are not hardcoded in React.

The workspace is organized around six report modules: Month in Review, Historical Performance, Company News, Constituent Performance, Final Analytics, and Footnotes & Disclosures. Snapshot loading, recalculation, assisted drafting, review, and finalization now live in their relevant module or report stage.

The first module is displayed and rendered as `Review` in `3033-v2`. It uses a validated 12-column drag-and-resize layout with controlled rich text. Company News can import report-scoped FMP candidates, while Historical Performance and Final Analytics accept auditable CSV inputs. See [docs/fmp-news-and-data-imports.md](docs/fmp-news-and-data-imports.md).

## Verification

```powershell
.\.venv\Scripts\python -m pytest backend/tests
npm test
npm run build
```

The checked-in 3033 visual baseline is under `backend/tests/fixtures/3033_202606`.
