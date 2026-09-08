# ADR 0008: Keep Opinion Radar separate from Monthly Commentary

- Status: Accepted
- Date: 2026-08-18

## Context

The screenshots and business discovery describe an internal social-listening product named
Opinion Radar. Its primary user is Digital Finance, and its required domain includes social
posts, authors, interactions, monitored accounts, competitor mappings, sentiment events and an
operational response workflow.

This repository's authoritative V2.1 specification and implementation instead cover the Monthly
Commentary report platform. Its DA-Report integration supplies a news catalog and news sentiment;
it does not provide the social-post or account contracts required by Opinion Radar. Treating the
requested changes as Company News UI fixes would merge unrelated business domains and would make
the requested metrics impossible to audit.

The Opinion Radar implementation repository has not yet been identified, while the business has
asked for the requirements baseline to be written first.

## Decision

Opinion Radar is a separate product and does not become a module of the Monthly Commentary V2.1
platform. Its confirmed product baseline is documented in
`docs/spec/舆情雷达产品需求规格书_V1.0.md`.

The PRD may be stored temporarily in this repository for discovery and review. No Opinion Radar
runtime code, routes, database tables or deployment responsibilities are implicitly assigned to
the Monthly Commentary application by that temporary location.

When the authoritative Opinion Radar repository is identified, the PRD and this boundary decision
must be migrated or cross-referenced without losing their review history.

## Consequences

- Monthly Commentary V2.1 scope, modules, data contracts and acceptance gates remain unchanged.
- Opinion Radar requires its own Futu data-source contract, social-content model, permissions,
  event workflow, quality gates and production approvals.
- Existing DA-Report news sentiment cannot be used as a substitute for post, author, interaction,
  competitor or core-account data.
- Implementation work must not begin in this application merely because the PRD is stored here.
- The final repository and deployment boundary remain a P0 prerequisite for Opinion Radar release.
