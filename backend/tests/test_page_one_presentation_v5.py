from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

from app.domain.document import initial_document, validate_document_content
from app.domain.page_one_presentation import PageOnePresentationError, page_one_presentation
from app.rendering.artifacts import render_docx
from app.rendering.html import render_html


def _document(version: str = "3033-v5") -> dict:
    content = initial_document(
        "report-v5",
        date(2026, 6, 30),
        version,
        version,
        "3033.HK",
        "Hang Seng TECH Index",
        "EN",
    )
    content["sections"]["footnotes"]["historical"] = "Source¹: CSOP.\n\nPast performance² is not indicative."
    _element(content, "footnote:historical")["content_html"] = (
        "<p>Source¹: CSOP.</p><p>Past performance² is not indicative.</p>"
    )
    return content


def _element(content: dict, element_id: str) -> dict:
    return next(
        item
        for item in content["presentation"]["page_one"]["elements"]
        if item["id"] == element_id
    )


def _report() -> SimpleNamespace:
    return SimpleNamespace(
        report_date=date(2026, 6, 30),
        language_mode="EN",
        product_name="CSOP Hang Seng TECH Index ETF",
        product_code="3033",
        benchmark_code="HSTECH",
    )


def test_v5_defaults_put_locked_eight_point_footnote_in_safe_footer_band():
    content = validate_document_content(_document())
    historical = _element(content, "historical_performance")
    footnote = _element(content, "footnote:historical")

    assert content["presentation"]["schema_version"] == 3
    assert (footnote["page"], footnote["x"], footnote["w"]) == (1, 0, 12)
    assert footnote["page"] == historical["page"]
    assert footnote["footer_bottom_mm"] == 20
    assert not {"row", "row_span", "gap_pt"} & footnote.keys()
    assert footnote["body_style"] == {
        "font_family": "Calibri",
        "font_size_pt": 8,
        "color": "#000000",
        "bold": False,
        "italic": False,
        "underline": False,
        "line_height": 1.2,
        "space_before_pt": 0,
        "space_after_pt": 0,
        "text_align": "left",
        "indent_level": 0,
    }


@pytest.mark.parametrize(
    ("language_mode", "text"),
    [
        ("EN", "Source¹: CSOP."),
        ("ZH_HANS", "资料来源¹：南方东英。"),
        ("ZH_HANT", "資料來源¹：南方東英。"),
    ],
)
def test_v5_preserves_multilingual_footnote_text_and_unicode_markers(
    language_mode: str,
    text: str,
):
    content = initial_document(
        f"report-{language_mode}",
        date(2026, 6, 30),
        "3033-v5",
        "3033-v5",
        "3033.HK",
        "Hang Seng TECH Index",
        language_mode,
    )
    content["sections"]["footnotes"]["historical"] = text
    _element(content, "footnote:historical")["content_html"] = f"<p>{text}</p>"

    canonical = page_one_presentation.canonicalize_document(content)

    assert canonical["sections"]["footnotes"]["historical"] == text
    assert text in render_html(_report(), canonical, layout_mode="paged")


def test_v5_locks_inline_style_but_keeps_allowed_paragraph_and_position_controls():
    content = _document()
    footnote = _element(content, "footnote:historical")
    footnote.update(x=2, w=8, footer_bottom_mm=31)
    footnote["content_html"] = (
        '<p data-line-height="2"><span data-font-size-pt="30"><strong>Source¹</strong>'
        "<br>Line 2</span></p>"
    )
    footnote["body_style"].update(
        font_family="Comic Sans MS",
        font_size_pt=30,
        color="#FF0000",
        bold=True,
        italic=True,
        underline=True,
        line_height=1.4,
        space_before_pt=2,
        space_after_pt=3,
        text_align="right",
    )

    canonical = page_one_presentation.canonicalize_document(content)
    saved = _element(canonical, "footnote:historical")

    assert (saved["x"], saved["w"], saved["footer_bottom_mm"]) == (2, 8, 31)
    assert saved["content_html"] == "<p>Source¹<br>Line 2</p>"
    assert saved["body_style"]["font_size_pt"] == 8
    assert saved["body_style"]["font_family"] == "Calibri"
    assert saved["body_style"]["color"] == "#000000"
    assert saved["body_style"]["bold"] is False
    assert saved["body_style"]["line_height"] == 1.4
    assert saved["body_style"]["space_before_pt"] == 2
    assert saved["body_style"]["space_after_pt"] == 3
    assert saved["body_style"]["text_align"] == "right"
    assert canonical["sections"]["footnotes"]["historical"] == "Source¹\nLine 2"


@pytest.mark.parametrize("footer_bottom_mm", [15.99, 36.01])
def test_v5_rejects_footer_position_outside_safe_band(footer_bottom_mm: float):
    content = _document()
    _element(content, "footnote:historical")["footer_bottom_mm"] = footer_bottom_mm

    with pytest.raises(PageOnePresentationError) as caught:
        page_one_presentation.canonicalize_document(content)

    assert caught.value.field.endswith("footer_bottom_mm")


