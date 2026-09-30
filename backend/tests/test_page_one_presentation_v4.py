from copy import deepcopy
from datetime import date
from types import SimpleNamespace

import pytest

from app.domain.document import initial_document, validate_document_content
from app.domain.models import ReportStatus
from app.domain.page_one_presentation import PageOnePresentationError, page_one_presentation
from app.domain.service.documents import canonicalize_document_content, document_content_for_read


def _v4_document() -> dict:
    return initial_document(
        "report-v4",
        date(2026, 8, 31),
        "3033-v4",
        "3033-v4",
        "3033.HK",
        "Hang Seng TECH Index",
        "EN",
    )


def _element(content: dict, element_id: str) -> dict:
    return next(
        item
        for item in content["presentation"]["page_one"]["elements"]
        if item["id"] == element_id
    )


def test_v4_defaults_have_numeric_styles_and_aligned_history_group():
    content = validate_document_content(_v4_document())
    page_one = content["presentation"]["page_one"]
    history = _element(content, "historical_performance")
    footnote = _element(content, "footnote:historical")

    assert content["presentation"]["schema_version"] == 2
    assert page_one["review_page_count"] == 1
    assert (history["page"], history["x"], history["w"]) == (
        footnote["page"], footnote["x"], footnote["w"],
    )
    assert history["title_style"] == {
        "font_family": "Calibri",
        "font_size_pt": 12,
        "color": "#22327F",
        "bold": True,
        "italic": False,
        "underline": False,
        "line_height": 1.2,
        "space_before_pt": 0,
        "space_after_pt": 4,
        "text_align": "center",
        "indent_level": 0,
    }
    assert history["header_style"]["font_size_pt"] == 11
    assert history["header_style"]["color"] == "#FFFFFF"
    assert history["header_style"]["text_align"] == "center"
    assert history["body_style"]["font_size_pt"] == 10
    assert history["body_style"]["text_align"] == "center"
    assert history["cell_padding_y_pt"] == 2
    assert footnote["gap_pt"] == 6
    assert footnote["body_style"]["font_size_pt"] == 9

    review = _element(content, "review:summary")
    assert review["title_style"]["font_size_pt"] == 14.04
    assert review["title_style"]["font_family"] == "Calibri"
    assert review["title_style"]["color"] == "#22327F"
    assert review["title_style"]["bold"] is True


def test_v4_keeps_title_brand_style_locked_but_persists_title_content_spacing():
    content = _v4_document()
    overridden_style = {
        "font_family": "Comic Sans MS",
        "font_size_pt": 5,
        "color": "#FF0000",
        "bold": False,
        "italic": True,
        "underline": True,
        "line_height": 3,
        "space_before_pt": 72,
        "space_after_pt": 7.5,
        "text_align": "right",
        "indent_level": 2,
    }
    titled_ids = (
        "review:summary", "review:drivers", "review:monitor", "review:outlook",
        "historical_performance",
    )
    for element_id in titled_ids:
        _element(content, element_id)["title_style"] = deepcopy(overridden_style)

    canonical = validate_document_content(content)

    review_titles = [_element(canonical, element_id)["title_style"] for element_id in titled_ids[:-1]]
    history_title = _element(canonical, "historical_performance")["title_style"]
    for review_title in review_titles:
        assert review_title == {
            "font_family": "Calibri", "font_size_pt": 14.04, "color": "#22327F",
            "bold": True, "italic": False, "underline": False, "line_height": 1.2,
            "space_before_pt": 0, "space_after_pt": 7.5, "text_align": "left",
            "indent_level": 2,
        }
    assert history_title == {
        "font_family": "Calibri", "font_size_pt": 12, "color": "#22327F",
        "bold": True, "italic": False, "underline": False, "line_height": 1.2,
        "space_before_pt": 0, "space_after_pt": 7.5, "text_align": "center",
        "indent_level": 2,
    }


def test_v4_history_group_can_move_to_last_review_page_but_not_past_it():
    content = _v4_document()
    content["presentation"]["page_one"]["review_page_count"] = 96
    _element(content, "historical_performance")["page"] = 96
    _element(content, "footnote:historical")["page"] = 96
    canonical = validate_document_content(content)
    assert _element(canonical, "historical_performance")["page"] == 96

    overflow = deepcopy(canonical)
    overflow["presentation"]["page_one"]["review_page_count"] = 97
    with pytest.raises(PageOnePresentationError) as caught:
        validate_document_content(overflow)
    assert caught.value.field == "presentation.page_one.review_page_count"


def test_v4_rejects_misaligned_history_group_and_out_of_range_typography():
    content = _v4_document()
    _element(content, "footnote:historical")["w"] = 11
    with pytest.raises(PageOnePresentationError, match="share x and w"):
        validate_document_content(content)

    content = _v4_document()
    _element(content, "review:summary")["body_style"]["font_size_pt"] = 36.1
    with pytest.raises(PageOnePresentationError) as caught:
        validate_document_content(content)
    assert caught.value.field.endswith("body_style.font_size_pt")

    content = _v4_document()
    _element(content, "review:summary")["title_style"]["space_after_pt"] = 72.1
    with pytest.raises(PageOnePresentationError) as caught:
        validate_document_content(content)
    assert caught.value.field.endswith("title_style.space_after_pt")


