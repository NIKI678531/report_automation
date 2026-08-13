# Monthly Commentary Platform

Generates the monthly fund commentary report for CSOP ETFs, from raw data ingestion through
calculation, editorial review and finalized HTML/PDF/DOCX delivery. This file fixes the words the
codebase uses, so the same idea is not called three things across the domain, the API and the UI.

## Language

### Product and report

**Product**:
A CSOP ETF the platform writes commentary for, identified by `product_code` and described by an
effective-dated `ProductCatalog` row.
_Avoid_: ETF, instrument, security

**Report**:
One month's commentary for one product, identified by `product_code` + `report_date`. Every
snapshot, document, metric and artifact hangs off exactly one report.
_Avoid_: Commentary, monthly note, deliverable

**Report date**:
The month-end date a report speaks as of. It selects the effective product catalog row, the news
window and the industry taxonomy version.
_Avoid_: Period end, month end, valuation date

**Constituent index**:
The index whose members are analysed in modules 04 and 05 (`constituent_index_code`, e.g. HSTECH).
_Avoid_: Benchmark, underlying

**Benchmark instrument**:
The priced series the fund's return is compared against (`benchmark_instrument_code`, e.g.
HSTECHN). Deliberately a different field from the constituent index — they are usually not the
same code.
_Avoid_: Index, comparison index

**Formula profile**:
The per-product key selecting versioned calculation configuration, such as industry display order
(`formula_profile`, e.g. `hstech-2026.1`).
_Avoid_: Calculation config, ruleset

### Report modules

**Report module**:
One of the six numbered pages of a report: 01 Review, 02 Historical Performance, 03 Company News,
04 Constituent Performance, 05 Final Analytics, 06 Footnotes & Disclosures. The workbench, the
calculation files and the rendered pages all use this division.
_Avoid_: Tab, page, chapter, screen

**Section**:
The key a module's content lives under inside a report document (`month_in_review`,
`historical_performance`, `company_news`, `constituents`, `analytics`, `footnotes`). A section is
the storage name for a module's content, not a synonym for the module.
_Avoid_: Block, part

**Module snapshot**:
The frozen calculated payload for one module, unique per snapshot + `module_code` +
`formula_version` + `template_version`. Only the four modules with arithmetic have one —
`historical_performance`, `constituents_performance`, `final_analytics`, `footnotes`.
_Avoid_: Module result, computed section

### Data and lineage

**Data snapshot**:
The immutable set of input data bound to a report at one as-of date. Every number in a delivered
report traces back to exactly one snapshot.
_Avoid_: Dataset, data pull, data load, extract

**Dataset slot**:
One named upload lane a report expects data in: `constituent_performance`, `index_constituents`,
`constituent_returns`, `total_return_series`, `fund_kpi_daily`, `trading_calendar`, `index_events`.
_Avoid_: File type, upload category, feed

**Dataset type**:
The lineage key recorded on a `SnapshotDataset` — `constituent_snapshot`,
`constituent_period_return`, `index_event`, `total_return_series`, `fund_kpi_daily`,
`trading_calendar`, `industry_master`. Deliberately a different namespace from the slot key,
because two slots can write the same snapshot data.
_Avoid_: Slot, source type

**External slot**:
A prerequisite dataset administered once for the whole system rather than uploaded onto a report.
Today only the HSICS industry master.
_Avoid_: Global dataset, shared upload

**Source policy**:
Where a snapshot's data came from — `CDB_ONLY`, `DA_REPORT_AUTO`, `DA_REPORT_AUTO_LOAD`,
`DA_REPORT_PLUS_UPLOAD`, `GOLDEN_FIXTURE`. Never defaulted; every construction site must state it.
_Avoid_: Data source, mode, origin

**Lane**:
Whether output may be distributed — `PRODUCTION` or `TESTING`. Orthogonal to source policy on
purpose: source policy says where data came from, the lane says whether it may leave the building.
_Avoid_: Environment, stage, mode

**Import batch**:
An all-or-nothing group of uploads, staged for validation and then applied as one new snapshot
(`STAGING` → `APPLIED` or `DISCARDED`). Nothing lands from a partially valid batch.
_Avoid_: Upload session, transaction

