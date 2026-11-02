from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from docx import Document
from sqlalchemy import select

from app.api.routes import render as render_routes
from app.domain.document import initial_document
from app.domain.models import AuditEvent
from app.rendering.artifacts import render_docx
from app.rendering.html import render_html
from app.rendering.important_information import (
    IMPORTANT_INFORMATION_CHECKSUM,
    IMPORTANT_INFORMATION_VERSION,
    ImportantInformationResourceError,
    load_important_information,
)
from app.rendering.report_heading import resolve_report_heading


EXPECTED_PARAGRAPHS = (
    "CSOP Hang Seng TECH Index ETF is a passive exchange traded fund that is not principal "
    "guaranteed, and your investments may suffer losses. Investment in the Product may also "
    "involve risks, including but not limited to equity market risk, new index risk, risks related "
    "to companies with a technology theme, geographical concentration risk, reliance on market "
    "makers risk, differences in dealing arrangements between Listed and Unlisted Class of Units "
    "risk, tracking error risk, trading risk and risk of early termination.",
    "Investment involves risks. Investors should refer to the offering documents and product key "
    "facts statement of the Fund for further details, including the product features and risk "
    "factors. The past performance information presented is not indicative of future performance.",
    "This material is prepared by CSOP Asset Management Limited and has not been reviewed by the "
    "Securities and Futures Commission in Hong Kong.",
)


@pytest.fixture(autouse=True)
def calibri_css(monkeypatch):
    monkeypatch.setattr("app.rendering.html._embedded_calibri_font_css", lambda: "")


def _report(*, language_mode: str = "EN", product_code: str = "3033") -> SimpleNamespace:
    names = {
        "EN": "CSOP Hang Seng TECH Index ETF",
        "ZH_HANS": "南方东英恒生科技指数ETF",
        "ZH_HANT": "南方東英恒生科技指數ETF",
    }
    return SimpleNamespace(
        report_date=date(2026, 10, 31),
        language_mode=language_mode,
        product_name=f"{names[language_mode]} ({product_code}.HK)",
        product_code=product_code,
        benchmark_code="HSTECH",
    )


def _content(*, language_mode: str = "EN", product_code: str = "3033") -> dict:
    return initial_document(
        "report-compliance",
        date(2026, 10, 31),
        "3033-v6",
        "3033-v6",
        f"{product_code}.HK",
        "Hang Seng TECH Index",
        language_mode,
    )


def test_important_information_resource_is_exactly_versioned():
    resource = load_important_information()

    assert resource.version == IMPORTANT_INFORMATION_VERSION == "csop-3033-important-information-v2"
    assert resource.checksum == IMPORTANT_INFORMATION_CHECKSUM
    assert resource.product_code == "3033"
    assert resource.title == "Key Risks Reminder"
    assert resource.paragraphs == EXPECTED_PARAGRAPHS


def test_important_information_is_once_above_the_continuous_html_title_only():
    report = _report()
    content = _content()

    continuous = render_html(report, content, layout_mode="continuous")
    paged = render_html(report, content, layout_mode="paged")

    assert continuous.count('data-section-key="important-information"') == 1
    assert continuous.index('data-section-key="important-information"') < continuous.index(
        '<h1 class="report-title">'
    )
    assert continuous.count("Key Risks Reminder") == 1
    assert "IMPORTANT INFORMATION" not in continuous
    assert 'class="important-information-marker"' not in continuous
    assert '<p id="important-information-title" class="important-information-lead">Key Risks Reminder</p>' in continuous
    for paragraph in EXPECTED_PARAGRAPHS:
        assert continuous.count(paragraph) == 1
        assert paragraph not in paged
    assert 'data-section-key="important-information"' not in paged


def test_product_specific_notice_is_not_applied_to_another_product():
    markup = render_html(
        _report(product_code="3149"),
        _content(product_code="3149"),
        layout_mode="continuous",
    )

    assert 'data-section-key="important-information"' not in markup
    assert "Key Risks Reminder" not in markup


@pytest.mark.parametrize(("language_mode", "commentary"), [
    ("EN", "Monthly Commentary"),
    ("ZH_HANS", "月度评论"),
    ("ZH_HANT", "月度評論"),
])
def test_two_line_heading_is_shared_by_html_and_docx(
    tmp_path, language_mode: str, commentary: str,
):
    report = _report(language_mode=language_mode)
    content = _content(language_mode=language_mode)

    for layout_mode in ("continuous", "paged"):
        markup = render_html(report, content, layout_mode=layout_mode)
        assert markup.count('class="report-title-line report-title-product"') == 1
        assert markup.count('class="report-title-line report-title-commentary"') == 1
        assert f'>{commentary}</span>' in markup

    destination = tmp_path / f"heading-{language_mode}.docx"
    render_docx(report, content, destination)
    exported = Document(destination)
    title = exported.paragraphs[0]
    assert title.style.name == "Title"
    assert title.text.splitlines() == [report.product_name, commentary]


@pytest.mark.parametrize("product_name", [
    "CSOP Hang Seng TECH Index ETF (3033.HK)",
    "CSOP Hang Seng TECH Index ETF (3033 HK)",
    "CSOP Hang Seng TECH Index ETF 3033.HK",
])
def test_heading_does_not_repeat_ticker_with_punctuation_variants(product_name: str):
    report = _report()
    report.product_name = product_name

    heading = resolve_report_heading(report, _content())

    assert heading.product == product_name
    assert heading.flat.count("3033") == 1


def test_heading_preserves_the_document_product_name_override():
    report = _report()
    content = _content()
    content["terminology_overrides"]["product_name"] = "Approved Product Display Name"

    heading = resolve_report_heading(report, content)
    markup = render_html(report, content, layout_mode="continuous")

    assert heading.product == "Approved Product Display Name (3033.HK)"
    assert (
        'class="report-title-line report-title-product">'
        "Approved Product Display Name (3033.HK)</span>"
    ) in markup


def test_invalid_important_information_blocks_only_the_html_export_with_audit(client, monkeypatch):
    created = client.post("/api/v1/reports", json={"report_date": "2026-10-31"}).json()
    finalized = client.post(
        f"/api/v1/reports/{created['id']}/finalize",
        json={"version": 1},
    ).json()

    def fail(*_args, **_kwargs):
        raise ImportantInformationResourceError("private deployment path")

    monkeypatch.setattr(render_routes, "generate_export", fail)
    grant = client.get(f"/api/v1/reports/{finalized['id']}/exports/html/download")
    assert grant.status_code == 200, grant.text
    response = client.get(grant.json()["download_url"])

    assert response.status_code == 503
    assert response.json()["error_code"] == "IMPORTANT_INFORMATION_RESOURCE_INVALID"
    assert "private deployment path" not in response.text
    with client.app.state.testing_sessionmaker() as db:
        event = db.scalar(select(AuditEvent).where(
            AuditEvent.entity_id == finalized["id"],
            AuditEvent.action == "export.failed",
        ))
    assert event.details["important_information_version"] == IMPORTANT_INFORMATION_VERSION
    assert event.details["important_information_checksum"] == IMPORTANT_INFORMATION_CHECKSUM