def test_v4_rich_text_is_sanitized_and_footnote_plain_text_is_derived():
    content = _v4_document()
    summary = next(
        block
        for block in content["sections"]["month_in_review"]["blocks"]
        if block["block_id"] == "summary"
    )
    summary["content"] = (
        '<p data-line-height="1.35" data-space-after-pt="4.5" data-text-align="justify">'
        '<span data-font-family="Noto Sans CJK TC" data-font-size-pt="12.5" '
        'data-color="#123abc"><u>Approved</u></span></p>'
    )
    footnote = _element(content, "footnote:historical")
    footnote["content_html"] = "<p>First.</p><p><strong>Second.</strong></p>"

    canonical = validate_document_content(content)
    assert canonical["sections"]["footnotes"]["historical"] == "First.\n\nSecond."
    summary_content = canonical["sections"]["month_in_review"]["blocks"][0]["content"]
    assert 'data-font-size-pt="12.5"' in summary_content
    resolved = page_one_presentation.resolve_for_render(canonical, {})
    assert "font-size:12.5pt" in resolved["review_blocks"][0]["rendered_content_html"]
    assert "<strong>Second.</strong>" in resolved["footnote"]["rendered_content_html"]


def test_v4_rich_text_preserves_numbered_lists_and_controlled_paragraph_indents():
    content = _v4_document()
    summary = next(
        block
        for block in content["sections"]["month_in_review"]["blocks"]
        if block["block_id"] == "summary"
    )
    summary["content"] = (
        '<ol><li data-indent-level="2"><p><strong>Key driver</strong><br>'
        'Wrapped supporting copy.</p></li></ol>'
        '<p data-indent-level="1">Indented paragraph.</p>'
    )

    canonical = validate_document_content(content)
    summary_content = canonical["sections"]["month_in_review"]["blocks"][0]["content"]
    assert '<ol><li data-indent-level="2">' in summary_content
    assert '<p data-indent-level="1">Indented paragraph.</p>' in summary_content

    rendered = page_one_presentation.resolve_for_render(canonical, {})[
        "review_blocks"
    ][0]["rendered_content_html"]
    assert '<ol><li data-indent-level="2" style="margin-left:4em">' in rendered
    assert '<p data-indent-level="1" style="margin-left:2em">' in rendered

    summary["content"] = '<p data-indent-level="7">Too far.</p>'
    with pytest.raises(PageOnePresentationError, match="data-indent-level"):
        validate_document_content(content)


def test_v4_render_html_uses_explicit_pdf_font_fallback_without_losing_requested_name():
    content = _v4_document()
    summary = next(
        block
        for block in content["sections"]["month_in_review"]["blocks"]
        if block["block_id"] == "summary"
    )
    summary["content"] = '<p><span data-font-family="Unbundled Font">Text</span></p>'

    resolved = page_one_presentation.resolve_for_render(
        validate_document_content(content), {}
    )
    rendered = resolved["review_blocks"][0]["rendered_content_html"]

    assert 'data-requested-font="Unbundled Font"' in rendered
    assert "font-family:Carlito" in rendered


def test_editable_v3_is_adapted_without_mutation_but_finalized_v3_is_unchanged():
    content = initial_document(
        "report-v3", date(2026, 8, 31), "3033-v3", "3033-v3",
        "3033.HK", "Hang Seng TECH Index", "EN",
    )
    document = SimpleNamespace(content=content, template_version="3033-v3")
    editable = SimpleNamespace(status=ReportStatus.EDITING)
    finalized = SimpleNamespace(status=ReportStatus.FINALIZED)

    adapted = document_content_for_read(editable, document)
    locked = document_content_for_read(finalized, document)

    assert adapted["template_version"] == "3033-v3"
    assert adapted["presentation"]["schema_version"] == 2
    assert locked["presentation"]["schema_version"] == 1
    assert content["presentation"]["schema_version"] == 1


