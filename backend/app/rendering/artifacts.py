from __future__ import annotations

import hashlib
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor
from playwright.sync_api import sync_playwright
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.storage import storage
from app.domain.document import content_manifests_match, render_content_manifest, review_display_title
from app.domain.localization import is_zh_hans, localized_portfolio_value, term
from app.domain.metrics.final_analytics import normalize_portfolio_rows
from app.domain.models import RenderArtifact, Report, ReportDocument
from .html import localized_document, pct, price, rebalancing_date_text, render_html, testing_banner


MIME = {"html": "text/html", "pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


def renderer_version_for(format_name: str) -> str:
    return (
        f"{settings.renderer_version}-paged-i18n-v2" if format_name == "pdf"
        else "html-continuous-i18n-v2" if format_name == "html"
        else "docx-paged-i18n-v2"
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _page_setup(section, page_number: int, language_mode: str, banner: dict | None = None) -> None:
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.top_margin, section.right_margin, section.bottom_margin, section.left_margin = Cm(0.7), Cm(1), Cm(1.5), Cm(1)
    header = section.header.paragraphs[0]
    header.text = term("monthly_commentary", language_mode)
    header.style = "Header"
    if banner:
        # DOCX has no cheap full-page watermark, so the lane rides in the running header, which
        # repeats on every page and survives printing just as the HTML/PDF watermark does.
        mark = header.add_run(f"    {banner['label']}")
        mark.bold = True
        mark.font.color.rgb = RGBColor.from_string(str(banner["color"]).lstrip("#").upper())
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    footer.add_run().add_picture(str(Path(__file__).parent / "static" / "csop-logo.png"), width=Cm(4.4))
    footer.add_run(f"  {page_number}")


def _shade(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def _table(document: Document, headers: list[str], rows: list[list[str]], blue_first: bool = False):
    table = document.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"
    for i, text in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = text
        _shade(cell, "2660AD")
        for run in cell.paragraphs[0].runs:
            run.font.color.rgb = RGBColor(255, 255, 255)
            run.font.bold = True
            run.font.size = Pt(8)
    for row in rows:
        cells = table.add_row().cells
        for i, text in enumerate(row):
            cells[i].text = text
            cells[i].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            if blue_first and i == 0:
                _shade(cells[i], "2660AD")
                for run in cells[i].paragraphs[0].runs:
                    run.font.color.rgb = RGBColor(255, 255, 255)
            for run in cells[i].paragraphs[0].runs:
                run.font.size = Pt(8)
    return table


def _set_east_asian_font(document: Document, font_name: str = "Noto Sans CJK SC") -> None:
    for style in document.styles:
        if not getattr(style, "font", None):
            continue
        style.font.name = font_name
        rpr = style.element.get_or_add_rPr()
        fonts = rpr.rFonts
        if fonts is None:
            fonts = OxmlElement("w:rFonts")
            rpr.append(fonts)
        fonts.set(qn("w:eastAsia"), font_name)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "li", "h2", "h3", "blockquote"}:
            self.parts.append("\n")


def _plain_html(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value)
    return " ".join("".join(parser.parts).split())


def render_docx(report: Report, content: dict, destination: Path) -> None:
    language_mode = str(content.get("language_mode") or report.language_mode or "EN")
    content = localized_document(content, language_mode)
    sections = content["sections"]
    banner = testing_banner(content)
    if banner and is_zh_hans(language_mode):
        banner = {**banner, "label": term("testing_label", language_mode)}
    document = Document()
    styles = document.styles
    styles["Normal"].font.name = "Calibri"
    styles["Normal"].font.size = Pt(10)
    for style_name in ["Title", "Heading 1", "Heading 2"]:
        styles[style_name].font.name = "Calibri"
        styles[style_name].font.color.rgb = RGBColor(34, 50, 127)
    if is_zh_hans(language_mode):
        _set_east_asian_font(document)
    _page_setup(document.sections[0], 1, language_mode, banner)
    document.add_heading((content.get("terminology_overrides") or {}).get("product_name") or report.product_name, 0)
    review = sections["month_in_review"]
    enable_review_layout = content.get("template_version") != "3033-v1"
    if enable_review_layout and review.get("blocks"):
        grouped: dict[int, list[dict]] = {}
        for block in sorted(review["blocks"], key=lambda item: (item["y"], item["x"], item["block_id"])):
            grouped.setdefault(block["y"], []).append(block)
        for block_row in grouped.values():
            layout_table = document.add_table(rows=1, cols=len(block_row))
            layout_table.autofit = False
            for cell, block in zip(layout_table.rows[0].cells, block_row):
                cell.width = Inches(7.1 * block["w"] / 12)
                heading = cell.paragraphs[0]
                run = heading.add_run(block["title"])
                run.bold = True
                run.font.color.rgb = RGBColor(34, 50, 127)
                alignment = {
                    "left": WD_ALIGN_PARAGRAPH.LEFT,
                    "center": WD_ALIGN_PARAGRAPH.CENTER,
                    "right": WD_ALIGN_PARAGRAPH.RIGHT,
                    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
                }.get(block.get("text_align"), WD_ALIGN_PARAGRAPH.LEFT)
                heading.alignment = alignment
                body = cell.add_paragraph(_plain_html(block["content"]))
                body.alignment = alignment
    else:
        document.add_heading(review_display_title(content), 1)
        document.add_paragraph(review["summary"])
        document.add_heading(term("key_drivers", language_mode), 1)
        for item in review["drivers"]:
            document.add_paragraph(f"{item['title']}\n{item['body']}", style="List Number")
        document.add_heading(term("areas_to_monitor", language_mode), 1)
        for item in review["monitor"]:
            document.add_paragraph(f"{item['title']}\n{item['body']}", style="List Number")
        document.add_heading(term("outlook", language_mode), 1)
        document.add_paragraph(review["outlook"])
    benchmark_name = (content.get("terminology_overrides") or {}).get("benchmark_name") or content["benchmark_name"]
    document.add_heading(term("historical_performance", language_mode, product=content["product_ticker"], benchmark=benchmark_name), 1)
    history = sections["historical_performance"]["rows"]
    _table(document, ["", term("return_1m", language_mode), term("return_3m", language_mode), term("return_6m", language_mode), term("return_ytd", language_mode)], [[x["name"], pct(x["return_1m"], language_mode), pct(x["return_3m"], language_mode), pct(x["return_6m"], language_mode), pct(x["return_ytd"], language_mode)] for x in history])
    document.add_paragraph(sections["footnotes"].get("historical", ""), style="Caption")

    _page_setup(document.add_section(WD_SECTION.NEW_PAGE), 2, language_mode, banner)
    document.add_heading(term("company_news", language_mode), 1)
    for item in sections["company_news"]:
        if not any(str(item.get(field) or "").strip() for field in ("title", "summary", "source_name")):
            continue
        paragraph = document.add_paragraph(style="List Bullet")
        run = paragraph.add_run(item["title"])
        run.bold = True; run.font.color.rgb = RGBColor(38, 96, 173)
        source_name = item.get("source_name")
        if source_name:
            paragraph.add_run("\n" + source_name)
        paragraph.add_run("\n" + item["summary"])

    _page_setup(document.add_section(WD_SECTION.NEW_PAGE), 3, language_mode, banner)
    heading = document.add_heading(term("constituent_performance", language_mode, index=getattr(report, "constituent_index_code", report.benchmark_code)), 1)
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    document.add_paragraph(f"({term('next_rebalancing_date', language_mode, date=rebalancing_date_text(content.get('next_rebalancing_date'), language_mode))})").alignment = WD_ALIGN_PARAGRAPH.CENTER
    constituents = sections["constituents"]
    _table(document, [term("stock_code", language_mode), term("stock_name", language_mode), term("closing_price_hkd", language_mode), term("weighting_pct", language_mode), term("return_1m", language_mode), term("return_3m", language_mode), term("return_6m", language_mode), term("return_ytd", language_mode)], [[str(x.get("security_code", "")), str(x.get("display_name") or ""), price(x.get("close_price"), language_mode), pct(x.get("weight"), language_mode), pct(x.get("return_1m"), language_mode), pct(x.get("return_3m"), language_mode), pct(x.get("return_6m"), language_mode), pct(x.get("return_ytd"), language_mode)] for x in constituents], blue_first=True)
    document.add_paragraph(sections["footnotes"].get("constituents", ""), style="Caption")

    _page_setup(document.add_section(WD_SECTION.NEW_PAGE), 4, language_mode, banner)
    analytics = sections["analytics"]
    document.add_heading(f"{term('top10', language_mode)} (%)", 1)
    _table(document, [term("issuer", language_mode), term("weight", language_mode)], [[x.get("display_issuer", ""), pct(x["weight"], language_mode)] for x in analytics["top10"]])
    document.add_heading(term("sector_breakdown", language_mode), 1)
    # Same chart snapshot the HTML/PDF donut reads, so the three formats can never drift apart
    # on order or precision. `display_value` already carries the "%" sign.
    sector_series = (analytics.get("sector_chart") or {}).get("series") or []
    industry_overrides = content.get("_industry_overrides") or {}
    _table(document, [term("sector", language_mode), term("weight", language_mode)], [[
        industry_overrides.get(str(x.get("code") or ""))
        or (x.get("label_zh_hans") if is_zh_hans(language_mode) else x.get("label"))
        or "",
        x["display_value"],
    ] for x in sector_series])
    document.add_heading(term("top_performers", language_mode, month=content["month_name"]), 1)
    _table(document, [term("issuer", language_mode), term("return", language_mode)], [[x.get("display_issuer", ""), pct(x["return"], language_mode)] for x in analytics["top"]])
    document.add_heading(term("bottom_performers", language_mode, month=content["month_name"]), 1)
    _table(document, [term("issuer", language_mode), term("return", language_mode)], [[x.get("display_issuer", ""), pct(x["return"], language_mode)] for x in analytics["bottom"]])
    document.add_heading(term("portfolio_analysis", language_mode, product=content["product_ticker"]), 1)
    portfolio_rows = normalize_portfolio_rows(analytics.get("portfolio"), "HKD")
    if is_zh_hans(language_mode):
        labels = {"AUM": "资产管理规模（百万港元）^", "AVERAGE_DAILY_TURNOVER": "平均每日成交额（百万港元）^^", "NUMBER_OF_HOLDINGS": "持仓数量"}
        for row in portfolio_rows:
            row["label"] = labels.get(row.get("metric_code"), row.get("label", ""))
            if row.get("display_value") == "N/A":
                row["display_value"] = term("no_data", language_mode)
            else:
                row["display_value"] = localized_portfolio_value(row.get("display_value"), language_mode)
    _table(document, [term("measure", language_mode), term("value", language_mode)], [[x["label"], x["display_value"]] for x in portfolio_rows])
    document.add_paragraph(sections["footnotes"].get("analytics", ""), style="Caption")
    document.save(destination)


def build_artifact(db: Session, report: Report, document: ReportDocument, format_name: str) -> RenderArtifact:
    if format_name not in MIME:
        raise ValueError(f"Unsupported format: {format_name}")
    content_manifest = render_content_manifest(document.content)
    existing = list(db.scalars(select(RenderArtifact).where(
        RenderArtifact.report_id == report.id,
        RenderArtifact.document_version == document.version,
    )))
    if any(not content_manifests_match(item.content_manifest, content_manifest) for item in existing):
        raise ValueError("QC-010: canonical content manifest differs across output formats")
    directory = settings.output_root / format_name
    directory.mkdir(parents=True, exist_ok=True)
    # The lane is part of the file's identity, not only of its contents: an artifact copied out of
    # the tool loses its database row but keeps its name.
    lane_prefix = "TESTING-" if str(document.content.get("lane", "PRODUCTION")) == "TESTING" else ""
    language_tag = "ZH-HANS" if report.language_mode == "ZH_HANS" else report.language_mode.replace("_", "-")
    destination = directory / f"{lane_prefix}{report.product_code}_{report.report_date.isoformat()}_{language_tag}_v{document.version}.{format_name}"
    if format_name == "html":
        html = render_html(report, document.content, layout_mode="continuous")
        destination.write_text(html, encoding="utf-8")
    elif format_name == "docx":
        render_docx(report, document.content, destination)
    else:
        html = render_html(report, document.content, layout_mode="paged")
        with TemporaryDirectory() as temp:
            source = Path(temp) / "report.html"
            source.write_text(html, encoding="utf-8")
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(source.as_uri(), wait_until="networkidle")
                page.evaluate("""async () => {
                    await document.fonts.ready;
                    await Promise.all(Array.from(document.images).map((image) => {
                        if (image.complete) return image.decode().catch(() => undefined);
                        return new Promise((resolve) => {
                            image.addEventListener('load', resolve, { once: true });
                            image.addEventListener('error', resolve, { once: true });
                        });
                    }));
                }""")
                overflow = page.evaluate("""() => Array.from(document.querySelectorAll('.report-page')).flatMap((reportPage) => {
                    const body = reportPage.querySelector('.page-body');
                    const footer = reportPage.querySelector('.page-footer');
                    if (!body || !footer) return [];
                    const bodyBottom = body.getBoundingClientRect().bottom;
                    const footerTop = footer.getBoundingClientRect().top;
                    return bodyBottom > footerTop
                        ? [{ page: reportPage.dataset.page, bodyBottom, footerTop }]
                        : [];
                })""")
                if overflow:
                    browser.close()
                    raise ValueError(f"PDF_LAYOUT_OVERFLOW: report content enters the footer safe area: {overflow}")
                page.pdf(path=str(destination), format="A4", print_background=True, margin={"top": "0", "right": "0", "bottom": "0", "left": "0"}, prefer_css_page_size=True)
                browser.close()
    object_key = f"{format_name}/{destination.name}"
    stored = storage.put_file(destination, object_key)
    artifact = RenderArtifact(
        report_id=report.id,
        document_version=document.version,
        format=format_name,
        storage_key=stored.key,
        mime_type=MIME[format_name],
        size_bytes=stored.size_bytes,
        checksum=stored.checksum,
        template_version=document.template_version,
        renderer_version=renderer_version_for(format_name),
        content_manifest=content_manifest,
    )
    db.add(artifact)
    db.commit()
    db.refresh(artifact)
    return artifact
