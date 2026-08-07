# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Stack

- Backend: Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PyMySQL. Installed as an editable
  package from `backend/pyproject.toml` (`pip install -e "./backend[dev,render]"`); no `uv` in this repo.
- Frontend: React + TypeScript + Vite (managed with **`npm` workspaces**; root `package.json` declares
  `"workspaces": ["frontend"]`, the workspace package is `@commentary/web`).
- Tasks: Celery + Redis. `TASK_MODE=EAGER` (default) runs renders inline; `TASK_MODE=CELERY` dispatches to a worker.
- DB: MySQL 8 in compose. Default local fallback (no env): `sqlite:///var/commentary.db`, anchored to the
  repo root rather than the CWD so alembic (runs in `backend/`) and uvicorn (runs at root) share one file.
- Rendering: Jinja2 canonical HTML → Playwright/Chromium PDF; python-docx DOCX.

## Common commands

Run from the repo root unless noted. Windows/PowerShell paths shown, since that is the development environment.

- Frontend dev server: `npm run dev` (Vite at `http://localhost:5173`, proxies `/api` → `http://localhost:8000`).
- Backend dev server: `.\.venv\Scripts\python -m uvicorn app.main:app --app-dir backend --reload --port 8000`.
- Backend tests: `.\.venv\Scripts\python -m pytest backend/tests` (`testpaths = ["tests"]`, `pythonpath = ["."]`).
  - Single test: `.\.venv\Scripts\python -m pytest backend/tests/test_reports_api.py::test_name`.
- Frontend tests: `npm test` (vitest). Production build: `npm run build` (`tsc -b && vite build`).
- Alembic migrations:
  - Upgrade: `cd backend && ..\.venv\Scripts\python -m alembic upgrade head`.
  - Autogenerate: `cd backend && ..\.venv\Scripts\python -m alembic revision --autogenerate -m "message"`.
- Visual QA one-off: `.\.venv\Scripts\python scripts/verify_visual.py` (writes evidence under `var/artifacts/visual/`).
- Full stack via Docker: `docker compose up --build`.
  - Frontend (nginx): `http://localhost:8080/`; API is reached same-origin through nginx at `/api/v1`.
  - Services: `db` (MySQL 8.4), `redis`, `api`, `worker` (Celery), `web` (nginx).

**Never introduce `pnpm` or `yarn` commands, lockfiles, or `packageManager` fields.** The project was
migrated to npm workspaces; `pnpm-lock.yaml` and `pnpm-workspace.yaml` were deliberately removed.

## Architecture

### Backend layout (`backend/`)

- `app/main.py` — `create_app()` assembles the FastAPI instance: CORS for `http://localhost:5173`,
  `AuthorizationMiddleware`, one router mounted at `settings.api_prefix` (`/api/v1`), and a catch-all
  exception handler that returns the structured `{error_code, message, severity, fix_hint}` envelope.
  OpenAPI lives at `/api/v1/openapi.json`, docs at `/docs`.
- `app/api/routes.py` — the single API surface. Reports, snapshots, imports, calculations, news
  candidates/selection, document updates, review, finalize, preview, render jobs, artifacts, audit.
  Add new endpoints here and keep them under `/api/v1`.
- `app/core/config.py` — `Settings` (plain Pydantic `BaseModel` reading `os.getenv`, with
  `load_dotenv(backend/.env, override=False)` so the real process environment always wins).
  Key fields: `database_url`, `api_prefix`, `template_version`, `auth_mode`, `task_mode`,
  `download_secret`, `fmp_*`. `output_root` resolves to `var/output`.
- `app/core/database.py` — engine/session. `app/core/security.py` — `Principal` + `AuthorizationMiddleware`
  (role from `X-User-Role` in LOCAL mode; bearer required in `ENTRA` mode; VIEWER is read-only; finalize
  requires REVIEWER/ADMIN). `app/core/storage.py` — object-storage port with HMAC-signed, TTL-bound downloads.
- `app/domain/` — keep these layers distinct:
  - `models.py` SQLAlchemy ORM · `schemas.py` Pydantic request/response · `service.py` orchestration ·
    `calculation.py` pure deterministic metric functions · `document.py` the `ReportDocument` content model ·
    `imports.py` CSV/XLSX parsing, validation and diff · `products.py` effective-dated product catalog.
- `app/integrations/` — external adapters behind stable interfaces (currently `fmp.py`, header-only secrets,
  fail-closed on provider error).
- `app/rendering/` — `html.py` canonical HTML, `artifacts.py` PDF/DOCX products + checksum,
  `visual_qa.py` structural page checks, `templates/*.j2`, `tokens/3033-v*.json`, `static/`.
- `app/worker.py` — Celery app and `dispatch_render`, which honours `TASK_MODE`.
- `migrations/` + `alembic.ini` — every schema change ships an upgrade **and** a downgrade.

### Frontend layout (`frontend/src/`)

