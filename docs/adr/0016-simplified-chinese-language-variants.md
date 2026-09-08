# ADR-0016: Simplified Chinese replaces the first-phase Traditional Chinese target

- Status: Superseded by ADR-0021
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

A language switch creates the missing language variant automatically. It copies the immutable
source snapshot into new snapshot/dataset identities, preserves source checksums and lineage, and
reruns deterministic calculations. Later switches synchronize language-neutral module choices in
either direction: snapshot-backed facts, Review block structure, selected-news identity/order and
the manual rebalancing date. Review prose, localized news overrides, terminology overrides and
footnotes remain language-specific and evolve independently. A finalized target remains immutable.

Simplified Chinese display values use an explicit `*_zh_hans` value first. A Traditional Chinese
source is converted locally with OpenCC and marked `OPENCC_T2S`; absent Chinese text is left blank
and marked `MISSING`. No English prose fallback or external AI translation is permitted. Missing
Chinese editorial content produces a non-blocking review warning. Reviewers may store versioned
product, benchmark, security and industry terminology overrides in `ReportDocument`.

## Consequences

- The current user workflow is English/Simplified Chinese rather than the V2.1
  English/Traditional Chinese/bilingual target.
- Language reports cannot overwrite one another's documents or artifacts.
- Editors see the same active module after switching language, and do not have to repeat module
  selections in the other language.
- Traditional Chinese and single-file bilingual UI/output remain future work.
- Conversion remains deterministic, offline and auditable.
