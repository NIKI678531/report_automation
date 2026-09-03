# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Stack

- Backend: Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PyMySQL. Installed as an editable
  package from `backend/pyproject.toml` (`pip install -e "./backend[dev,render]"`); no `uv` in this repo.
- Frontend: React + TypeScript + Vite (managed with **`npm` workspaces**; root `package.json` declares
  `"workspaces": ["frontend"]`, the workspace package is `@commentary/web`).
- Tasks: Celery + Redis. `TASK_MODE=EAGER` (default) runs renders inline; `TASK_MODE=CELERY` dispatches to a worker.
- DB: MySQL 8 in compose, and MySQL is the only supported deployment target — `deployment_problems()`
  refuses to start a non-LOCAL process on SQLite. Default local fallback (no env):
  `sqlite:///var/commentary.db`, anchored to the repo root rather than the CWD so alembic (runs in
  `backend/`) and uvicorn (runs at root) share one file.
- Auth: `AUTH_MODE=LOCAL` (default) trusts request headers and is for workstations only;
  `AUTH_MODE=ENTRA` validates a Microsoft Entra access token and needs the `entra` extra
  (`pip install -e "./backend[entra]"`, i.e. `pyjwt[crypto]`).
- Artifact storage: `STORAGE_BACKEND=LOCAL` (default) writes to `var/output`; `STORAGE_BACKEND=S3`
  is any S3-compatible store (Volcengine TOS, MinIO, AWS S3) and needs the `storage` extra
  (`pip install -e "./backend[storage]"`, i.e. `boto3`). `deployment_problems()` refuses to start a
  non-LOCAL process on `LOCAL` storage — the deployment has no persistent volume. The production
  image installs `[render,entra,storage]` so promoting it never depends on a pip install.
- Rendering: Jinja2 canonical HTML → Playwright/Chromium PDF; python-docx DOCX.

## Common commands

Run from the repo root unless noted. Windows/PowerShell paths shown, since that is the development environment.

- Frontend dev server: `npm run dev` (Vite at `http://localhost:5173`, proxies `/api` → `http://localhost:8000`).
- Backend dev server: `.\.venv\Scripts\python -m uvicorn app.main:app --app-dir backend --reload --port 8000`.
- Backend tests: `.\.venv\Scripts\python -m pytest backend/tests` (`testpaths = ["tests"]`, `pythonpath = ["."]`).
  - Single test: `.\.venv\Scripts\python -m pytest backend/tests/test_reports_api.py::test_name`.
  - Against real MySQL: `$env:TEST_MYSQL_URL = "mysql+pymysql://user:pw@host/scratch?charset=utf8mb4"`
    enables `test_migrations_apply_to_a_real_mysql_database`. It downgrades the target to base first,
    so it must point at a throwaway schema.
  - `backend/tests/fixtures/` holds data the source is not free to publish — golden records
    transcribed from an approved report, vendor EOD samples — so a checkout can arrive without it.
    Anything that needs one calls `require_fixtures()` from `conftest.py` and **skips** when it is
    absent; `addopts = "-rs"` prints each reason, so a thinner run says so in its own log. A module
    that reads a fixture at import time must guard with `module_level=True`, or the whole run dies
    in collection. TESTING-lane tests never touch the files: the app answers 503 `FIXTURE_MISSING`
    and the test client in `conftest.py` turns that one code into the same skip.
- Frontend tests: `npm test` (vitest). Production build: `npm run build` (`tsc -b && vite build`).
- Alembic migrations:
  - Upgrade: `cd backend && ..\.venv\Scripts\python -m alembic upgrade head`.
  - Autogenerate: `cd backend && ..\.venv\Scripts\python -m alembic revision --autogenerate -m "message"`.
- Visual QA one-off: `.\.venv\Scripts\python scripts/verify_visual.py` (writes evidence under `var/artifacts/visual/`).
- Deployment preflight: `.\.venv\Scripts\python scripts/check_deployment.py` — runs the startup
  refusal checks plus the ones the app only reaches at first use (database reachable and at head,
  JWKS answering, artifact bucket addressable). `--token "$ACCESS_TOKEN"` additionally resolves a
  real token to a subject, role and product scope; `--env-file path` checks the environment that
  file describes instead of the current one, so the production settings can be proved clean from a
  workstation before any process reads them; `--skip-network` reports configuration without calling
  the tenant or the bucket. Exit 1 means the environment must not serve traffic.
- Full stack via Docker: `docker compose up --build`.
  - Frontend (nginx): `http://localhost:8080/`; API is reached same-origin through nginx at `/api/v1`.
  - Services: `db` (MySQL 8.4), `redis`, `api`, `worker` (Celery), `web` (nginx).

