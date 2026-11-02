# ADR-0046: Key Risks Reminder title

- Date: 2026-11-02
- Status: Accepted
- Supersedes in part: ADR-0045

The 3033 continuous-HTML notice above the report title now uses the approved heading
`Key Risks Reminder` instead of `IMPORTANT INFORMATION`. Its three approved body paragraphs,
product scope and placement remain unchanged. Paged preview, PDF and DOCX continue to omit this
reader-only notice.

The selected immutable resource advances to `csop-3033-important-information-v2` with a new
compiled checksum; v1 remains in the repository as historical evidence. HTML export audits record
the v2 identity, and the HTML renderer identity advances to `html-reader-compliance-v11` so
regenerated artifacts can be distinguished. No database migration or stored ReportDocument rewrite
is required.

Rollback selects the v1 resource and restores `html-reader-compliance-v10`.