def test_v3_upgrade_preserves_each_footnote_paragraph_style_and_nudge_through_save():
    current = initial_document(
        "report-v3", date(2026, 8, 31), "3033-v3", "3033-v3",
        "3033.HK", "Hang Seng TECH Index", "EN",
    )
    historical_text = "First <source>.\ncontinuation\n\nSecond & final."
    current["sections"]["footnotes"]["historical"] = historical_text
    _element(current, "historical_performance")["vertical_nudge_steps"] = 3
    legacy_footnote = _element(current, "footnote:historical")
    legacy_footnote["bottom_nudge_steps"] = 2
    legacy_footnote["paragraph_styles"] = [
        {
            "paragraph_index": 0,
            "font_size_role": "footnote-8",
            "line_height_role": "1.0",
            "text_align": "left",
        },
        {
            "paragraph_index": 1,
            "font_size_role": "footnote-10",
            "line_height_role": "1.4",
            "text_align": "justify",
        },
    ]
    original = deepcopy(current)
    document = SimpleNamespace(content=current, template_version="3033-v3")

    adapted = document_content_for_read(
        SimpleNamespace(status=ReportStatus.EDITING), document,
    )
    locked = document_content_for_read(
        SimpleNamespace(status=ReportStatus.FINALIZED), document,
    )

    expected_html = (
        '<p data-line-height="1" data-text-align="left">'
        '<span data-font-size-pt="8">First &lt;source&gt;.<br>continuation</span></p>'
        '<p data-line-height="1.4" data-text-align="justify">'
        '<span data-font-size-pt="10">Second &amp; final.</span></p>'
    )
    assert _element(adapted, "historical_performance")["offset_y_pt"] == 15
    assert _element(adapted, "footnote:historical")["gap_pt"] == 8
    assert _element(adapted, "footnote:historical")["content_html"] == expected_html
    assert adapted["sections"]["footnotes"]["historical"] == historical_text
    assert locked == original
    assert current == original

    resolved = page_one_presentation.resolve_for_render(adapted, {})
    assert 'style="line-height:1;text-align:left"' in resolved["footnote"]["rendered_content_html"]
    assert 'style="font-size:8pt"' in resolved["footnote"]["rendered_content_html"]
    assert 'style="line-height:1.4;text-align:justify"' in resolved["footnote"]["rendered_content_html"]
    assert 'style="font-size:10pt"' in resolved["footnote"]["rendered_content_html"]

    report = SimpleNamespace(
        id="report-v3",
        report_date=date(2026, 8, 31),
        language_mode="EN",
        template_version="3033-v3",
        active_snapshot_id=None,
        lane="PRODUCTION",
    )
    product = SimpleNamespace(
        ticker="3033.HK",
        benchmark_instrument_name="Hang Seng TECH Index",
        benchmark_instrument_code="HSTECH",
        design_token_version="3033-v3",
    )
    saved = canonicalize_document_content(
        report, product, adapted, current_content=current,
    )

    assert saved["template_version"] == "3033-v4"
    assert _element(saved, "historical_performance")["offset_y_pt"] == 15
    assert _element(saved, "footnote:historical")["gap_pt"] == 8
    assert _element(saved, "footnote:historical")["content_html"] == expected_html
    assert saved["sections"]["footnotes"]["historical"] == historical_text


@pytest.mark.parametrize(
    ("bottom_nudge_steps", "expected_gap_pt"),
    [(-3, 28), (0, 16), (4, 0)],
)
def test_v3_bottom_nudge_migration_is_distinct_across_the_full_legacy_range(
    bottom_nudge_steps: int,
    expected_gap_pt: float,
):
    content = initial_document(
        "report-v3", date(2026, 8, 31), "3033-v3", "3033-v3",
        "3033.HK", "Hang Seng TECH Index", "EN",
    )
    _element(content, "footnote:historical")["bottom_nudge_steps"] = bottom_nudge_steps

    upgraded = page_one_presentation.upgrade_document_to_v4(content)

    assert _element(upgraded, "footnote:historical")["gap_pt"] == expected_gap_pt


def test_editable_v1_is_adapted_to_v4_shape_but_finalized_v1_is_unchanged():
    content = initial_document(
        "report-v1", date(2026, 8, 31), "3033-v1", "3033-v1",
        "3033.HK", "Hang Seng TECH Index", "EN",
    )
    assert "presentation" not in content
    document = SimpleNamespace(content=content, template_version="3033-v1")

    adapted = document_content_for_read(SimpleNamespace(status=ReportStatus.EDITING), document)
    locked = document_content_for_read(SimpleNamespace(status=ReportStatus.FINALIZED), document)

    assert adapted["template_version"] == "3033-v4"
    assert adapted["presentation"]["schema_version"] == 2
    assert _element(adapted, "review:summary")["title_style"]["font_size_pt"] == 14.04
    assert _element(adapted, "historical_performance")["title_style"]["font_size_pt"] == 12
    assert "presentation" not in locked
    assert "presentation" not in content


def test_first_save_of_adapted_v1_stamps_v4_without_losing_the_v2_presentation():
    current = initial_document(
        "report-v1", date(2026, 8, 31), "3033-v1", "3033-v1",
        "3033.HK", "Hang Seng TECH Index", "EN",
    )
    report = SimpleNamespace(
        id="report-v1",
        report_date=date(2026, 8, 31),
        language_mode="EN",
        template_version="3033-v1",
        active_snapshot_id=None,
        lane="PRODUCTION",
    )
    product = SimpleNamespace(
        ticker="3033.HK",
        benchmark_instrument_name="Hang Seng TECH Index",
        benchmark_instrument_code="HSTECH",
        design_token_version="3033-v1",
    )
    submitted = document_content_for_read(
        SimpleNamespace(status=ReportStatus.EDITING),
        SimpleNamespace(content=current, template_version="3033-v1"),
    )

    saved = canonicalize_document_content(
        report, product, submitted, current_content=current,
    )

    assert saved["template_version"] == "3033-v4"
    assert saved["design_token_version"] == "3033-v4"
    assert saved["presentation"]["schema_version"] == 2
    assert _element(saved, "review:summary")["title_style"]["font_size_pt"] == 14.04
