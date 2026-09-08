# ADR-0021: English, Simplified Chinese and Hong Kong Traditional Chinese variants

- Status: Accepted
- Date: 2026-08-31
- Supersedes: ADR-0016

## Context

The report workspace must expose English, Simplified Chinese and Traditional Chinese as complete,
independently renderable report languages. English editorial prose is intentionally maintained by
an editor rather than machine translated. Simplified and Traditional Chinese editorial content can
be converted deterministically, but a later synchronization must not overwrite a reviewer’s target-
language changes.

## Decision

- The UI and language-variant API expose `EN`, `ZH_HANS` and `ZH_HANT`. Traditional Chinese uses
  Hong Kong conventions, `zh-HK` browser formatting and a Traditional Chinese output font.
  `BILINGUAL` remains a stored/API compatibility value and is not offered as a new UI mode.
- Structured names prefer the target field. Simplified Chinese uses `*_zh_hans`, then OpenCC T2S
  from `*_zh_hant`/legacy `*_zh`; Traditional Chinese uses `*_zh_hant`/legacy `*_zh`, then OpenCC
  S2HK from `*_zh_hans`. Missing Chinese stays blank and produces a review warning; it never
  silently falls back to English.
- Synchronizing two Chinese variants converts Review fields, manual news and news overrides,
  footnotes, and terminology overrides. Each generated target field records the source report,
  source document version, conversion method, and source/target checksums in versioned
  `ReportDocument.translation_provenance.fields`.
- A target field is regenerated only when blank or when its checksum still equals the prior
  generated checksum. A manually changed target is preserved and its generated-field provenance is
  removed. English/Chinese editorial prose is never automatically translated.
- Snapshot facts, layout, news identity/order and manual rebalancing date continue to synchronize.
  Finalized reports and their artifacts remain immutable.
- HTML, PDF and DOCX use Traditional Chinese terms, names, fonts and the `ZH-HANT` filename tag.
  No database migration is required because conversion provenance is stored in document JSON.

## Consequences

All three language reports share auditable facts while retaining independent editorial control.
OpenCC conversion is offline and reproducible. Editors must supply genuinely missing Chinese source
text and must author English prose separately.