**Mapping profile**:
The versioned instruction for turning one vendor's sheet and column layout into the canonical
fields. `mapping_version` records which profile produced a given snapshot.
_Avoid_: Column mapping, schema, adapter

**Industry master**:
The report-date-effective HSICS taxonomy used for every industry aggregation. Every aggregation
carries its `taxonomy` and `taxonomy_version` so a retroactive taxonomy change cannot silently
rewrite a past report.
_Avoid_: Sector table, GICS, classification

**Golden fixture**:
The frozen `3033_LCD_20260630` baseline under `backend/tests/fixtures/`. The only place literal
report numbers are allowed to live.
_Avoid_: Test data, sample, seed

**DA Report**:
The approved read-only SQLite snapshot that supplies company news candidates and auto-loaded
monthly data. Fails closed when unavailable.
_Avoid_: News DB, upstream, vendor feed

### Calculation and quality

**Metric value**:
One system-computed number, unique per snapshot + `metric_code` + `dimension_key` +
`formula_version`, carrying raw precision alongside its unit and display precision. Prose may cite
these; it may never invent a number.
_Avoid_: Figure, stat, computed field

**Formula version**:
The version stamp of the arithmetic that produced a metric, so a formula change creates a new
value rather than mutating an old one.
_Avoid_: Calc version, algorithm version

**Chart snapshot**:
Structured chart data in which ordering, the zero-weight filter, the percentage string and the
colour token are all already decided. Renderers do geometry and colour lookup only — never
regroup, re-sort or recompute.
_Avoid_: Chart data, chart config, plot

**Finding**:
One entry in a validation or quality result list: `check_id` / `severity` / `status` / `message` /
`fix_hint`. Parsers accumulate findings and run to completion instead of raising on the first bad
row.
_Avoid_: Error, validation error, issue

**Check id**:
The identifier of the rule that produced a finding (`QC-001`, `KPI-002`, `QC-HOLDING-COUNT`).
Distinct from `error_code`, which belongs to the HTTP error envelope for a single failed request.
_Avoid_: Error code, rule code

### Document, review and rendering

**Report document**:
The versioned content model an editor works on — narrative plus bound facts. Append-only: an edit
creates a new version and keeps lineage.
_Avoid_: Draft, content, payload

**Binding**:
Attaching a snapshot's derived facts into a document, recorded in `module_bindings` so each module
declares which snapshot it is quoting.
_Avoid_: Sync, refresh, merge

**Content manifest**:
The per-section checksums plus lane and module order stored on every artifact, so what was
rendered can be proved after the fact.
_Avoid_: Metadata, fingerprint

**Finalize**:
The REVIEWER/ADMIN act that locks one document version as the version to be rendered and
delivered.
_Avoid_: Approve, publish, sign off, lock

**Canonical HTML**:
The Jinja-rendered HTML that is the single source PDF and DOCX are derived from. There is no
second layout path.
_Avoid_: Template output, preview HTML

**Render artifact**:
A delivered file (html, pdf or docx) with its checksum, `template_version`, `renderer_version` and
content manifest.
_Avoid_: Output, export, file, download

**Design token version**:
The report output's visual contract, `backend/app/rendering/tokens/3033-v*.json`. Separate from
the product-UI tokens in `frontend/src/styles/tokens.css` — neither may be applied to the other.
_Avoid_: Theme, style version

**Testing banner**:
The lane mark stamped on TESTING-lane output. A control rather than decoration: tokens decide how
it looks, the renderer decides only that it exists.
_Avoid_: Watermark, disclaimer

### Company news

**News item**:
A deduplicated article from a provider, unique by source URL.
_Avoid_: Article, story, headline

**Candidate**:
A news item matched to a report, with the match status and evidence that justified the match.
_Avoid_: Suggestion, hit, result

**Selection**:
A candidate an editor has chosen and ordered into module 03, with optional title and summary
overrides.
_Avoid_: Chosen news, pick, inclusion

**Fetch run**:
One provider query window, unique per report + snapshot + provider + scope + date range, so the
same window is never billed or fetched twice.
_Avoid_: Query, pull, sync
