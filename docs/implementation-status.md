# Implementation status against V2.1

Last verified: 2026-08-06

## Implemented and tested

- React + TypeScript product frontend and Python FastAPI `/api/v1` backend.
- SQLAlchemy domain persistence with Alembic upgrade/downgrade migrations.
- Report creation, immutable document versions, optimistic locking, finalization, and separate revisions.
- Golden fixture snapshot plus CSV/XLSX constituent import, alias mapping, validation, diff, reasoned dataset override, checksum, and audit event.
- Deterministic calculation of Top 10, sector totals, Top/Bottom performers, and core quality gates.
- News candidate creation/filtering and ordered report selection with editable title/summary.
- Metric-bound assisted draft with explicit provenance and no external AI data disclosure.
- Central review endpoint, role boundary, render jobs, artifact metadata, and authorized download boundary.
- Canonical semantic HTML, Chromium PDF, and editable DOCX from one finalized `ReportDocument`.
- A4 four-page PDF structural checks, reference/diff PNGs, and machine-readable visual manifest.
- Container definitions, MySQL/Redis local topology, CI workflow, frontend production build, and real-browser workflow validation.
- Effective-dated Product Catalog, administrator-only approved CSV import, server-resolved report identity, and product-specific constituent-count/formula profiles.
- Fund title selector plus six-module report workspace. The previous global snapshot/recalculate/draft/review/finalize buttons now live in their data, content, or review context.
- Initial controlled 12-column Month in Review layout with mouse drag ordering, keyboard move controls, immutable document-version saves, and responsive desktop/mobile presentation.
- Historical Performance, Company News selection, full constituent table, four-part Final Analytics, formula context, and Footnotes module views backed by the existing report document.
- `3033-v2` Review editor with 12-column drag/resize, controlled TipTap rich text, server overlap/bounds validation, HTML sanitization, responsive stacking, and shared HTML/DOCX rendering. `3033-v1` remains version-isolated.
- FMP Stable server adapter with header-only secret handling, constituent/general scopes, report-month date filters, provider normalization, URL/hash deduplication, report-scoped candidates, and fail-closed error handling.
- Historical Performance raw Total Return CSV and Final Analytics constituent/KPI CSV, including preview/diff/reasoned apply, explicit ratio scale, server calculations, and immutable input snapshots.
- DA-Report-derived workbench tokens: local Inter/Roboto Mono, glass surfaces, restrained elevation, responsive filter bars, selected news states, and reduced-motion support.

## Incomplete or environment-dependent

- Production CDB logical views and credentials are unavailable; `CDB_ONLY` intentionally fails closed. The adapter/configuration must be completed against approved physical views.
- Microsoft Entra token signature, issuer, audience, and group validation requires tenant/application configuration. Local mode enforces roles using test headers; deployed `ENTRA` mode currently enforces bearer presence and must be connected to the company identity configuration before production.
- Azure OpenAI deployment and DA-Report news connector are unavailable. The current assisted draft is deterministic and provenance-bound; manual approved news ingestion is implemented.
- Celery/Redis worker separation is represented in deployment topology, but the local implementation executes rendering inline while persisting the same job states. Production queue execution remains to be wired.
- Object storage and short-lived signed URLs require the company storage endpoint; local artifacts use the workspace filesystem.
- English golden output is implemented. Full Traditional Chinese and paired bilingual templates, terminology workflow, and language completeness rules remain incomplete.
- The output passes four-page A4 structural validation but does not meet the specification's recommended 0.5% pixel-difference target against the supplied reference PDF. The latest evidence manifest is generated under `artifacts/visual/latest/manifest.json`; current page differences remain materially above the target.
- Formal Marketing, Business, Data Steward, Security, and UAT approvals are external gates and have not been claimed.
- The business-approved full CSOP listed-fund CSV has not been supplied. The production catalog therefore contains only the confirmed 3033 baseline; test-only products are never seeded by migrations.
- A rotated FMP key has not been injected into the development runtime, so live FMP coverage for Hong Kong tickers remains unverified. Automated provider tests use an HTTP mock and no real credential.
- Review v2 currently supports rich-text blocks, creation/deletion, drag and resize. Dedicated image/data-table block property editors, bilingual block editing, undo/redo history, and DOCX fidelity for complex staggered rows remain incomplete.

This file is an implementation ledger, not a waiver. Items above remain part of the active V2.1 objective.
