# Implementation status against V2.1

Last verified: 2026-08-25

## Implemented and tested

- React + TypeScript product frontend and Python FastAPI `/api/v1` backend.
- SQLAlchemy domain persistence with Alembic upgrade/downgrade migrations.
- Report creation, immutable document versions, optimistic locking, finalization, and separate revisions.
- Golden fixture snapshots plus one-source-per-logical-dataset CSV/XLSX slots, mapping validation, preview/diff, immutable apply and replacement audit lineage.
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
- DA-Report SQLite adapter with read-only snapshot access, a full Regional Corporate catalog, filter-bound keyset pagination, source/sentiment/importance/date facets, delayed selection materialization and fail-closed retry handling. The legacy constituent-matching fetch path and optional Marketaux provider remain available.
- Separate Index Constituents, Constituent Returns, Total Return Series, Fund KPI Daily, Trading Calendar and Index Events slots. A first application needs no reason; replacing the active source for the same slot requires one.
- DA-Report-derived workbench tokens: local Inter/Roboto Mono, glass surfaces, restrained elevation, responsive filter bars, selected news states, and reduced-motion support.
- Versioned MappingProfile persistence and administrator API; CSV/XLSX sheet/header scanning now reads field aliases, explicit units and approved unlabelled-column positions from the selected profile. Ambiguous or unknown formats stop in `NEEDS_MAPPING`, and duplicate Bloomberg return groups are recorded without double import.
- Normalized SnapshotDataset, MetricValue, ModuleSnapshot and QualityCheckResult persistence with Decimal database columns, lineage IDs/checksums, module bindings and read APIs. Existing document sections remain a compatibility projection.
- Effective-dated HSICS master CSV import with 2/4/6 digit code restoration, hierarchy/effective-range validation and report-date constituent mapping. Non-fixture finalization requires a bound HSICS dataset.
- A complete valid slot set automatically runs server calculations, while Review retains the cross-module checks as advisory diagnostics. Under ADR-0014, Finalize version-locks the current document without blocking on those findings; the Downloads menu then generates or reuses PDF/HTML/DOCX artifacts on demand and serves them through signed links.
- Final Analytics trading-calendar and index-event records, report-date AUM validation, 95% daily-turnover coverage gate, and authoritative next rebalancing selection.
- Portfolio Analysis always renders its fixed AUM/turnover/holding rows in the workbench, HTML, PDF and DOCX. It resolves every selected report month from that month's snapshot, normalizes supported source amount units to HKD millions, averages only unique authoritative trading days, and exposes raw/display metadata; absent upstream KPI observations are shown as `N/A` rather than silently hiding a row or inventing a value. Month/report-version selection automatically repairs legacy documents missing any of the three portfolio metrics.
- Product configuration now separates the constituent index (`HSTECH`) from the official return benchmark instrument (`HSTECHN`).
- Company News opens directly against the complete DA Regional Corporate catalog without requiring an active report snapshot. It supports server-side filters, an optional current-constituent company selector, infinite cursor loading, visible retry errors, bilingual enrichment metadata, manual additions and a retained right-side report editor. Saved DA rows retain external lineage and survive data recalculation; report outputs show only the publisher name while date/URL remain available for audit in the workbench. Cross-period selection is allowed with a non-blocking post-report-date warning under ADR-0002.
- Legacy combined imports, GICS/sector-override uploads, the old React report module, pnpm files and OneDrive `*-AZ-AI-WS-07*` source/configuration copies have been removed.
- V2.1 lifecycle states, calculation-before-finalize gating, QC-008 AI number binding, dynamic lineage footnotes, and canonical cross-format content manifests for QC-010 comparison.
- Page 04 exposes two distinct paths: an explicit constituent CSV identity override and automatic CDB HSTECH identity plus FMP 1M/3M/6M/YTD returns. Both paths produce immutable source lineage; Historical Performance and Final Analytics do not expose manual calculation inputs.
- Effective-dated ProductCatalog bindings for fund Total Return instrument, fund KPI product and trading calendar, with reversible migration and fail-closed validation.
- Read-only DA-Report monthly-data provider for official FUND/BENCHMARK Total Return, report-month KPI/calendar and future index events. Report creation can stage a `DA_REPORT_AUTO` snapshot; one constituent upload advances it to `DA_REPORT_PLUS_UPLOAD`, and refresh preserves the upload checksum.
- MetricValue and ModuleSnapshot source IDs now follow an explicit dependency graph instead of referencing every snapshot dataset. Constituent periods are independent from Historical common TR periods.
- Frontend and canonical HTML/PDF sector breakdowns now render accessible SVG donut charts without a chart library or CSS conic gradients. Chromium waits for fonts/images and fails on footer-safe-area overflow.
- Visual QA now verifies page-4 required text, a nonblank multicolor donut and its center hole. The latest actual PDF passes these structural checks.
- English/Simplified Chinese report variants are implemented as independently editable reports. Explicit creation copies immutable snapshot/dataset lineage to new IDs, preserves source checksums, reruns deterministic calculations, regenerates language-specific footnotes, and records OpenCC/manual terminology provenance. Missing Chinese editorial text remains blank and produces a non-blocking warning.
- The application language selector switches the full workbench between English and Simplified Chinese, remembers the preference locally, selects only the same-month target-language report, and requires an explicit action when that variant does not exist.
- Preview now restores the approved four-page A4 presentation with the running header, footer CSOP Logo, and page numbers. Downloadable HTML keeps the continuous white document flow, while PDF and DOCX retain the formal four-page structure. Chinese HTML/PDF embed Noto Sans SC data when rendered, while DOCX declares the matching East Asian font.

