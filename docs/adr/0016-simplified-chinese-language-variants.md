# ADR-0016: Simplified Chinese replaces the first-phase Traditional Chinese target

- Status: Accepted
- Date: 2026-08-24

## Context

V2.1 names English, Traditional Chinese and bilingual output as the target language set. The
approved implementation request instead makes Simplified Chinese the only Chinese mode exposed
in the current product UI. Reports in different languages must remain independently editable,
while their quantitative facts remain reproducible and auditable.

## Decision

Add `ZH_HANS` as a persisted report and document language. The UI exposes only `EN` and
`ZH_HANS`; existing `ZH_HANT` and `BILINGUAL` values remain accepted for stored-data and API
compatibility.

An explicit language-variant command creates a separate report. It copies the immutable source
snapshot into new snapshot/dataset identities, preserves source checksums and lineage, and reruns
deterministic calculations. Review prose, news selection text and footnotes belong to the new
document version and evolve independently.

Simplified Chinese display values use an explicit `*_zh_hans` value first. A Traditional Chinese
source is converted locally with OpenCC and marked `OPENCC_T2S`; absent Chinese text is left blank
and marked `MISSING`. No English prose fallback or external AI translation is permitted. Missing
Chinese editorial content produces a non-blocking review warning. Reviewers may store versioned
product, benchmark, security and industry terminology overrides in `ReportDocument`.

## Consequences

- The current user workflow is English/Simplified Chinese rather than the V2.1
  English/Traditional Chinese/bilingual target.
- Language reports cannot overwrite one another's documents or artifacts.
- Traditional Chinese and single-file bilingual UI/output remain future work.
- Conversion remains deterministic, offline and auditable.
