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

The web application is a Webpack Federation remote (`fundCmtAuto` / `./App`) served on port **3030**. Its entry is `/remote/fund-cmt-auto/remoteEntry.js`; standalone development opens `http://localhost:3030/remote/fund-cmt-auto/`. The namespaced API is proxied to FastAPI. See [host integration](k8s/REMOTE.md) for registration and platform proxy settings. Use Node 24.19+ and npm workspaces.

For a checkout inside OneDrive, keep the SQLite database available offline. If an existing
`var/commentary.db` returns `disk I/O error`, preserve it and set `DATABASE_URL` to a new local SQLite
file before running both Alembic and the API.

Local development runs with `AUTH_MODE=LOCAL`, where the caller's identity comes from the
`X-User-Role`, `X-User-ID` and `X-Product-Scope` request headers and defaults to an unrestricted
administrator. That is a workstation convenience, not security — see
[Deployment](#deployment) before exposing the API to anyone else.

## Deployment

UAT / Production use the company remote-application conventions: one backend image (API with synchronous rendering/translation)
and one nginx-unprivileged frontend image, external MySQL, and plain YAML in `k8s/uat`
and `k8s/prd`. The existing remote application platform handles access; there is no standalone
Ingress, domain/certificate setup or application login in this deployment. `AUTH_MODE=REMOTE`
uses the shared `remote-app` actor while retaining MySQL and signing-key guards.

See [the deployment manual](k8s/README.md), [runbook](k8s/RUNBOOK.md) and
[release checklist](k8s/CHECKLIST.md). Build manifests are `docker-compose.uat.yml` and
`docker-compose.prd.yml`; copy the matching `.env.<env>.example` for Secret generation.
The optional local image-validation stack is `compose.yaml` (Docker Compose >= 2.30); its
MySQL data is disposable; configure its credentials and the download signing key in `.env`.
`TASK_MODE=EAGER` requires no Redis or separate worker; render/translation requests wait for completion.
See [ADR-0028](docs/adr/0028-synchronous-jobs-without-redis.md) for limits and migration notes.
Development remains `npm run dev` and uvicorn as described above.

The old VM files have been replaced. [ADR-0026](docs/adr/0026-remote-app-deployment-conventions.md)
records the user's remote-application requirements and the adaptations to the supplied manual.

## Product catalog

The report title is an effective-dated fund selector backed by the API product catalog. The initial migration contains only the approved 3033 project baseline. Import the business-approved current fund list using [docs/product-catalog-import.md](docs/product-catalog-import.md); funds are not hardcoded in React.

The workspace is organized around six report modules: Month in Review, Historical Performance, Company News, Constituent Performance, Final Analytics, and Footnotes & Disclosures. Snapshot loading, recalculation, assisted drafting, review, and finalization now live in their relevant module or report stage.

The first module uses the `3033-v4` paged presentation model. All six opening-page modules expose drag handles and a detailed side inspector. Module titles keep the approved reference-PDF typography and color as locked brand defaults, while body copy, Historical table cells, and footnotes retain validated typography controls; bound financial values remain locked. Editable text areas can insert a validated superscript marker before or after the current selection. Review blocks move within a collision-checked 12-column topology. Historical Performance and its aligned footnote move as one group onto explicitly created continuation pages, each with the same running chrome; later business pages and the final immutable disclaimer shift accordingly. Existing finalized v1-v3 documents keep their original rendering.

Final Analytics takes its displayed month and fund ticker from the canonical report document. Changing the top report date navigates to the latest report for that fund and date, or opens the create-report state when none exists. Company News loads the report year's DA-Report catalog by default and exposes fixed All / Bullish / Neutral / Bearish sentiment controls.

Report creation loads Historical Performance directly from the read-only CDB warehouse. Page 04 can load report-month HSTECH identity, closing price, weight and HSICS codes from CDB, then calculate 1M/3M/6M/YTD returns from FMP dividend-adjusted EOD history without waiting for a CSV; a constituent CSV remains a separate explicit override. Applying or refreshing data creates a new immutable mixed-source snapshot and derives Final Analytics on the server. Finalization locks the document version. Each subsequent HTML, PDF or DOCX download generates that version anew and deletes its temporary files after the response; no finished files are stored. See [ADR-0029](docs/adr/0029-on-demand-report-downloads.md). See [docs/news-sources-and-data-imports.md](docs/news-sources-and-data-imports.md).

## Verification

```powershell
\.\.venv\Scripts\python -m pytest backend/tests
npm test
npm run build
```

The checked-in 3033 visual baseline is under `backend/tests/fixtures/3033_202606`.
`scripts/verify_visual.py <downloaded.pdf>` checks an explicitly saved download, compares the original report pages, and independently verifies the final disclaimer page in `var/artifacts/visual/latest/manifest.json`. Legacy templates remain five pages; v4 expects the selected opening-page count plus four fixed pages.
