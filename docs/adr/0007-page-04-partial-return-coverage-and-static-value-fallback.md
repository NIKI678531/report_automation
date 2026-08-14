# ADR 0007: Page 04 partial return coverage and static-value fallback

- Status: Accepted
- Date: 2026-08-14
- Amends: ADR-0004 Page 04 join coverage

## Context

The approved Page 04 workflow joins a report-month HSTECH identity/price/weight file to an
approved Total Return source. The Bloomberg workbook can contain two header-equivalent groups:
live add-in formulas and a static-value copy. Outside a Bloomberg-enabled Excel session the live
cells may resolve to calculation errors even though the static group contains the reviewed
values. Some recently listed securities can also lack one or more return periods legitimately.

The V2.1 full-join rule treated any missing constituent return as blocking. The business has now
confirmed a narrower rule: identity, name, closing price and weight remain mandatory, while an
individual 1M, 3M, 6M or YTD return may be unavailable and must render as `N/A`, never zero.

## Decision

Each batch still covers exactly one report month and accepts one canonical file or split identity
and return files. Duplicate logical sources remain blocking and require explicit exclusion. A
validated identity/price/weight file may be applied before its return source. This creates a
pending immutable snapshot: Page 04 renders all returns as `N/A`, while Top 10 constituents and
the industry breakdown are calculated immediately from weights and effective HSICS mappings.
Return-dependent top/bottom performer rankings remain empty.

A later return-only batch may join to an active uploaded split identity snapshot from the same
report. It supplements that snapshot without requiring a replacement reason when no return source
is currently applied. Final calculation, review and publication gates continue to require the
complete constituent-performance bundle and all other mandatory datasets.

For header-equivalent Bloomberg return groups, the parser selects the complete aligned group with
the highest numeric coverage and reports that selection in import findings and lineage. Period
boundaries may fall back across equivalent header groups. Blank, `N/A`, `#N/A` and `NA` are
approved missing tokens; arbitrary text and calculation errors such as `#NAME?`, `#REF!` and
`#VALUE!` remain blocking when no valid group supplies the value.

A recognized return source must contain at least one numeric return. Missing periods or unmatched
identity rows are retained as `N/A` with warnings and missing-reason lineage. Return rows outside
the effective constituent set are shown in the merge preview and are not merged. The reviewer sees
the full eight-column joined table and unmatched-code lists before applying the immutable batch.

## Consequences

- Core constituent facts cannot be hidden behind `N/A`; a missing code, name, price or weight
  rejects the import.
- Page 04 can faithfully show a partially unavailable return history without inventing zeroes.
- Reviewers can save and inspect identity-only Page 04 data and its weight-based Page 05 outputs
  before the return file arrives.
- Downstream performer rankings continue to exclude unavailable returns.
- Reviewers can verify the selected month, source files, joined rows and unmatched codes before
  creating a new snapshot.
