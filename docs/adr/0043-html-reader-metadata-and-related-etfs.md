# HTML reader metadata and related product cards

- Date: 2026-10-27
- Status: Accepted
- Supersedes in part: ADR-0042 for the continuous-HTML left rail.

The downloadable continuous HTML now uses a publication-style reader sidebar instead of
ticker-only links. It shows `CSOP Intelligence` as author, the date on which the HTML is rendered in
`Asia/Hong_Kong`, the `Product Insights` category, and script-free sharing links. Its authored-by,
date, category, share and related-products labels are black; product cards and interactive accents
retain the report template blue. The date is presentation metadata and is not written into the
finalized document or used as its report date.

The continuous HTML heading includes the product ticker and the `Monthly Commentary` suffix; for
3033 it is `CSOP Hang Seng TECH Index ETF (3033.HK) Monthly Commentary`. `Related Products`
contains English cards for 3033 CSOP Hang Seng TECH Index ETF and 3149 CSOP Hang
Seng Pioneer Technology Index ETF. The calls to action link to the corresponding official English
CSOP product pages. Desktop readers keep the sidebar fixed while the report scrolls. At 800px and
below it moves above the report so the expanded content does not make the report unreadably narrow.
Printing continues to suppress the sidebar, and paged preview/PDF/DOCX remain unchanged.

The Report Centre continues to display the stored report date, while its `Last updated` timestamp
is now explicitly formatted in Hong Kong time. The HTML renderer identity advances to
`html-reader-sidebar-v9`; no database migration or immutable document rewrite is required.
