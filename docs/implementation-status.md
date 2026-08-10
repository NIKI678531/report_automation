# Implementation status against V2.1

Last verified: 2026-08-10

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
- `3033-v2` Review editor with editable month-derived report and block titles, 12-column drag/resize, controlled TipTap rich text, server overlap/bounds validation, HTML sanitization, responsive stacking, and shared HTML/PDF/DOCX rendering. `3033-v1` remains version-isolated.
- Physical-page navigation aligned to the canonical four-page output (`01`, `01`, `02`, `03`, `04`, with cross-page Footnotes at `01/03/04`), plus synchronized fund/date/report revision selection.
- Final Analytics period and Portfolio Analysis ticker are bound to server-owned report identity; out-of-month Final Analytics observations are rejected before snapshot application.
- FMP Stable server adapter with header-only secret handling, constituent/general scopes, report-month date filters, provider normalization, URL/hash deduplication, report-scoped candidates, and fail-closed error handling.
- Historical Performance raw Total Return CSV and Final Analytics constituent/KPI CSV, including preview/diff/reasoned apply, explicit ratio scale, server calculations, and immutable input snapshots.
- DA-Report-derived workbench tokens: local Inter/Roboto Mono, glass surfaces, restrained elevation, responsive filter bars, selected news states, and reduced-motion support.
- Versioned MappingProfile persistence and administrator API; CSV/XLSX sheet/header scanning now reads field aliases, explicit units and approved unlabelled-column positions from the selected profile. Ambiguous or unknown formats stop in `NEEDS_MAPPING`, and duplicate Bloomberg return groups are recorded without double import.
- Normalized SnapshotDataset, MetricValue, ModuleSnapshot and QualityCheckResult persistence with Decimal database columns, lineage IDs/checksums, module bindings and read APIs. Existing document sections remain a compatibility projection.
- Effective-dated HSICS master CSV import with 2/4/6 digit code restoration, hierarchy/effective-range validation and report-date constituent mapping. Non-fixture finalization requires a bound HSICS dataset.
- Final Analytics trading-calendar and index-event records, report-date AUM validation, 95% daily-turnover coverage gate, and authoritative next rebalancing selection.
- Product configuration now separates the constituent index (`HSTECH`) from the official return benchmark instrument (`HSTECHN`).
- DA-Report SQLite provider with strict current-constituent title matching, report candidate relations, persisted ensure idempotency, local read-only mode, and checksum-verified TOS presigned-object materialization to ephemeral disk. Company News automatically loads candidates once without auto-selecting them.
- V2.1 lifecycle states, calculation-before-finalize gating, QC-008 AI number binding, dynamic lineage footnotes, and canonical cross-format content manifests for QC-010 comparison.

## Incomplete or environment-dependent

- Production CDB logical views and credentials are unavailable; `CDB_ONLY` intentionally fails closed. The adapter/configuration must be completed against approved physical views.
- Microsoft Entra token signature, issuer, audience, and group validation requires tenant/application configuration. Local mode enforces roles using test headers; deployed `ENTRA` mode currently enforces bearer presence and must be connected to the company identity configuration before production.
- Azure OpenAI deployment is unavailable. The current assisted draft is deterministic and MetricValue-bound; DA-Report snapshot news and manual approved news ingestion are implemented.
- Celery/Redis worker separation is represented in deployment topology, but the local implementation executes rendering inline while persisting the same job states. Production queue execution remains to be wired.
- Object storage and short-lived signed URLs require the company storage endpoint; local artifacts use the workspace filesystem.
- English golden output is implemented. Full Traditional Chinese and paired bilingual templates, terminology workflow, and language completeness rules remain incomplete.
- The output passes four-page A4 structural validation but does not meet the specification's recommended 0.5% pixel-difference target against the supplied reference PDF. The latest evidence manifest is generated under `artifacts/visual/latest/manifest.json`; current page differences remain materially above the target.
- Formal Marketing, Business, Data Steward, Security, and UAT approvals are external gates and have not been claimed.
- The business-approved full CSOP listed-fund CSV has not been supplied. The production catalog therefore contains only the confirmed 3033 baseline; test-only products are never seeded by migrations.
- A rotated FMP key has not been injected into the development runtime, so live FMP coverage for Hong Kong tickers remains unverified. Automated provider tests use an HTTP mock and no real credential.
- Review v2 currently supports rich-text blocks, creation/deletion, drag and resize. Dedicated image/data-table block property editors, bilingual block editing, undo/redo history, and DOCX fidelity for complex staggered rows remain incomplete.
- Production CDB views, the formal report-date 112-subindustry HSICS file, complete KPI/calendar/event feeds, and TOS credentials/object publication remain environment inputs. The code fails closed or marks QA blocked rather than copying facts from the PDF.

This file is an implementation ledger, not a waiver. Items above remain part of the active V2.1 objective.