def test_v4_draft_upgrade_preserves_page_and_columns_but_resets_vertical_position():
    v4 = _document("3033-v4")
    historical = _element(v4, "historical_performance")
    footnote = _element(v4, "footnote:historical")
    historical.update(page=2, x=3, w=7)
    footnote.update(page=2, x=3, w=7, gap_pt=19)
    footnote["content_html"] = "<p>Kept¹</p>"
    v4["presentation"]["page_one"]["review_page_count"] = 2

    upgraded = page_one_presentation.upgrade_document_to_v5(v4)
    upgraded_footnote = _element(upgraded, "footnote:historical")

    assert upgraded["template_version"] == "3033-v5"
    assert upgraded["presentation"]["schema_version"] == 3
    assert (upgraded_footnote["page"], upgraded_footnote["x"], upgraded_footnote["w"]) == (2, 3, 7)
    assert upgraded_footnote["footer_bottom_mm"] == 20
    assert upgraded_footnote["content_html"] == "<p>Kept¹</p>"
    assert "gap_pt" not in upgraded_footnote


def test_v5_paged_and_continuous_html_share_footer_style_without_body_footnote():
    content = _document()
    paged = render_html(_report(), content, layout_mode="paged")
    continuous = render_html(_report(), content, layout_mode="continuous")

    for markup in (paged, continuous):
        assert markup.count('data-layout-id="footnote:historical"') == 1
        assert 'class="review-footnote-layer"' in markup
        assert "font-size:8.0pt" in markup
        assert "Source¹" in markup


def test_v5_keeps_existing_review_typography_controls_while_locking_footnote_style():
    content = _document()
    summary = _element(content, "review:summary")
    summary["body_style"]["font_size_pt"] = 11
    summary["title_style"]["space_after_pt"] = 6

    paged = render_html(_report(), content, layout_mode="paged")

    assert "font-size:11.0pt" in paged
    assert "margin-bottom:6.0pt" in paged
    assert "font-size:8.0pt" in paged


def test_v5_historical_footnote_follows_historical_to_the_selected_review_page():
    content = _document()
    content["presentation"]["page_one"]["review_page_count"] = 2
    _element(content, "historical_performance")["page"] = 2
    _element(content, "footnote:historical")["page"] = 2

    paged = render_html(_report(), content, layout_mode="paged")
    page_one_start = paged.index('data-page="1"')
    page_two_start = paged.index('data-page="2"')
    page_three_start = paged.index('data-page="3"')
    footnote_start = paged.index('data-layout-id="footnote:historical"')

    assert page_one_start < page_two_start < footnote_start < page_three_start
    assert paged.count('data-layout-id="footnote:historical"') == 1


def test_v5_docx_writes_historical_footnote_only_to_footer_xml(tmp_path):
    content = _document()
    _element(content, "footnote:historical")["body_style"].update(
        line_height=1.4,
        space_before_pt=2,
        space_after_pt=3,
        text_align="right",
    )
    destination = tmp_path / "v5-review-footer.docx"

    render_docx(_report(), content, destination)

    with ZipFile(destination) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
        footer_xml = "\n".join(
            archive.read(name).decode("utf-8")
            for name in archive.namelist()
            if name.startswith("word/footer") and name.endswith(".xml")
        )
    assert "Source¹" not in document_xml
    assert "Source¹" in footer_xml
    assert "Past performance²" in footer_xml

    exported = Document(destination)
    paragraph = next(
        paragraph
        for section in exported.sections
        for paragraph in section.footer.paragraphs
        if "Source¹" in paragraph.text
    )
    assert paragraph.alignment == WD_ALIGN_PARAGRAPH.RIGHT
    assert paragraph.paragraph_format.space_before.pt == 2
    assert paragraph.paragraph_format.space_after.pt >= 3
    assert paragraph.paragraph_format.line_spacing.pt == pytest.approx(11.2)


def test_v5_docx_footer_follows_historical_to_its_review_section(tmp_path):
    content = _document()
    content["presentation"]["page_one"]["review_page_count"] = 2
    _element(content, "historical_performance")["page"] = 2
    _element(content, "footnote:historical")["page"] = 2
    destination = tmp_path / "v5-review-page-two.docx"

    render_docx(_report(), content, destination)

    exported = Document(destination)
    first_footer = "\n".join(paragraph.text for paragraph in exported.sections[0].footer.paragraphs)
    second_footer = "\n".join(paragraph.text for paragraph in exported.sections[1].footer.paragraphs)
    assert "Source¹" not in first_footer
    assert "Source¹" in second_footer


def test_finalized_v4_content_can_still_render_with_legacy_body_footnote():
    v4 = deepcopy(_document("3033-v4"))
    markup = render_html(_report(), v4, layout_mode="paged")

    assert 'class="review-footnote-layer"' not in markup
    assert markup.count('data-layout-id="footnote:historical"') == 1
    assert "font-size:9.0pt" in markup