- `main.tsx` / `App.tsx` boot the app; `App.tsx` owns fund selection, report creation, the status rail and
  the review gate. `components/` for shared UI (`ModuleNav`, `ReportModulesV2`, `CsvDatasetUpload`),
  `features/<domain>/` for business workbenches (`news/NewsWorkbench`, `review/ReviewCanvas`),
  `api.ts` for the typed backend client, `styles/tokens.css` for design tokens, `styles.css` for components.
- The workspace is six report modules: Review, Historical Performance, Company News,
  Constituent Performance, Final Analytics, Footnotes & Disclosures.
- Behind nginx in Docker the app is served at `/`, so API calls hit same-origin `/api/v1/...`.

### Data flow

`ReportConfig → DataSnapshot → MetricValue → ReportDocument → RenderArtifact`. Every artifact must be
traceable back to a snapshot, a `formula_version` and a document version. HTML, PDF and DOCX all read the
**same** finalized `ReportDocument` and the same design-token version.

## Design system

`DESIGN.md` at the repo root is the authoritative UI specification ("CSOP Intelligent Hub" —
Material You-style glassmorphism for financial UIs). It is implemented in
`frontend/src/styles/tokens.css` (tokens) and `frontend/src/styles.css` (components).

When building or changing frontend UI:

- Use tokens — **never** hardcode colors, radii, spacing, durations or easings. Every value in
  `styles.css` must be a `var(--…)` reference. Token names map 1:1 onto the `DESIGN.md` front matter:
  `colors.primary` → `--color-primary`, `rounded.xl` → `--radius-xl`, `spacing.md` → `--space-md`,
  `dur-fast` → `--dur-fast`, `ease-emphasized` → `--ease-emphasized`.
- Consult the eight principles in `DESIGN.md` before adding a screen: one hero per screen,
  whitespace over borders, soft glass never hard box, gradient accents not fills, motion = causality,
  micro-interactions everywhere, greeting not dashboard, readability first.
- Clickable elements need all five states: `default / hover / active / disabled / focus-visible`.
  Pressed is `scale(0.97)`; focus is the 4px glow ring `0 0 0 4px rgba(35,97,173,.14)`, never a hard outline.
- Cards and popovers are glass: `--color-surface` + `backdrop-filter: blur(…)` + a soft shadow.
  The "solid white + hard border" combination is banned.
- Category `badge-*` classes carry business classification only. Status uses an icon plus a semantic color.
- Amounts, percentages and table numbers use the numeric token (Roboto Mono + `tabular-nums`).
- Lists load with skeleton + shimmer, not a spinner. Grids enter with a `i * 60ms` stagger, capped at 600ms.
- Every animation degrades under `@media (prefers-reduced-motion: reduce)`.
- Dark mode is `body.dark-mode` overriding `dark-*` tokens only — never a structural change.

The report **output** (canonical HTML/PDF/DOCX) is a separate visual contract governed by
`backend/app/rendering/tokens/3033-v*.json` and the golden `3033_LCD_20260630` baseline. Do not apply the
product-UI design system to report output, and do not apply report tokens to the product UI.

## Hard constraints (from AGENTS.md and the V2.1 specification)

- **No hardcoded report facts.** Numbers, dates, security names, sectors and footnotes come from snapshots,
  derived metrics or versioned configuration. Golden values live only in `backend/tests/fixtures/`.
- **No authoritative calculation in the browser.** React handles interaction, editing and preview only.
- **Nothing immutable is overwritten.** Snapshots, documents and artifacts are append-only; refresh, edit and
  re-render create new versions and keep lineage.
- **No implicit mixing of CDB and uploaded files.** One effective source per dataset; overrides record
  reason, actor and diff.
- **AI never produces numbers.** It may only cite system-generated `MetricValue`s and must pass the QC-008
  number check.
- **Secrets never leak.** Credentials, tokens, signed URLs and paid news bodies stay out of logs, prompts,
  the repository and delivered artifacts.
- **`var/` is runtime-only** and gitignored; the backend container must not depend on local disk for
  persistence.

## Conventions

- Write endpoints take a `version` for optimistic locking and return 409 on conflict; validation failures
  return 422 with `error_code / field / entity_id / message / severity / fix_hint`.
- Async work returns 202 with `job_id` and a status URL; repeated idempotency keys return the original job.
- Dates are ISO 8601 (`YYYY-MM-DD`); timestamps are UTC and converted to `Asia/Hong_Kong` in the UI.
- Numeric APIs carry raw precision plus `unit` and `display_precision` — never a formatted string as fact.
- Keep calculation functions in `domain/calculation.py` pure and versioned by `formula_version`.
- Every migration is reversible and covered by `backend/tests/test_migrations.py`.
- Replacing React, FastAPI or the canonical rendering path requires a new ADR under `docs/adr/` plus full
  3033 regression evidence (see `docs/adr/0001-mandatory-stack-and-rendering.md`).
- `docs/implementation-status.md` is the live ledger of what is done versus environment-blocked. Update it
  when you complete or unblock a specification item; it is a ledger, not a waiver.