**Never introduce `pnpm` or `yarn` commands, lockfiles, or `packageManager` fields.** The project was
migrated to npm workspaces; `pnpm-lock.yaml` and `pnpm-workspace.yaml` were deliberately removed.

## Architecture

### Backend layout (`backend/`)

- `app/main.py` — `_verify_deployment_configuration()` runs **before** the app object exists and raises
  `ConfigurationError` if `settings.deployment_problems()` is non-empty, then `create_app()` assembles
  the FastAPI instance: `AuthorizationMiddleware` added first so CORS (`settings.cors_allow_origins`)
  ends up outermost — a browser must be able to read a 401/403 body — one router mounted at
  `settings.api_prefix` (`/api/v1`), and handlers for `HTTPException` / `RequestValidationError` /
  `Exception` that all emit the same `{error_code, message, severity, fix_hint, request_id}` envelope
  (422 adds `findings[]`). OpenAPI lives at `/api/v1/openapi.json`, docs at `/docs`.
- `app/api/routes/` — the API surface, one module per area: `reports.py` (lifecycle, document,
  review, finalize, preview), `datasets.py` (snapshots, imports, import batches, calculations),
  `news.py`, `render.py` (render jobs, artifacts), `catalog.py`, `admin.py` (audit trail), with shared
  dependencies in `deps.py` (`principal`, `require_role`, `require_product_access`, `request_id`) and
  bounded upload reading in `uploads.py`; the router is assembled in `__init__.py`. Add a new endpoint
  to the module that owns its area and keep it under `/api/v1`.
- `app/core/config.py` — `Settings` (plain Pydantic `BaseModel` reading `os.getenv`, with
  `load_dotenv(backend/.env, override=False)` so the real process environment always wins) and
  `ConfigurationError`. Key fields: `database_url`, `db_pool_*`, `api_prefix`, `template_version`,
  `auth_mode`, `task_mode`, `download_secret`, `download_ttl_seconds`, `entra_*`, `upload_*`,
  `cors_allow_origins`, `allow_testing_lane`, `da_report_*`, `datawarehouse_*`, `fmp_*`,
  `marketaux_*`. `output_root` resolves to `var/output`. `deployment_problems()` returns every reason
  the configuration must not serve traffic (default/short `DOWNLOAD_SECRET`, unknown `AUTH_MODE`,
  missing Entra audience/issuer/JWKS, symmetric or `none` algorithms, `ALLOW_TESTING_LANE`, SQLite);
  LOCAL is exempt by design. Env parsing goes through `_env_bool/_env_int/_env_float/_env_csv`, which
  name the offending variable instead of crashing with a bare `ValueError`.
- `app/core/database.py` — engine/session, with SQLite and MySQL configured differently:
  `check_same_thread=False` for SQLite; `pool_pre_ping` + `pool_recycle` + `pool_size` /
  `max_overflow` / `pool_timeout` and a `connect_timeout` for MySQL, plus `charset=utf8mb4` unless the
  URL already carries one.
- `app/core/security.py` — the authorization boundary: `Principal` (`subject`, `role`,
  `product_scope`), `SYSTEM_PRINCIPAL` for work no request initiated, a `current_principal`
  ContextVar, and `AuthorizationMiddleware`. It is a **pure ASGI** middleware, not a
  `BaseHTTPMiddleware`, so the downstream app runs in its context and the service layer can read the
  principal without threading an argument through every signature. Only `/api/v1/health` (exact match)
  and CORS preflight skip identity. Rules that hold everywhere live here — VIEWER never writes,
  finalize needs REVIEWER/ADMIN; endpoint-specific rules live in `deps.py`. Every response, including
  a denial built by hand outside FastAPI's exception handlers, carries `SECURITY_HEADERS` plus a CSP
  chosen by content type: `_API_CSP` (`default-src 'none'`) for JSON and downloads, `_DOCUMENT_CSP`
  for the `text/html` report preview.
- `app/core/entra.py` — Microsoft Entra token validation: cached JWKS with a rate-limited rollover
  refresh, algorithm pinning (`entra_allowed_algorithms`, HS\*/none rejected), audience/issuer/expiry
  with leeway, `oid` preferred over `sub`, and role plus product scope read from claims. Errors are
  `TokenError`s carrying the error code the envelope reports (`TOKEN_EXPIRED`,
  `TOKEN_AUDIENCE_REJECTED`, `TOKEN_ALGORITHM_REJECTED`, `ROLE_NOT_ASSIGNED`, …).
  `ensure_available()` is called at startup so a missing PyJWT fails the boot, not the first request.
