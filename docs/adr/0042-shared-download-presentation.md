# Shared download presentation for existing reports

- Date: 2026-10-23
- Status: Accepted
- Supersedes in part: ADR-0039 and ADR-0041, for HTML reader links and DOCX data-footnote presentation.

The product owner requires the two ticker links and updated Word footnotes in all reports,
including re-downloads of existing finalized reports. These are exporter presentation rules,
not edits to the immutable source document. Template versions, financial facts, footnote text,
saved layout controls, document checksums and finalized-version selection remain unchanged.

Every continuous HTML download, regardless of product or template version, includes `3033`
and `3149` links to the approved CSOP product URLs. Both ticker-only cards stay fixed at the
left of the viewport during scrolling. Narrow screens retain a smaller fixed left rail; the
report reserves space for it, and the Review grid uses smaller screen-only gaps. Printing
hides the rail and restores full report width. Paged preview/PDF and DOCX do not gain links.

Every DOCX download places Historical Performance's footnote in the corresponding Review
section footer, including old v4 documents that previously put it below the table. It follows
the historical table's saved page and preserves available horizontal and footer-position
controls. All three data footnotes use Calibri Regular 8pt; paragraph alignment and spacing
remain available. The body copy and the disclaimer are not reformatted. Word recipients
still need Calibri installed; no proprietary font is committed or newly embedded in DOCX.

HTML and DOCX renderer identifiers advance to `html-fixed-sidebar-v7` and
`docx-shared-footer-v7`, so export audits distinguish the new presentation from earlier
downloads. Existing files on recipients' computers do not change; users must download again.
PDF retains its version-specific rendering behavior. No database migration or source-document
rewrite is needed.

Verification covers template versions v1-v6 and multiple products, Word footer XML and
unchanged source content, v4 continuation pages, and browser scrolling at 1440/390/320px.
A real finalized v2 report was downloaded through the signed HTML/DOCX endpoints: both links
and Calibri 8pt footer runs were verified, and its source version/checksum remained unchanged.