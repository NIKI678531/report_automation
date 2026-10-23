# Calibri data footnotes and ticker-only HTML links

- Date: 2026-10-22
- Status: Accepted
- Superseded in part by ADR-0042: all HTML downloads now use a fixed left ticker rail, and all DOCX downloads use the updated footer presentation, including old reports.
- Supersedes in part: ADR-0039 (Calibri/Carlito compatibility for new output)

## Decision

`3033-v6` retains presentation schema 3. Editable v1-v5 documents adapt in memory and persist
the new template/token version on a successful save. Existing finalized and archived documents
retain their original version and rendering rules. No stored document is overwritten.

The Review, Constituents and Analytics data footnotes use Calibri Regular, 8pt, black, with
default 1.2 line spacing. Review retains its existing paragraph alignment/spacing controls,
twelve-column position/width, and 16-36mm footer bottom distance (20mm by default). It follows
Historical Performance to the selected opening page. Paged preview/PDF and DOCX use the footer
band; continuous HTML keeps the footnote after its associated content, not at the viewport bottom.
Report body typography and the fixed disclaimer are outside this change.

Only v6 continuous HTML for product code `3033` adds two links outside the report body:

- `3033`: https://www.csopasset.com/tc/products/co-chst
- `3149`: https://www.csopasset.com/tc/products/hk-cptc

Each whole card is a link. Its only visible text is the ticker: no fund names, descriptions or
button captions. Desktop places the cards to the left; narrow screens place them above the
report. Browser printing hides the sidebar and restores the report width. Paged preview, PDF,
DOCX, legacy templates and other products do not include it. Links open a new tab with
`noopener noreferrer`; no scripts, external assets or CSP changes are needed.

## Font Provisioning

Set `CALIBRI_FONT_PATH` to an absolute path to **Calibri Regular TTF** that the organization is
licensed to use on the server and embed in downloadable HTML/PDF. Font availability on Windows
alone does not establish redistribution or web-embedding rights. Do not commit the font to this
repository. Font resources and permission must be confirmed by the deployment owner.

For containers, an approved image build can supply the licensed font in a read-only image layer
and set the environment variable to its in-container path. No PVC or writable persistent font
directory is needed. The standard image does not include proprietary Calibri; configure both
the production image and the render-test runner before releasing v6 output.

HTML embeds the configured face under a footnote-only `Report Calibri` alias, so an offline
recipient does not depend on a locally installed font. Missing/unreadable/non-TTF input returns
503 `CALIBRI_FONT_UNAVAILABLE` without leaking filesystem paths. Chromium layout/export also
checks that this face actually loaded; it must not silently fall back to Carlito. Chinese glyphs
retain the existing Noto fallback. DOCX declares Calibri for Latin text and keeps the language's
East Asian font; Word recipients must have Calibri installed. This change does not embed fonts
in DOCX or establish permission to redistribute font files.

## Verification

- Domain/render tests: `backend/tests/test_page_one_presentation_v5.py`, including v4/v5
  compatibility, v6 geometry preservation, missing-font errors, DOCX footer XML, and the
  product/version/output-mode sidebar matrix.
- Its real-font test uses `CALIBRI_FONT_PATH`, or the installed Windows Calibri for local testing,
  and skips explicitly if unavailable. It generates desktop/mobile screenshots, checks print
  hiding, measures 16/20/36mm footer positions and inspects the actual three-page PDF font names.
- ReviewCanvas and ReviewModule tests cover locked typography and moving, saving, previewing,
  and reloading the footnote. The API tests verify the remote preview route and readable errors.
- In this checkout, full backend collection is blocked by the pre-existing missing
  `load_monthly_turnover` import in `app.integrations.da_report`. Rendering tests can be run with
  `--noconftest -o pythonpath=backend`; this does not substitute for a full API lifecycle test.

No production font was installed, service started, database migrated, or deployment performed.