- `app/core/storage.py` — the object-storage port and its two backends, selected by
  `STORAGE_BACKEND`: `LocalObjectStorage` (filesystem, workstations and UAT) and `S3ObjectStorage`
  (any S3-compatible store; the boto3 client is built lazily so importing never needs the extra and
  a test can inject a stub). `build_storage()` raises on a backend nothing implements rather than
  falling back to disk. Downloads are HMAC-SHA256 signed, TTL-bound and tied to the caller's
  subject. A `storage_key` arrives from the database, so `resolve()`, `put_file()` and `open()` all
  refuse one that escapes the object root — on S3 there is no filesystem to catch `..`, so the key
  is validated segment by segment instead.
- `app/domain/` — keep these layers distinct:
  - `models.py` SQLAlchemy ORM · `schemas.py` Pydantic request/response · `document.py` the
    `ReportDocument` content model · `imports.py` CSV/XLSX parsing, validation and diff ·
    `products.py` effective-dated product catalog.
  - `service/` session-bound orchestration, one module per concern and layered
    `audit → lifecycle → catalog → documents → snapshots → imports → import_batches →
    calculations → reports`, with `news` beside them. `lifecycle.py` holds the shared
    `ensure_report_not_archived` / `ensure_report_editable` guards that every state-changing service
    calls, so "can this report still be edited?" is answered in one place. Everything that touches a
    `Session` lives here.
  - `metrics/` pure deterministic metric functions, **one module per report module** so an import
    states which page it feeds: `historical_performance.py` (02), `constituent_performance.py` (04),
    `industry_breakdown.py` (the donut in 05), `final_analytics.py` (05), `footnotes.py` (06).
    Supporting modules that are not report modules: `errors.py`, `formatting.py`, `fund_kpis.py`,
    and `quality_checks.py` for the QC/KPI gate, which spans modules. 01 Review and 03 Company News
    have no arithmetic and deliberately have no module here. Import from the specific module —
    there is no flat re-export.
- `app/integrations/` — external adapters behind stable interfaces (`da_report.py` reads the approved
  read-only SQLite snapshot, `marketaux.py` is the optional remote vendor; both fail closed).
- `app/rendering/` — `html.py` canonical HTML, `artifacts.py` PDF/DOCX products + checksum,
  `visual_qa.py` structural page checks, `templates/*.j2`, `tokens/3033-v*.json`, `static/`.
  Every format renders through a real path because Chromium and python-docx require one, so
  `artifacts.publish()` deletes that local copy once a remote backend has the object — on `LOCAL`
  the same file *is* the artifact and is kept.
- `app/worker.py` — Celery app and `dispatch_render`, which honours `TASK_MODE`.
- `migrations/` + `alembic.ini` — every schema change ships an upgrade **and** a downgrade, and both
  are stepped one revision at a time by `backend/tests/test_migrations.py`. Indexed `String` columns
  must declare a length of at most 768 characters: InnoDB caps an index key at 3072 bytes and utf8mb4
  reserves four bytes per character, so a longer column is a `CREATE TABLE` failure on MySQL that
  SQLite accepts silently. Long values are made unique through a hash column instead — that is what
  `news_items.source_url_hash` is for.

### Frontend layout (`frontend/src/`)

- `main.tsx` / `App.tsx` boot the app; `App.tsx` owns fund selection, report creation, the status rail and
  the review gate. `components/` for shared UI (`ModuleNav`, `ReportModulesV2`, `CsvDatasetUpload`),
  `features/<domain>/` for business workbenches (`news/NewsWorkbench`, `review/ReviewCanvas`),
  `api.ts` for the typed backend client, `styles/tokens.css` for design tokens, `styles.css` for components.
- `api.ts` throws `ApiError` (an `Error` subclass) carrying `status`, `errorCode`, `fixHint`,
  `requestId` and `findings[]`, with `message` already composed into a readable sentence. Call sites
  render `String(caught)`, so never surface a raw body: an HTML page from nginx or a JSON envelope
  must not reach the status rail. Add new failure text to `PROXY_FALLBACKS`, not to a call site.
- The workspace is six report modules: Review, Historical Performance, Company News,
  Constituent Performance, Final Analytics, Footnotes & Disclosures.
- Behind nginx in Docker the app is served at `/`, so API calls hit same-origin `/api/v1/...`.

### Data flow

