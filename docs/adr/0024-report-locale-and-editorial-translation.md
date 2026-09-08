# ADR-0024: Report-scoped language and protected editorial translation

- Status: Accepted
- Date: 2026-09-08
- Partially supersedes: ADR-0021 (English/Chinese editorial translation only)

Report Centre language is a personal navigation preference, not the language of an opened report.
The complete report workspace now derives its language from the selected report. Leaving it restores
the centre preference. A language change opens a separate same-month, same-revision variant; it never
changes a report's language in place or rewrites a finalized document.

The product owner approved English/Chinese translation through a company-approved OpenAI-compatible
gateway. It is explicitly disabled until configured. Only Review prose and custom titles are eligible;
facts, layout, links, news bodies, terminology master data and regulatory disclosures are not sent.
Simplified/Traditional conversion remains offline OpenCC. News and disclosures use approved language
sources; missing translations remain visible as missing rather than being invented.

Translation runs as a version-bound, caller-scoped idempotent job. The worker checks configuration,
source and target versions and editable state again before atomically recording its result and a new
document version. Field checksums distinguish generated text from manual edits. Manual target edits
are retained and flagged for review when their source changes; unchanged translations and unedited
reverse translations do not invoke the gateway. Target-only blocks are retained during cross-English
layout synchronization rather than silently deleted.

HTML structure and protected numeric/code/link tokens are rebuilt locally, not by the model. Output
must preserve protected tokens, satisfy the document schema and pass the applicable QC-008 numeric
binding check before it is saved. Source/target field checksums, provider, model and prompt version
are retained, but request/response bodies and credentials are not logged. Machine translation remains
editorial assistance, not approved legal wording or a guarantee of linguistic quality.

The independent job table and reversible migration were chosen over reusing format-specific render
jobs. Production uses the existing Celery/Redis infrastructure and MySQL, with no local persistence
or PVC dependency. See [the translation runbook](../editorial-translation.md) for configuration and
verification boundaries.