## Incomplete or environment-dependent

- The live read-only CDB adapter and approved performance/constituent views have been verified for 3033/HSTECH coverage from 2024 through the latest available 2026 observation. Deployment still requires injecting the database secret and TLS configuration through the company secret store.
- The DA-Report upstream repository is not present in this workspace. Its MySQL schema/ETL and dump-to-SQLite converter still need to produce `total_return_series`, `fund_kpi_daily`, `trading_calendar` and `index_events`; the 2026-08-07 SQLite snapshot does not contain them, so production automatic monthly snapshots correctly remain PENDING until that external delivery lands.
- Microsoft Entra token signature, issuer, audience, and group validation requires tenant/application configuration. Local mode enforces roles using test headers; deployed `ENTRA` mode currently enforces bearer presence and must be connected to the company identity configuration before production.
- Azure OpenAI deployment is unavailable. The current assisted draft is deterministic and MetricValue-bound; DA-Report snapshot news and manual approved news ingestion are implemented.
- Celery/Redis worker separation is represented in deployment topology, but the local implementation executes rendering inline while persisting the same job states. Production queue execution remains to be wired.
- Object storage and short-lived signed URLs require the company storage endpoint; local artifacts use the workspace filesystem.
- English golden output and independent Simplified Chinese output are implemented. Traditional Chinese and paired bilingual UI/templates remain incomplete and are intentionally deferred by ADR-0016.
- The output passes four-page A4 validation and page-4 donut/text structure checks but does not meet the specification's recommended 0.5% pixel-difference target against the supplied reference PDF. The latest page-4 difference is 12.0464%; evidence is under `var/artifacts/visual/latest/manifest.json`.
- Formal Marketing, Business, Data Steward, Security, and UAT approvals are external gates and have not been claimed.
- The business-approved full CSOP listed-fund CSV has not been supplied. The production catalog therefore contains only the confirmed 3033 baseline; test-only products are never seeded by migrations.
- Page 04 constituent identity can be loaded automatically from the report-month-effective CDB HSTECH view; 1M/3M/6M/YTD returns are loaded from FMP's dividend-adjusted EOD endpoint using each normalized Hong Kong ticker. An explicit constituent CSV remains an override, and provider tests use HTTP mocks without committed credentials.
- Review v2 currently supports rich-text blocks, creation/deletion, drag and resize, plus Simplified Chinese terminology overrides. Dedicated image/data-table block property editors, Traditional Chinese/paired bilingual block editing, undo/redo history, and DOCX fidelity for complex staggered rows remain incomplete.
- The formal report-date 112-subindustry HSICS file, complete KPI/calendar/event feeds, and TOS credentials/object publication remain environment inputs. CDB/FMP credentials also remain deployment secrets. The code fails closed or marks QA blocked rather than copying facts from the PDF.

This file is an implementation ledger, not a waiver. Items above remain part of the active V2.1 objective.