`ReportConfig → DataSnapshot → MetricValue → ReportDocument → RenderArtifact`. Every artifact must be
traceable back to a snapshot, a `formula_version` and a document version. HTML, PDF and DOCX all read the
**same** finalized `ReportDocument` and the same design-token version.

### Deployment and the security boundary

Two auth modes, one enforcement path. Configuration lives in `.env.example` (compose/deployment
secrets, at the repo root) and `backend/.env.example` (service settings); neither has a working
default, and `compose.yaml` references the secrets as `${VAR:?message}` so a missing one stops
`docker compose up` by name rather than standing up a database with a published password.

- **LOCAL** — identity is *asserted* by `X-User-Role` / `X-User-ID` / `X-Product-Scope`. Developer
  mode only. It is also the switch that gates every other workstation-only behaviour: home-directory
  snapshot probing, the public default signing key, the fixture lane.
- **ENTRA** — identity is *proved* by a signed access token, and the headers above are ignored
  entirely. Otherwise a caller could authenticate as a viewer and then claim `X-User-Role: ADMIN`.

Rules to keep intact when touching this area:

- Roles are ordered `VIEWER < EDITOR < REVIEWER < ADMIN`. VIEWER is read-only everywhere; finalize
  needs REVIEWER or ADMIN; catalog, industry-master and mapping-profile writes need ADMIN.
- **Product scope gates rows, not endpoints.** A report outside the caller's scope is a 404, not a
  403 — a 403 confirms the report exists.
- Uploads are bounded while streaming, never after buffering the body, and the ceiling must stay at
  or below nginx's `client_max_body_size`. A proxy-level 413 carries none of the error envelope.
- Artifacts go to object storage, never to container-local disk. The deployment provides no
  persistent volume, so `STORAGE_BACKEND=LOCAL` outside LOCAL auth is a startup refusal alongside
  SQLite. The download route streams from the port rather than reading a path, and an artifact row
  whose object is gone answers 404 `ARTIFACT_CONTENT_MISSING` — that is what a restart looks like
  when the rule was broken, and a 500 would blame the request instead.
- Download URLs are HMAC-signed, TTL-bound and tied to the requesting subject; a signature is not a
  capability someone else can replay.
- Jinja autoescape is `autoescape=True`, not `select_autoescape([...])` — the templates are named
  `*.html.j2`, and suffix-based selection silently leaves escaping off for them.
- New tests for any of this belong in `backend/tests/test_security.py`, which is organised by
  property (roles, scope, headers, audit, uploads, downloads, XSS, Entra, configuration guards).

`docs/entra-setup.md` is the tenant-side runbook: app registration, the four app-role values, the
three ways product scope can be carried, and an `error_code` → cause table. Keep it in step with
`app/core/entra.py` — the table is a promise about specific error codes.

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
  the repository and delivered artifacts. No default may be a working credential.
- **Production is MySQL 8 with utf8mb4.** SQLite is a developer convenience; a deployed process refuses
  to start on it. Schema written against SQLite must still be legal InnoDB — index key lengths above all.
- **`var/` is runtime-only** and gitignored; the backend container must not depend on local disk for
  persistence.

## Conventions

- Write endpoints take a `version` for optimistic locking and return 409 on conflict; validation failures
  return 422 with `error_code / field / entity_id / message / severity / fix_hint`.
- Every error response is the same envelope, including the ones the middleware builds before FastAPI's
  handlers run. Add `request_id` — it is what the 500 handler tells the user to quote.
- New settings go through the `_env_*` helpers in `config.py`, get a line in the matching
  `.env.example`, and — if getting them wrong is unsafe rather than merely wrong — a check in
  `deployment_problems()`.
- Async work returns 202 with `job_id` and a status URL; repeated idempotency keys return the original job.
- Dates are ISO 8601 (`YYYY-MM-DD`); timestamps are UTC and converted to `Asia/Hong_Kong` in the UI.
- Numeric APIs carry raw precision plus `unit` and `display_precision` — never a formatted string as fact.
- Keep calculation functions in `domain/metrics/` pure and versioned by `formula_version`, in the
  module named for the report module they feed. Nothing there may touch a `Session`; the
  session-bound half is `domain/service/calculations.py`.
- Every migration is reversible and covered by `backend/tests/test_migrations.py`.
- Replacing React, FastAPI or the canonical rendering path requires a new ADR under `docs/adr/` plus full
  3033 regression evidence (see `docs/adr/0001-mandatory-stack-and-rendering.md`).
- `docs/implementation-status.md` is the live ledger of what is done versus environment-blocked. Update it
  when you complete or unblock a specification item; it is a ledger, not a waiver.
