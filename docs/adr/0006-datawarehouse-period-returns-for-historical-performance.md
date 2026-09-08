# ADR 0006: Data-warehouse period returns for Historical Performance

- Status: Accepted
- Date: 2026-08-13
- Supersedes: the Page 02 source and calculation decision in ADR-0004/ADR-0005
- Superseded in part by: ADR-0010 for the production connection transport

## Context

The approved CSOP data warehouse now exposes product returns in
`view_ads_busi_performance_class_returns_f_p` and benchmark returns in
`view_ads_busi_performance_index_returns_f_p`. Both views publish decimal period-return fields for
1M, 3M, 6M and YTD and join one-to-one on `(trade_date, class_id)`. For 3033, the approved master
mapping is `CO-CHST / CLS00178 / HSTECHN Index`; the unlisted `CLS00199` share class is excluded.

This source differs from §7.2 of the V2.1 execution specification, which requires the application
to derive returns from common Total Return endpoints. The business has explicitly selected the
warehouse's precomputed return fields for this page.

## Decision

Page 02 reads `returns_l1m`, `returns_l3m`, `returns_l6m`, and `returns_ytd` directly from the two
warehouse views. Values remain decimal ratios in snapshots and are multiplied by 100 only at the
display layer. For a selected report month, the adapter chooses the latest common product/index
row within that month, not a stale row from an earlier month, and records the effective date. It
also stores up to 12 monthly observations so reviewers can choose how many report months to inspect.

The source is read-only. Local development may use `DATAWAREHOUSE_SQLITE_PATH`; deployed workloads
must use a checksummed `DATAWAREHOUSE_OBJECT_URL` backed by TOS and an ephemeral cache. No PVC or
container-persistent media path is introduced.

The application does not fall back to DA-Report market returns, Yahoo, fixtures, or zero when the
authoritative warehouse route is enabled. Missing `CO-CHST / CLS00178` rows create a blocking,
auditable provider finding.

## Consequences

- Period start dates are not invented because the warehouse views do not expose the selected
  underlying start observations; lineage records the exact source field and effective end date.
- The refreshed 2026-08-17 `td_attribution_cdb_test_2025.db` contains 2025 coverage for the listed
  `CO-CHST / CLS00178` class and its `HSTECHN Index` benchmark in both performance tables. The
  unlisted `CLS00199` sibling remains explicitly excluded.
- The official Total Return CSV parser remains available only as a compatibility fallback when the
  warehouse performance route is explicitly disabled.
