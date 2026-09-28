from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from io import BytesIO
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_ROW_HEIGHT_RULE, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from app.core.config import settings
from app.domain.document import checksum as structured_checksum
from app.domain.document import render_content_manifest, review_display_title
from app.domain.localization import (
    is_chinese,
    is_zh_hans,
    is_zh_hant,
    localized_portfolio_label,
    localized_portfolio_value,
    term,
)
from app.domain.metrics.final_analytics import normalize_portfolio_rows
from app.domain.models import Report, ReportDocument
from app.domain.page_one_presentation import page_one_presentation
from .disclaimer import disclaimer_audit_fields, load_disclaimer
from .html import (
    _render_tokens,
    localized_document,
    long_date,
    pct,
    price,
    rebalancing_date_text,
    render_html,
    sector_chart,
    testing_banner,
)


MIME = {"html": "text/html", "pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


def renderer_version_for(format_name: str) -> str:
    return (
        f"{settings.renderer_version}-paged-i18n-v4" if format_name == "pdf"
        else "html-continuous-i18n-v4" if format_name == "html"
        else "docx-paged-i18n-v4"
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _font_name(tokens: dict[str, Any], language_mode: str) -> str:
    if is_zh_hans(language_mode):
        return "Noto Sans CJK SC"
    if is_zh_hant(language_mode):
        return "Noto Sans CJK TC"
    return str(tokens["font"]["family"]).split(",", 1)[0].strip().strip('"')


def _set_run_font(
    run,
    font_name: str,
    *,
    size: float | None = None,
    bold: bool | None = None,
    color: RGBColor | None = None,
) -> None:
    run.font.name = font_name
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if color is not None:
        run.font.color.rgb = color
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    for attribute in ("ascii", "hAnsi", "eastAsia", "cs"):
        rfonts.set(qn(f"w:{attribute}"), font_name)


def _set_paragraph_border(paragraph, *, color: str | None = None, size: int = 4, space: int = 1) -> None:
    ppr = paragraph._p.get_or_add_pPr()
    existing = ppr.find(qn("w:pBdr"))
    if existing is not None:
        ppr.remove(existing)
    if not color:
        return
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(size))
    bottom.set(qn("w:space"), str(space))
    bottom.set(qn("w:color"), color)
    borders.append(bottom)
    ppr.append(borders)


def _set_cell_margins(cell, *, top: int = 0, right: int = 0, bottom: int = 0, left: int = 0) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_mar = tc_pr.find(qn("w:tcMar"))
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for edge, value in (("top", top), ("right", right), ("bottom", bottom), ("left", left)):
        node = tc_mar.find(qn(f"w:{edge}"))
        if node is None:
            node = OxmlElement(f"w:{edge}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def _set_cell_borders(cell, *, color: str | None = None, size: int = 4, edges: tuple[str, ...] = ("top", "left", "bottom", "right")) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_borders = tc_pr.find(qn("w:tcBorders"))
    if tc_borders is None:
        tc_borders = OxmlElement("w:tcBorders")
        tc_pr.append(tc_borders)
    for edge in edges:
        node = tc_borders.find(qn(f"w:{edge}"))
        if node is None:
            node = OxmlElement(f"w:{edge}")
            tc_borders.append(node)
        node.set(qn("w:val"), "single" if color else "nil")
        if color:
            node.set(qn("w:sz"), str(size))
            node.set(qn("w:color"), color)


def _set_table_geometry(table, widths: list[int], *, indent: int = 0) -> None:
    table.autofit = False
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    tbl_pr = table._tbl.tblPr
    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:type"), "dxa")
    tbl_w.set(qn("w:w"), str(sum(widths)))
    tbl_ind = tbl_pr.find(qn("w:tblInd"))
    if tbl_ind is None:
        tbl_ind = OxmlElement("w:tblInd")
        tbl_pr.append(tbl_ind)
    tbl_ind.set(qn("w:type"), "dxa")
    tbl_ind.set(qn("w:w"), str(indent))
    layout = tbl_pr.find(qn("w:tblLayout"))
    if layout is None:
        layout = OxmlElement("w:tblLayout")
        tbl_pr.append(layout)
    layout.set(qn("w:type"), "fixed")
    grid = table._tbl.tblGrid
    for child in list(grid):
        grid.remove(child)
    for width in widths:
        col = OxmlElement("w:gridCol")
        col.set(qn("w:w"), str(width))
        grid.append(col)
    for row in table.rows:
        for index, cell in enumerate(row.cells[: len(widths)]):
            tc_w = cell._tc.get_or_add_tcPr().get_or_add_tcW()
            tc_w.set(qn("w:type"), "dxa")
            tc_w.set(qn("w:w"), str(widths[index]))


def _set_table_borders(table, *, color: str | None = None, size: int = 4) -> None:
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.find(qn("w:tblBorders"))
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        node = borders.find(qn(f"w:{edge}"))
        if node is None:
            node = OxmlElement(f"w:{edge}")
            borders.append(node)
        node.set(qn("w:val"), "single" if color else "nil")
        if color:
            node.set(qn("w:sz"), str(size))
            node.set(qn("w:color"), color)


def _prevent_row_split(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    if tr_pr.find(qn("w:cantSplit")) is None:
        tr_pr.append(OxmlElement("w:cantSplit"))


def _repeat_table_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    if tr_pr.find(qn("w:tblHeader")) is None:
        tr_pr.append(OxmlElement("w:tblHeader"))


def _usable_width_twips(section) -> int:
    return int((section.page_width - section.left_margin - section.right_margin) / 635)


def _format_paragraph(
    paragraph,
    *,
    alignment: WD_ALIGN_PARAGRAPH | None = None,
    before: float = 0,
    after: float = 0,
    line_spacing: float = 1.0,
    keep_with_next: bool | None = None,
) -> None:
    if alignment is not None:
        paragraph.alignment = alignment
    paragraph.paragraph_format.space_before = Pt(before)
    paragraph.paragraph_format.space_after = Pt(after)
    paragraph.paragraph_format.line_spacing = line_spacing
    paragraph.paragraph_format.widow_control = True
    if keep_with_next is not None:
        paragraph.paragraph_format.keep_with_next = keep_with_next


def _clear_paragraph(paragraph) -> None:
    for child in list(paragraph._p):
        if child.tag != qn("w:pPr"):
            paragraph._p.remove(child)


def _set_run_vertical_position(run, points: float) -> None:
    """Raise/lower glyphs without moving the fixed Word footer logo or page number."""

    properties = run._r.get_or_add_rPr()
    existing = properties.find(qn("w:position"))
    if existing is not None:
        properties.remove(existing)
    position = OxmlElement("w:position")
    position.set(qn("w:val"), str(int(round(points * 2))))
    properties.append(position)


def _footer_table(
    section,
    page_number: int,
    footnote: str,
    font_name: str,
    *,
    footnote_paragraphs: list[dict[str, Any]] | None = None,
    footnote_bottom_nudge_pt: float = 0,
) -> None:
    footer = section.footer
    footer.is_linked_to_previous = False
    for table in list(footer.tables):
        table._element.getparent().remove(table._element)
    anchor = footer.paragraphs[0]
    _clear_paragraph(anchor)
    footnote_spacing_after = {1: 5.25, 3: 3.5, 4: 3.6}.get(page_number, 2.5)
    footnote_line_spacing = Pt(13.7) if page_number == 3 and footnote else 1.0
    if footnote_paragraphs is not None and footnote:
        for index, item in enumerate(footnote_paragraphs):
            paragraph = anchor if index == 0 else footer.add_paragraph()
            _clear_paragraph(paragraph)
            alignment = {
                "center": WD_ALIGN_PARAGRAPH.CENTER,
                "right": WD_ALIGN_PARAGRAPH.RIGHT,
                "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
            }.get(str(item.get("text_align") or "left"), WD_ALIGN_PARAGRAPH.LEFT)
            _format_paragraph(
                paragraph,
                alignment=alignment,
                after=footnote_spacing_after
                if index == len(footnote_paragraphs) - 1 else 1,
                line_spacing=Pt(
                    float(item.get("font_size_pt") or 8)
                    * float(item.get("line_height") or 1.2)
                ),
            )
            paragraph.paragraph_format.left_indent = Pt(0.5)
            paragraph.paragraph_format.right_indent = Pt(-7.5)
            run = paragraph.add_run(str(item.get("text") or ""))
            _set_run_font(
                run,
                font_name,
                size=float(item.get("font_size_pt") or 8),
                color=RGBColor(0, 0, 0),
            )
            _set_run_vertical_position(run, footnote_bottom_nudge_pt)
    else:
        _format_paragraph(
            anchor,
            after=footnote_spacing_after if footnote else 0,
            line_spacing=footnote_line_spacing,
        )
        anchor.paragraph_format.left_indent = Pt(0.5)
        anchor.paragraph_format.right_indent = Pt(-7.5)
        if footnote:
            _set_run_font(anchor.add_run(footnote), font_name, size=10, color=RGBColor(0, 0, 0))
        else:
            anchor.paragraph_format.line_spacing = Pt(1)
            _set_run_font(anchor.add_run("\u200b"), font_name, size=1, color=RGBColor(255, 255, 255))

    # The reference stacks the footnote, logo and page number vertically. The table extends
    # into the right page margin so the logo and folio align with the PDF rather than the body.
    table = footer.add_table(rows=2, cols=1, width=Cm(19.54))
    widths = [11080]
    _set_table_geometry(table, widths)
    _set_table_borders(table)
    for row in table.rows:
        _prevent_row_split(row)
        cell = row.cells[0]
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.BOTTOM
        _set_cell_margins(cell, top=0, right=0, bottom=0, left=0)
        _set_cell_borders(cell)

    logo_cell = table.rows[0].cells[0]
    _set_cell_margins(logo_cell, top=0, right=167, bottom=0, left=0)
    logo_paragraph = logo_cell.paragraphs[0]
    _clear_paragraph(logo_paragraph)
    _format_paragraph(logo_paragraph, alignment=WD_ALIGN_PARAGRAPH.RIGHT, after=0, line_spacing=1.0)
    logo_paragraph.add_run().add_picture(
        str(Path(__file__).parent / "static" / "csop-logo.png"), width=Cm(4.6)
    )

    number_row = table.rows[1]
    number_row.height = Pt(8.5)
    number_row.height_rule = WD_ROW_HEIGHT_RULE.EXACTLY
    number_paragraph = number_row.cells[0].paragraphs[0]
    _clear_paragraph(number_paragraph)
    _format_paragraph(number_paragraph, alignment=WD_ALIGN_PARAGRAPH.RIGHT, after=0, line_spacing=Pt(8.5))
    _set_run_font(number_paragraph.add_run(str(page_number)), font_name, size=8, color=RGBColor(119, 119, 119))


def _page_setup(
    section,
    page_number: int,
    report: Report,
    language_mode: str,
    tokens: dict[str, Any],
    *,
    footnote: str = "",
    footnote_paragraphs: list[dict[str, Any]] | None = None,
    footnote_bottom_nudge_pt: float = 0,
    banner: dict | None = None,
) -> None:
    page = tokens["page"]
    deep = str(tokens["color"]["brandDeep"]).lstrip("#").upper()
    font_name = _font_name(tokens, language_mode)
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    reference_top_margin_mm = {1: 9.88, 2: 12.87, 3: 14.38, 4: 15.25}.get(
        page_number, float(page["marginTopMm"])
    )
    section.top_margin = Cm(reference_top_margin_mm / 10)
    section.right_margin = Cm(float(page["marginRightMm"]) / 10)
    section.bottom_margin = Cm(float(page["marginBottomMm"]) / 10)
    section.left_margin = Cm(float(page["marginLeftMm"]) / 10)
    section.header_distance = Pt(11.3)
    section.footer_distance = Pt(7)
    section.header.is_linked_to_previous = False
    section.footer.is_linked_to_previous = False
    header = section.header.paragraphs[0]
    _clear_paragraph(header)
    header.style = "Header"
    _format_paragraph(header, after=0, line_spacing=1.0)
    header.paragraph_format.left_indent = Pt(-6.4)
    header.paragraph_format.first_line_indent = Pt(8.2)
    header.paragraph_format.right_indent = Pt(-7.6)
    _set_run_font(
        header.add_run(f"{term('monthly_commentary', language_mode)} | {long_date(report.report_date, language_mode)}"),
        font_name,
        size=12,
        color=RGBColor.from_string(deep),
    )
    if banner:
        mark = header.add_run(f"    {banner['label']}")
        _set_run_font(
            mark,
            font_name,
            size=7,
            bold=True,
            color=RGBColor.from_string(str(banner["color"]).lstrip("#").upper()),
        )
    _set_paragraph_border(header, color=None if page_number == 1 else deep, size=2, space=12)
    _footer_table(
        section,
        page_number,
        footnote,
        font_name,
        footnote_paragraphs=footnote_paragraphs,
        footnote_bottom_nudge_pt=footnote_bottom_nudge_pt,
    )


def _shade(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    existing = tc_pr.find(qn("w:shd"))
    if existing is not None:
        tc_pr.remove(existing)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def _table(
    parent,
    headers: list[str] | None,
    rows: list[list[str]],
    *,
    widths: list[int],
    font_name: str,
    blue: str,
    font_size: float = 10,
    header_font_size: float | None = None,
    blue_first: bool = False,
    body_borders: bool = False,
    alignments: list[WD_ALIGN_PARAGRAPH] | None = None,
    header_height_cm: float | None = None,
    row_height_cm: float | None = None,
    line_height: float | None = None,
):
    table = parent.add_table(rows=1 if headers is not None else 0, cols=len(widths))
    _set_table_geometry(table, widths)
    _set_table_borders(table, color="000000" if body_borders else None, size=4)
    if headers is not None:
        header_row = table.rows[0]
        _repeat_table_header(header_row)
        _prevent_row_split(header_row)
        if header_height_cm:
            header_row.height = Cm(header_height_cm)
            header_row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
        for index, text in enumerate(headers):
            cell = header_row.cells[index]
            cell.text = text
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            _shade(cell, blue)
            _set_cell_margins(cell, top=75, right=55, bottom=75, left=55)
            _set_cell_borders(cell, color="FFFFFF", size=5)
            paragraph = cell.paragraphs[0]
            resolved_header_size = header_font_size or font_size
            _format_paragraph(
                paragraph,
                alignment=WD_ALIGN_PARAGRAPH.CENTER,
                line_spacing=Pt(resolved_header_size * line_height)
                if line_height is not None else 1.0,
            )
            for run in paragraph.runs:
                _set_run_font(
                    run,
                    font_name,
                    size=resolved_header_size,
                    bold=True,
                    color=RGBColor(255, 255, 255),
                )
    for values in rows:
        row = table.add_row()
        _prevent_row_split(row)
        if row_height_cm:
            row.height = Cm(row_height_cm)
            row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
        for index, text in enumerate(values):
            cell = row.cells[index]
            cell.text = text
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            _set_cell_margins(cell, top=35, right=55, bottom=35, left=55)
            if body_borders:
                _set_cell_borders(cell, color="595959", size=3)
            else:
                _set_cell_borders(cell)
            color = RGBColor(0, 0, 0)
            if blue_first and index == 0:
                _shade(cell, blue)
                _set_cell_borders(cell, color="FFFFFF", size=5, edges=("top", "bottom", "left", "right"))
                color = RGBColor(255, 255, 255)
            paragraph = cell.paragraphs[0]
            alignment = alignments[index] if alignments else WD_ALIGN_PARAGRAPH.LEFT
            _format_paragraph(
                paragraph,
                alignment=alignment,
                line_spacing=Pt(font_size * line_height)
                if line_height is not None else 1.0,
            )
            for run in paragraph.runs:
                _set_run_font(run, font_name, size=font_size, color=color)
    # Rows appended after the initial grid need their tcW values materialized as well.
    _set_table_geometry(table, widths)
    return table


def _style_font(style, font_name: str, size: float, *, bold: bool = False, color: RGBColor | None = None) -> None:
    style.font.name = font_name
    style.font.size = Pt(size)
    style.font.bold = bold
    if color is not None:
        style.font.color.rgb = color
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    for attribute in ("ascii", "hAnsi", "eastAsia", "cs"):
        rfonts.set(qn(f"w:{attribute}"), font_name)


def _configure_styles(document: Document, tokens: dict[str, Any], language_mode: str) -> None:
    font_name = _font_name(tokens, language_mode)
    deep = RGBColor.from_string(str(tokens["color"]["brandDeep"]).lstrip("#").upper())
    fonts = tokens["font"]
    _style_font(document.styles["Normal"], font_name, float(fonts["bodyPt"]), color=RGBColor(0, 0, 0))
    _style_font(document.styles["Title"], font_name, float(fonts["reportTitlePt"]), bold=True, color=deep)
    _style_font(document.styles["Heading 1"], font_name, float(fonts["sectionPt"]), bold=True, color=deep)
    _style_font(document.styles["Heading 2"], font_name, 12, bold=True, color=deep)
    _style_font(document.styles["Header"], font_name, 12, color=deep)
    _style_font(document.styles["Caption"], font_name, float(fonts["smallPt"]), color=RGBColor(0, 0, 0))
    for name in ("List Bullet", "List Number"):
        _style_font(document.styles[name], font_name, float(fonts["bodyPt"]), color=RGBColor(0, 0, 0))
    normal = document.styles["Normal"].paragraph_format
    normal.space_before = Pt(0)
    normal.space_after = Pt(3)
    normal.line_spacing = 1.0
    title = document.styles["Title"].paragraph_format
    title.space_before = Pt(0)
    title.space_after = Pt(7)
    title.line_spacing = 1.0
    title.keep_with_next = True
    for name in ("Heading 1", "Heading 2"):
        paragraph_format = document.styles[name].paragraph_format
        paragraph_format.space_before = Pt(6)
        paragraph_format.space_after = Pt(4)
        paragraph_format.line_spacing = 1.0
        paragraph_format.keep_with_next = True
    caption = document.styles["Caption"].paragraph_format
    caption.space_before = Pt(2)
    caption.space_after = Pt(0)
    caption.line_spacing = 1.0


class _RichTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.blocks: list[
            tuple[list[tuple[str, bool, bool]], dict[str, str], str | None]
        ] = []
        self.current: list[tuple[str, bool, bool]] = []
        self.current_style: dict[str, str] = {}
        self.current_marker: str | None = None
        self.list_stack: list[dict[str, int | str]] = []
        self.list_item_depth = 0
        self.bold_depth = 0
        self.italic_depth = 0

    def _flush(self) -> None:
        while self.current and not self.current[-1][0]:
            self.current.pop()
        if self.current:
            self.blocks.append((self.current, self.current_style, self.current_marker))
        self.current = []
        self.current_style = {}
        self.current_marker = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"ol", "ul"}:
            self._flush()
            self.list_stack.append({"tag": tag, "counter": 0})
        elif tag == "li":
            self._flush()
            self.current_style = {str(key): str(value or "") for key, value in attrs}
            self.list_item_depth += 1
            if self.list_stack and self.list_stack[-1]["tag"] == "ol":
                self.list_stack[-1]["counter"] = int(self.list_stack[-1]["counter"]) + 1
                self.current_marker = f"{self.list_stack[-1]['counter']}. "
            else:
                self.current_marker = "• "
        elif tag in {"p", "h2", "h3", "blockquote"}:
            if self.list_item_depth:
                if self.current and self.current[-1][0] != "\n":
                    self.current.append(("\n", self.bold_depth > 0, self.italic_depth > 0))
                if attrs and not self.current_style:
                    self.current_style = {str(key): str(value or "") for key, value in attrs}
            else:
                self._flush()
                self.current_style = {str(key): str(value or "") for key, value in attrs}
        elif tag in {"strong", "b"}:
            self.bold_depth += 1
        elif tag in {"em", "i"}:
            self.italic_depth += 1
        elif tag == "br":
            self.current.append(("\n", self.bold_depth > 0, self.italic_depth > 0))

    def handle_data(self, data: str) -> None:
        text = data.replace("\xa0", " ")
        if text:
            self.current.append((text, self.bold_depth > 0, self.italic_depth > 0))

    def handle_endtag(self, tag: str) -> None:
        if tag in {"strong", "b"}:
            self.bold_depth = max(0, self.bold_depth - 1)
        elif tag in {"em", "i"}:
            self.italic_depth = max(0, self.italic_depth - 1)
        elif tag == "li":
            self._flush()
            self.list_item_depth = max(0, self.list_item_depth - 1)
        elif tag in {"p", "h2", "h3", "blockquote"} and not self.list_item_depth:
            self._flush()
        elif tag in {"ol", "ul"}:
            self._flush()
            if self.list_stack:
                self.list_stack.pop()

    def close(self) -> None:
        super().close()
        self._flush()


def _append_rich_text(
    parent,
    value: str,
    *,
    font_name: str,
    size: float,
    alignment,
    style_roles: dict[str, Any] | None = None,
) -> None:
    parser = _RichTextExtractor()
    parser.feed(value)
    parser.close()
    defaults = ((style_roles or {}).get("defaults") or {})
    for segments, attributes, marker in parser.blocks:
        paragraph = parent.add_paragraph()
        resolved_alignment = {
            "left": WD_ALIGN_PARAGRAPH.LEFT,
            "center": WD_ALIGN_PARAGRAPH.CENTER,
            "right": WD_ALIGN_PARAGRAPH.RIGHT,
            "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
        }.get(attributes.get("data-text-align", ""), alignment)
        resolved_line_height = float(
            ((style_roles or {}).get("line_height") or {}).get(
                attributes.get("data-line-height-role"),
                defaults.get("review_line_height", 1.0),
            )
        )
        resolved_size = float(
            ((style_roles or {}).get("font_size_pt") or {}).get(
                attributes.get("data-font-size-role"), size
            )
        )
        _format_paragraph(
            paragraph,
            alignment=resolved_alignment,
            after=1.5,
            # Word interprets a numeric value as a multiple of its font-dependent "single"
            # line height, which is taller than CSS font-size * line-height. Use exact points so
            # the DOCX pagination follows the same 1.0/1.2/1.4 contract as HTML/PDF.
            line_spacing=Pt(resolved_size * resolved_line_height),
        )
        if marker:
            paragraph.paragraph_format.left_indent = Cm(0.45)
            paragraph.paragraph_format.first_line_indent = Cm(-0.35)
            _set_run_font(
                paragraph.add_run(marker),
                font_name,
                size=resolved_size,
                color=RGBColor(0, 0, 0),
            )
        for text, bold, italic in segments:
            run = paragraph.add_run(text)
            _set_run_font(
                run,
                font_name,
                size=resolved_size,
                bold=bold,
                color=RGBColor(0, 0, 0),
            )
            run.italic = italic


def _remove_initial_empty_paragraph(cell) -> None:
    if cell.paragraphs and not cell.paragraphs[0].text and len(cell._tc) > 1:
        cell._tc.remove(cell.paragraphs[0]._element)


def _review_block(
    parent,
    block: dict[str, Any],
    *,
    font_name: str,
    font_size: float,
    deep: RGBColor,
    style_roles: dict[str, Any] | None = None,
) -> None:
    heading = next(
        (paragraph for paragraph in reversed(parent.paragraphs) if not paragraph.text),
        None,
    ) if hasattr(parent, "paragraphs") else None
    if heading is None:
        heading = parent.add_paragraph()
    _clear_paragraph(heading)
    _format_paragraph(
        heading,
        # Word does not accept negative paragraph spacing. Negative nudges are fully represented
        # by the canonical HTML/PDF preview and its collision preflight; DOCX consumes as much of
        # the preceding gap as its flow model can express without producing an invalid document.
        before=max(0.0, 2 + float(block.get("vertical_nudge_pt") or 0)),
        after=3,
        line_spacing=1.0,
        keep_with_next=True,
    )
    heading_run = heading.add_run(str(block.get("title") or ""))
    _set_run_font(heading_run, font_name, size=14, bold=True, color=deep)
    alignment = {
        "center": WD_ALIGN_PARAGRAPH.CENTER,
        "right": WD_ALIGN_PARAGRAPH.RIGHT,
        "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
    }.get(str(block.get("text_align") or "left"), WD_ALIGN_PARAGRAPH.LEFT)
    heading.alignment = alignment
    _append_rich_text(
        parent,
        str(block.get("content") or ""),
        font_name=font_name,
        size=font_size,
        alignment=alignment,
        style_roles=style_roles,
    )


def _review_flow(
    parent,
    node: dict[str, Any],
    *,
    width: int,
    font_name: str,
    font_size: float,
    deep: RGBColor,
    style_roles: dict[str, Any] | None = None,
) -> None:
    """Render the resolver's content-driven flow tree into Word tables and paragraphs."""

    if node["kind"] == "block":
        _review_block(
            parent,
            node["block"],
            font_name=font_name,
            font_size=font_size,
            deep=deep,
            style_roles=style_roles,
        )
        return

    children = list(node.get("children") or [])
    if node["kind"] == "stack":
        for child in children:
            _review_flow(
                parent,
                child,
                width=width,
                font_name=font_name,
                font_size=font_size,
                deep=deep,
                style_roles=style_roles,
            )
        return

    def append_grid_row(child_nodes: list[dict[str, Any]]) -> None:
        column_count = max(1, int(node["w"]))
        if hasattr(parent, "_tc"):
            _remove_initial_empty_paragraph(parent)
        table = parent.add_table(rows=1, cols=column_count)
        unit = width // column_count
        widths = [unit] * (column_count - 1) + [width - unit * (column_count - 1)]
        _set_table_geometry(table, widths)
        _set_table_borders(table)
        row = table.rows[0]
        _prevent_row_split(row)
        occupied: set[int] = set()
        for child in child_nodes:
            start = max(0, min(column_count - 1, int(child["x"]) - int(node["x"])))
            span = max(1, min(column_count - start, int(child["w"])))
            cell = row.cells[start].merge(row.cells[start + span - 1])
            occupied.update(range(start, start + span))
            for redundant in list(cell.paragraphs[1:]):
                cell._tc.remove(redundant._element)
            _clear_paragraph(cell.paragraphs[0])
            _set_cell_borders(cell)
            _set_cell_margins(
                cell,
                top=0,
                right=225 if start + span < column_count else 0,
                bottom=45,
                left=225 if start else 0,
            )
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
            child_width = sum(widths[start:start + span])
            _review_flow(
                cell,
                child,
                width=child_width,
                font_name=font_name,
                font_size=font_size,
                deep=deep,
                style_roles=style_roles,
            )
        for index in range(column_count):
            if index not in occupied:
                cell = row.cells[index]
                _set_cell_borders(cell)
                _set_cell_margins(cell)

    if node["kind"] == "columns":
        append_grid_row(children)
        return
    for child in children:
        append_grid_row([child])


def _review_layout(
    document: Document,
    layout: dict[str, Any],
    *,
    width: int,
    font_name: str,
    font_size: float,
    deep: RGBColor,
    style_roles: dict[str, Any] | None = None,
) -> None:
    _review_flow(
        document,
        layout,
        width=width,
        font_name=font_name,
        font_size=font_size,
        deep=deep,
        style_roles=style_roles,
    )


def _legacy_review(document: Document, content: dict[str, Any], language_mode: str, width: int, font_name: str, deep: RGBColor) -> None:
    review = content["sections"]["month_in_review"]
    heading = document.add_heading(review_display_title(content), 1)
    _format_paragraph(heading, before=0, after=4, keep_with_next=True)
    summary = document.add_paragraph(str(review.get("summary") or ""))
    _format_paragraph(summary, after=3, line_spacing=1.0)
    columns = document.add_table(rows=1, cols=2)
    _set_table_geometry(columns, [width // 2, width - width // 2])
    _set_table_borders(columns)
    for index, (title, items) in enumerate((
        (term("key_drivers", language_mode), review.get("drivers") or []),
        (term("areas_to_monitor", language_mode), review.get("monitor") or []),
    )):
        cell = columns.rows[0].cells[index]
        _set_cell_borders(cell)
        _set_cell_margins(cell, right=225 if index == 0 else 0, left=225 if index == 1 else 0)
        p = cell.paragraphs[0]
        _clear_paragraph(p)
        _format_paragraph(p, after=3, keep_with_next=True)
        _set_run_font(p.add_run(title), font_name, size=14, bold=True, color=deep)
        for item in items:
            p = cell.add_paragraph(style="List Number")
            _format_paragraph(p, after=2, line_spacing=1.0)
            _set_run_font(p.add_run(str(item.get("title") or "")), font_name, size=10, bold=True)
            p.add_run().add_break()
            _set_run_font(p.add_run(str(item.get("body") or "")), font_name, size=10)
    right = columns.rows[0].cells[1]
    p = right.add_paragraph()
    _format_paragraph(p, before=5, after=3, keep_with_next=True)
    _set_run_font(p.add_run(term("outlook", language_mode)), font_name, size=14, bold=True, color=deep)
    p = right.add_paragraph(str(review.get("outlook") or ""))
    _format_paragraph(p, after=0, line_spacing=1.0)


def _add_blue_title(parent, title: str, second: str | None, *, width: int, font_name: str, blue: str) -> None:
    table = parent.add_table(rows=1, cols=2 if second else 1)
    widths = [int(width * 0.78), width - int(width * 0.78)] if second else [width]
    _set_table_geometry(table, widths)
    _set_table_borders(table, color=blue, size=4)
    for index, cell in enumerate(table.rows[0].cells):
        _shade(cell, blue)
        _set_cell_margins(cell, top=95, right=65, bottom=95, left=65)
        _set_cell_borders(cell, color=blue, size=4)
        p = cell.paragraphs[0]
        _clear_paragraph(p)
        _format_paragraph(p, alignment=WD_ALIGN_PARAGRAPH.CENTER)
        text = title if index == 0 else str(second)
        _set_run_font(p.add_run(text), font_name, size=12, bold=True, color=RGBColor(255, 255, 255))


def _font_for_chart(size: int, font_name: str, *, bold: bool = False):
    from PIL import ImageFont

    if font_name == "Noto Sans CJK SC":
        candidates = [
            Path("C:/Windows/Fonts/NotoSansSC-VF.ttf"),
            Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        ]
    else:
        candidates = [
            Path("C:/Windows/Fonts/calibrib.ttf" if bold else "C:/Windows/Fonts/calibri.ttf"),
            Path("/usr/share/fonts/truetype/crosextra/Carlito-Bold.ttf" if bold else "/usr/share/fonts/truetype/crosextra/Carlito-Regular.ttf"),
        ]
    candidates.append(Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _sector_chart_image(chart: dict[str, Any], source_series: list[dict[str, Any]], font_name: str) -> BytesIO:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (900, 680), "white")
    draw = ImageDraw.Draw(image)
    center = (450, 340)
    outer, inner = 265, 148
    box = (center[0] - outer, center[1] - outer, center[0] + outer, center[1] + outer)
    label_font = _font_for_chart(29, font_name)
    for display, source in zip(chart.get("rows") or [], source_series):
        start = float(source.get("start_angle") or 0) - 90
        end = float(source.get("end_angle") or 0) - 90
        draw.pieslice(box, start=start, end=end, fill=display["color"], outline="white", width=3)
    draw.ellipse(
        (center[0] - inner, center[1] - inner, center[0] + inner, center[1] + inner),
        fill="white",
        outline="#eeeeee",
        width=2,
    )
    outside_index = 0
    for display, source in zip(chart.get("rows") or [], source_series):
        start = float(source.get("start_angle") or 0)
        end = float(source.get("end_angle") or 0)
        middle = math.radians((start + end) / 2 - 90)
        text = str(display.get("display_value") or "")
        if display.get("inside"):
            radius = (outer + inner) / 2
            position = (center[0] + radius * math.cos(middle), center[1] + radius * math.sin(middle))
            draw.text(position, text, fill="white", font=label_font, anchor="mm")
        else:
            side = -1 if outside_index % 2 == 0 else 1
            outside_index += 1
            start_point = (center[0] + (outer + 4) * math.cos(middle), center[1] + (outer + 4) * math.sin(middle))
            elbow = (start_point[0] + side * 32, start_point[1] - 32)
            end_point = (center[0] + side * (outer + 55), elbow[1])
            draw.line((start_point, elbow, end_point), fill="#777777", width=2)
            draw.text((end_point[0] + side * 8, end_point[1]), text, fill="black", font=label_font, anchor="rm" if side < 0 else "lm")
    output = BytesIO()
    image.save(output, format="PNG", dpi=(300, 300), optimize=True)
    output.seek(0)
    return output


def _sector_legend(parent, rows: list[dict[str, Any]], *, font_name: str) -> None:
    if not rows:
        return
    for pair_start in range(0, len(rows), 2):
        paragraph = parent.add_paragraph()
        _format_paragraph(paragraph, after=0, line_spacing=1.0)
        paragraph.paragraph_format.tab_stops.add_tab_stop(Cm(4.25))
        for offset, row in enumerate(rows[pair_start:pair_start + 2]):
            if offset:
                paragraph.add_run("\t")
            marker = paragraph.add_run("■ ")
            _set_run_font(
                marker,
                font_name,
                size=8,
                color=RGBColor.from_string(str(row["color"]).lstrip("#").upper()),
            )
            _set_run_font(paragraph.add_run(str(row.get("sector") or "")), font_name, size=8.5)


def _simple_rule_table(parent, headers: list[str], rows: list[list[str]], *, width: int, font_name: str) -> None:
    table = parent.add_table(rows=1, cols=2)
    _set_table_geometry(table, [int(width * 0.68), width - int(width * 0.68)])
    _set_table_borders(table)
    for index, text in enumerate(headers):
        cell = table.rows[0].cells[index]
        _set_cell_margins(cell, top=60, right=70, bottom=60, left=70)
        _set_cell_borders(cell, color="000000", size=5, edges=("bottom",))
        p = cell.paragraphs[0]
        _clear_paragraph(p)
        _format_paragraph(p, alignment=WD_ALIGN_PARAGRAPH.LEFT if index == 0 else WD_ALIGN_PARAGRAPH.CENTER)
        _set_run_font(p.add_run(text), font_name, size=10, bold=True)
    _repeat_table_header(table.rows[0])
    for values in rows:
        row = table.add_row()
        _prevent_row_split(row)
        for index, text in enumerate(values):
            cell = row.cells[index]
            _set_cell_margins(cell, top=55, right=70, bottom=55, left=70)
            _set_cell_borders(cell, color="000000", size=4, edges=("bottom",))
            p = cell.paragraphs[0]
            _clear_paragraph(p)
            _format_paragraph(p, alignment=WD_ALIGN_PARAGRAPH.LEFT if index == 0 else WD_ALIGN_PARAGRAPH.CENTER)
            _set_run_font(p.add_run(text), font_name, size=10)


def render_docx(report: Report, content: dict, destination: Path) -> None:
    language_mode = str(content.get("language_mode") or report.language_mode or "EN")
    content = localized_document(content, language_mode)
    tokens = _render_tokens(str(content.get("design_token_version") or "3033-v1"))
    page_one = (
        page_one_presentation.resolve_for_render(content, tokens)
        if content.get("template_version") == "3033-v3"
        else None
    )
    if page_one is not None:
        content = page_one["document"]
    sections = content["sections"]
    banner = testing_banner(content)
    if banner and is_chinese(language_mode):
        banner = {**banner, "label": term("testing_label", language_mode)}
    font_name = _font_name(tokens, language_mode)
    deep_hex = str(tokens["color"]["brandDeep"]).lstrip("#").upper()
    blue_hex = str(tokens["color"]["brandTable"]).lstrip("#").upper()
    deep = RGBColor.from_string(deep_hex)
    disclaimer = load_disclaimer()
    document = Document()
    _configure_styles(document, tokens, language_mode)
    review = sections["month_in_review"]
    footnotes = sections.get("footnotes") or {}
    _page_setup(
        document.sections[0], 1, report, language_mode, tokens,
        footnote=str(footnotes.get("historical") or ""),
        footnote_paragraphs=page_one["footnote"]["paragraphs"] if page_one else None,
        footnote_bottom_nudge_pt=page_one["footnote"]["bottom_nudge_pt"] if page_one else 0,
        banner=banner,
    )
    usable_width = _usable_width_twips(document.sections[0])
    title = document.add_heading((content.get("terminology_overrides") or {}).get("product_name") or report.product_name, 0)
    _format_paragraph(title, before=0, after=6, line_spacing=1.0, keep_with_next=True)
    _set_paragraph_border(title, color=deep_hex, size=2, space=7)
    enable_review_layout = content.get("template_version") != "3033-v1"
    if page_one is not None and page_one["review_layout"] is not None:
        _review_layout(
            document,
            page_one["review_layout"],
            width=usable_width,
            font_name=font_name,
            font_size=float(page_one["style_roles"]["defaults"]["review_font_size_pt"]),
            deep=deep,
            style_roles=page_one["style_roles"],
        )
    elif enable_review_layout and review.get("blocks"):
        _review_layout(
            document,
            page_one_presentation.resolve_for_render(
                {**content, "template_version": "3033-v3"},
                _render_tokens("3033-v3"),
            )["review_layout"],
            width=usable_width,
            font_name=font_name,
            font_size=float(tokens["font"]["bodyPt"]),
            deep=deep,
        )
    else:
        _legacy_review(document, content, language_mode, usable_width, font_name, deep)
    benchmark_name = (content.get("terminology_overrides") or {}).get("benchmark_name") or content["benchmark_name"]
    history_heading = document.add_heading(term("historical_performance", language_mode, product=content["product_ticker"], benchmark=benchmark_name), 1)
    _format_paragraph(
        history_heading,
        alignment=WD_ALIGN_PARAGRAPH.CENTER,
        before=max(
            0.0,
            4 + (float(page_one["historical"]["vertical_nudge_pt"]) if page_one else 0),
        ),
        after=4,
        keep_with_next=True,
    )
    history = sections["historical_performance"]["rows"]
    history_font_size = (
        float(page_one["historical"]["table_font_size_pt"])
        if page_one else 10.0
    )
    history_line_height = (
        float(page_one["historical"]["table_line_height"])
        if page_one else 1.2
    )
    history_height_scale = history_font_size * history_line_height / (10.0 * 1.2)
    _table(
        document,
        ["", term("return_1m", language_mode), term("return_3m", language_mode), term("return_6m", language_mode), term("return_ytd", language_mode)],
        [[x["name"], pct(x["return_1m"], language_mode), pct(x["return_3m"], language_mode), pct(x["return_6m"], language_mode), pct(x["return_ytd"], language_mode)] for x in history],
        widths=[int(usable_width * ratio) for ratio in (0.20, 0.20, 0.20, 0.20)] + [usable_width - int(usable_width * 0.80)],
        font_name=font_name,
        blue=blue_hex,
        font_size=history_font_size,
        header_font_size=history_font_size,
        alignments=[WD_ALIGN_PARAGRAPH.LEFT] + [WD_ALIGN_PARAGRAPH.CENTER] * 4,
        header_height_cm=0.78 * history_height_scale,
        row_height_cm=0.62 * history_height_scale,
        line_height=history_line_height if page_one else None,
    )

    page2 = document.add_section(WD_SECTION.NEW_PAGE)
    _page_setup(page2, 2, report, language_mode, tokens, banner=banner)
    news_heading = document.add_heading(term("company_news", language_mode), 1)
    _format_paragraph(news_heading, before=3, after=5, keep_with_next=True)
    for item in sections["company_news"]:
        if not any(str(item.get(field) or "").strip() for field in ("title", "summary", "source_name")):
            continue
        paragraph = document.add_paragraph(style="List Bullet")
        paragraph.paragraph_format.left_indent = Cm(0.55)
        paragraph.paragraph_format.first_line_indent = Cm(-0.3)
        _format_paragraph(paragraph, after=5, line_spacing=1.0)
        run = paragraph.add_run(item["title"])
        _set_run_font(run, font_name, size=10, bold=True, color=RGBColor.from_string(blue_hex))
        source_name = item.get("source_name")
        if source_name:
            _set_run_font(paragraph.add_run("\n" + source_name), font_name, size=9)
        _set_run_font(paragraph.add_run("\n" + item["summary"]), font_name, size=10)

    page3 = document.add_section(WD_SECTION.NEW_PAGE)
    _page_setup(
        page3, 3, report, language_mode, tokens,
        footnote=str(footnotes.get("constituents") or ""), banner=banner,
    )
    heading = document.add_heading(term("constituent_performance", language_mode, product=content["product_ticker"]), 1)
    _format_paragraph(heading, alignment=WD_ALIGN_PARAGRAPH.CENTER, before=8, after=3, keep_with_next=True)
    for run in heading.runs:
        _set_run_font(run, font_name, size=16, bold=True, color=deep)
    rebalance = document.add_paragraph(f"({term('next_rebalancing_date', language_mode, date=rebalancing_date_text(content.get('next_rebalancing_date'), language_mode))})")
    _format_paragraph(rebalance, alignment=WD_ALIGN_PARAGRAPH.CENTER, after=8, line_spacing=1.0, keep_with_next=True)
    for run in rebalance.runs:
        _set_run_font(run, font_name, size=12)
    constituents = sections["constituents"]
    percentages = (0.06, 0.17, 0.12, 0.12, 0.13, 0.13, 0.13)
    constituent_widths = [int(usable_width * value) for value in percentages]
    constituent_widths.append(usable_width - sum(constituent_widths))
    _table(
        document,
        [term("stock_code", language_mode), term("stock_name", language_mode), term("closing_price_hkd", language_mode), term("weighting_pct", language_mode), term("return_1m", language_mode), term("return_3m", language_mode), term("return_6m", language_mode), term("return_ytd", language_mode)],
        [[str(x.get("security_code", "")), str(x.get("display_name") or ""), price(x.get("close_price"), language_mode), pct(x.get("weight"), language_mode), pct(x.get("return_1m"), language_mode), pct(x.get("return_3m"), language_mode), pct(x.get("return_6m"), language_mode), pct(x.get("return_ytd"), language_mode)] for x in constituents],
        widths=constituent_widths,
        font_name=font_name,
        blue=blue_hex,
        font_size=9.3,
        header_font_size=9.3,
        blue_first=True,
        alignments=[WD_ALIGN_PARAGRAPH.CENTER] * 8,
        header_height_cm=1.35,
        row_height_cm=0.53,
    )

    page4 = document.add_section(WD_SECTION.NEW_PAGE)
    _page_setup(
        page4, 4, report, language_mode, tokens,
        footnote=str(footnotes.get("analytics") or ""), banner=banner,
    )
    analytics = sections["analytics"]
    outer = document.add_table(rows=1, cols=2)
    outer_widths = [int(usable_width * 0.49), usable_width - int(usable_width * 0.49)]
    _set_table_geometry(outer, outer_widths)
    _set_table_borders(outer)
    left, right = outer.rows[0].cells
    for cell in (left, right):
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
        _set_cell_borders(cell)
    _set_cell_margins(left, right=170)
    _set_cell_margins(right, left=170)
    _add_blue_title(left, term("top10", language_mode, product=content["product_ticker"]), "(%)", width=outer_widths[0] - 170, font_name=font_name, blue=blue_hex)
    _table(
        left,
        None,
        [[x.get("display_issuer", ""), pct(x["weight"], language_mode)] for x in analytics["top10"]],
        widths=[int((outer_widths[0] - 170) * 0.78), (outer_widths[0] - 170) - int((outer_widths[0] - 170) * 0.78)],
        font_name=font_name,
        blue=blue_hex,
        font_size=11,
        alignments=[WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.RIGHT],
        row_height_cm=0.62,
    )
    _remove_initial_empty_paragraph(left)
    _add_blue_title(right, term("sector_breakdown", language_mode, product=content["product_ticker"]), None, width=outer_widths[1] - 170, font_name=font_name, blue=blue_hex)
    # The Word contract permits charts as high-resolution images; the chart data and labels are
    # still sourced from the same immutable snapshot used by HTML/PDF.
    source_chart = analytics.get("sector_chart") or {}
    sector_series = source_chart.get("series") or []
    industry_overrides = content.get("_industry_overrides") or {}
    chart = sector_chart(source_chart, tokens["chart"]["sectorDonut"], language_mode, content["product_ticker"], industry_overrides)
    chart_paragraph = right.add_paragraph()
    _format_paragraph(chart_paragraph, alignment=WD_ALIGN_PARAGRAPH.CENTER)
    if chart.get("has_data"):
        picture = chart_paragraph.add_run().add_picture(_sector_chart_image(chart, sector_series, font_name), width=Cm(7.2))
        picture._inline.docPr.set("title", term("sector_breakdown", language_mode, product=content["product_ticker"]))
        picture._inline.docPr.set("descr", str(chart.get("alt_text") or ""))
        _sector_legend(right, chart["rows"], font_name=font_name)
    _remove_initial_empty_paragraph(right)

    performers = document.add_table(rows=1, cols=2)
    _set_table_geometry(performers, outer_widths)
    _set_table_borders(performers)
    for index, (title_text, rows) in enumerate((
        (term("top_performers", language_mode, month=content["month_name"]), [[x.get("display_issuer", ""), pct(x["return"], language_mode)] for x in analytics["top"]]),
        (term("bottom_performers", language_mode, month=content["month_name"]), [[x.get("display_issuer", ""), pct(x["return"], language_mode)] for x in analytics["bottom"]]),
    )):
        cell = performers.rows[0].cells[index]
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
        _set_cell_borders(cell)
        _set_cell_margins(cell, top=230, right=170 if index == 0 else 0, left=170 if index == 1 else 0)
        heading = cell.paragraphs[0]
        _clear_paragraph(heading)
        _format_paragraph(heading, after=5, keep_with_next=True)
        _set_run_font(heading.add_run(title_text), font_name, size=14, bold=True, color=deep)
        _simple_rule_table(
            cell,
            [term("issuer", language_mode), f"{content['month_name']} {term('return', language_mode)}"],
            rows,
            width=outer_widths[index] - 170,
            font_name=font_name,
        )

    portfolio_heading = document.add_heading(term("portfolio_analysis", language_mode, product=content["product_ticker"]), 1)
    _format_paragraph(portfolio_heading, before=12, after=5, keep_with_next=True)
    portfolio_rows = normalize_portfolio_rows(analytics.get("portfolio"), "HKD")
    if is_chinese(language_mode):
        for row in portfolio_rows:
            row["label"] = localized_portfolio_label(
                row.get("metric_code"), row.get("label", ""), language_mode
            )
            if row.get("display_value") == "N/A":
                row["display_value"] = term("no_data", language_mode)
            else:
                row["display_value"] = localized_portfolio_value(row.get("display_value"), language_mode)
    portfolio_table = document.add_table(rows=0, cols=2)
    portfolio_widths = [int(usable_width * 0.63), usable_width - int(usable_width * 0.63)]
    _set_table_geometry(portfolio_table, portfolio_widths)
    _set_table_borders(portfolio_table)
    for values in [[x["label"], x["display_value"]] for x in portfolio_rows]:
        row = portfolio_table.add_row()
        _prevent_row_split(row)
        row.height = Cm(0.72)
        row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
        for index, text in enumerate(values):
            cell = row.cells[index]
            _set_cell_margins(cell, top=70, right=80, bottom=70, left=80)
            _set_cell_borders(cell, color="000000", size=4, edges=("bottom",))
            p = cell.paragraphs[0]
            _clear_paragraph(p)
            _format_paragraph(p, alignment=WD_ALIGN_PARAGRAPH.LEFT if index == 0 else WD_ALIGN_PARAGRAPH.CENTER)
            _set_run_font(p.add_run(text), font_name, size=10, bold=index == 0)

    # The legal copy is an immutable render resource rather than report content. It is appended
    # at generation time so finalized and archived documents created before this page existed get
    # the same current approved disclaimer without mutating their stored document checksum.
    page5 = document.add_section(WD_SECTION.NEW_PAGE)
    _page_setup(page5, 5, report, "EN", tokens, banner=banner)
    disclaimer_font = _font_name(tokens, "EN")
    disclaimer_heading = document.add_heading(disclaimer.title, 1)
    _format_paragraph(
        disclaimer_heading,
        before=3,
        after=9,
        line_spacing=1.0,
        keep_with_next=True,
    )
    for run in disclaimer_heading.runs:
        _set_run_font(run, disclaimer_font, size=14, bold=True, color=deep)
    for text in disclaimer.paragraphs:
        paragraph = document.add_paragraph()
        _format_paragraph(paragraph, after=5, line_spacing=1.08)
        paragraph.paragraph_format.keep_together = True
        _set_run_font(paragraph.add_run(text), disclaimer_font, size=11)
    issuer = document.add_paragraph()
    _format_paragraph(issuer, before=8, after=0, line_spacing=1.08)
    issuer.paragraph_format.keep_together = True
    _set_run_font(issuer.add_run(disclaimer.issuer), disclaimer_font, size=11)
    document.save(destination)


@dataclass
class GeneratedExport:
    directory: TemporaryDirectory
    path: Path
    filename: str
    mime_type: str
    size_bytes: int
    checksum: str
    content_manifest: dict
    disclaimer_version: str
    disclaimer_checksum: str

    def cleanup(self) -> None:
        self.directory.cleanup()


def assert_page_one_layout_fits(report: Report, content: dict[str, Any]) -> None:
    """Measure page one in Chromium and reject content entering either safe area.

    This preflight is shared by finalization and every export format. Draft preview deliberately
    skips the exception so the browser can mark the offending element and let an editor fix it.
    """

    from playwright.sync_api import sync_playwright

    html = render_html(report, content, layout_mode="paged")
    with TemporaryDirectory(prefix="commentary-layout-check-") as temp:
        source = Path(temp) / "report.html"
        source.write_text(html, encoding="utf-8")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(source.as_uri(), wait_until="networkidle")
                page.evaluate("""async () => {
                    await document.fonts.ready;
                    await Promise.all(Array.from(document.images).map((image) =>
                        image.complete ? image.decode().catch(() => undefined) : new Promise((resolve) => {
                            image.addEventListener('load', resolve, { once: true });
                            image.addEventListener('error', resolve, { once: true });
                        })
                    ));
                }""")
                findings = page.evaluate("""() => {
                    const tolerance = 0.5;
                    const reportPage = document.querySelector('.report-page[data-page="1"]');
                    const footer = reportPage?.querySelector('.page-footer');
                    const footnote = reportPage?.querySelector('.footnote');
                    if (!reportPage || !footer) return [];
                    const pageBody = reportPage.querySelector('.page-body');
                    const pageRect = reportPage.getBoundingClientRect();
                    const bodyRect = pageBody?.getBoundingClientRect() ?? pageRect;
                    const footerTop = footer.getBoundingClientRect().top;
                    const footnoteTop = footnote?.getBoundingClientRect().top ?? footerTop;
                    const horizontalOverflow = (node) =>
                        [node, ...node.querySelectorAll('*')].some((candidate) =>
                            candidate.scrollWidth > candidate.clientWidth + tolerance
                        );
                    const layoutNodes = Array.from(reportPage.querySelectorAll('[data-layout-id]'));
                    if (!layoutNodes.length) {
                        if (!pageBody) return [];
                        const bodyBounds = pageBody.getBoundingClientRect();
                        const bottom = bodyBounds.bottom;
                        const safeBottom = Math.min(footnoteTop, footerTop);
                        const vertical = bottom > safeBottom + tolerance;
                        const horizontal = bodyBounds.left < pageRect.left - tolerance
                            || bodyBounds.right > pageRect.right + tolerance
                            || horizontalOverflow(pageBody);
                        return vertical || horizontal
                            ? [{ layout_id: 'page_one', axis: vertical && horizontal ? 'both' : vertical ? 'vertical' : 'horizontal',
                                bottom: Math.round(bottom * 100) / 100,
                                safe_bottom: Math.round(safeBottom * 100) / 100,
                                left: Math.round(bodyBounds.left * 100) / 100,
                                right: Math.round(bodyBounds.right * 100) / 100,
                                safe_left: Math.round(pageRect.left * 100) / 100,
                                safe_right: Math.round(pageRect.right * 100) / 100 }]
                            : [];
                    }
                    const boundsFindings = layoutNodes.flatMap((node) => {
                        const rect = node.getBoundingClientRect();
                        const safeBottom = node === footnote ? footerTop : Math.min(footnoteTop, footerTop);
                        const horizontalBounds = node.closest('.page-body') ? bodyRect : pageRect;
                        const vertical = rect.bottom > safeBottom + tolerance;
                        const horizontal = rect.left < horizontalBounds.left - tolerance
                            || rect.right > horizontalBounds.right + tolerance
                            || horizontalOverflow(node);
                        return vertical || horizontal
                            ? [{
                                layout_id: node.dataset.layoutId,
                                axis: vertical && horizontal ? 'both' : vertical ? 'vertical' : 'horizontal',
                                bottom: Math.round(rect.bottom * 100) / 100,
                                safe_bottom: Math.round(safeBottom * 100) / 100,
                                left: Math.round(rect.left * 100) / 100,
                                right: Math.round(rect.right * 100) / 100,
                                safe_left: Math.round(horizontalBounds.left * 100) / 100,
                                safe_right: Math.round(horizontalBounds.right * 100) / 100,
                            }]
                            : [];
                    });
                    const overlapFindings = [];
                    for (let leftIndex = 0; leftIndex < layoutNodes.length; leftIndex += 1) {
                        const leftNode = layoutNodes[leftIndex];
                        const leftRect = leftNode.getBoundingClientRect();
                        for (let rightIndex = leftIndex + 1; rightIndex < layoutNodes.length; rightIndex += 1) {
                            const rightNode = layoutNodes[rightIndex];
                            if (leftNode.contains(rightNode) || rightNode.contains(leftNode)) continue;
                            const rightRect = rightNode.getBoundingClientRect();
                            const overlapWidth = Math.min(leftRect.right, rightRect.right)
                                - Math.max(leftRect.left, rightRect.left);
                            const overlapHeight = Math.min(leftRect.bottom, rightRect.bottom)
                                - Math.max(leftRect.top, rightRect.top);
                            if (overlapWidth <= tolerance || overlapHeight <= tolerance) continue;
                            overlapFindings.push({
                                layout_id: leftNode.dataset.layoutId,
                                axis: 'overlap',
                                overlaps_with: rightNode.dataset.layoutId,
                                overlap_width: Math.round(overlapWidth * 100) / 100,
                                overlap_height: Math.round(overlapHeight * 100) / 100,
                            });
                        }
                    }
                    return [...boundsFindings, ...overlapFindings];
                }""")
            finally:
                browser.close()
    page_one_presentation.assert_no_overflow(findings)


def generate_export(report: Report, document: ReportDocument, format_name: str) -> GeneratedExport:
    """Render one fixed document into isolated scratch space; caller owns cleanup after delivery."""
    if format_name not in MIME:
        raise ValueError(f"Unsupported format: {format_name}")
    directory = TemporaryDirectory(prefix="commentary-export-")
    destination = Path(directory.name) / f"output.{format_name}"
    lane_prefix = "TESTING-" if document.content.get("lane") == "TESTING" else ""
    language = str(document.content.get("language_mode") or report.language_mode)
    language_tag = language.replace("_", "-")
    product = re.sub(r"[^A-Za-z0-9._-]", "_", report.product_code)
    filename = f"{lane_prefix}{product}_{report.report_date.isoformat()}_{language_tag}_v{document.version}.{format_name}"
    try:
        assert_page_one_layout_fits(report, document.content)
        _render_file(report, document, format_name, destination)
        disclaimer_fields = disclaimer_audit_fields()
        content_manifest = {
            key: value
            for key, value in render_content_manifest(document.content).items()
            if key != "checksum"
        }
        content_manifest.update(disclaimer_fields)
        content_manifest["checksum"] = structured_checksum(content_manifest)
        return GeneratedExport(
            directory=directory,
            path=destination,
            filename=filename,
            mime_type=MIME[format_name],
            size_bytes=destination.stat().st_size,
            checksum=sha256(destination),
            content_manifest=content_manifest,
            **disclaimer_fields,
        )
    except BaseException:
        directory.cleanup()
        raise


def _render_file(report: Report, document: ReportDocument, format_name: str, destination: Path) -> None:
    if format_name == "html":
        html = render_html(report, document.content, layout_mode="continuous")
        destination.write_text(html, encoding="utf-8")
    elif format_name == "docx":
        render_docx(report, document.content, destination)
    else:
        from playwright.sync_api import sync_playwright

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
