from conftest import download_report
from copy import deepcopy
import io
from datetime import datetime, timezone

import pypdfium2 as pdfium
from docx import Document
from playwright.sync_api import sync_playwright
from sqlalchemy import select

from app.domain.models import ProductCatalog


def prepared_report(client):
    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()
    client.post(f"/api/v1/reports/{report['id']}/snapshots", json={"source_policy": "GOLDEN_FIXTURE"})
    client.post(f"/api/v1/reports/{report['id']}/calculations")
    return report["id"]


def test_calculation_and_ai_draft_are_versioned_and_bound(client):
    report_id = prepared_report(client)
    calculated = client.post(f"/api/v1/reports/{report_id}/calculations")
    assert calculated.status_code == 200, calculated.text
    assert calculated.json()["metrics"]["constituent_count"] == 30
    assert calculated.json()["formula_version"] == "hstech-2026.1"
    assert client.get(f"/api/v1/reports/{report_id}").json()["status"] == "EDITING"
    version = calculated.json()["document_version"]
    metrics = client.get(f"/api/v1/reports/{report_id}/metrics").json()
    modules = client.get(f"/api/v1/reports/{report_id}/modules").json()
    quality = client.get(f"/api/v1/reports/{report_id}/quality-results").json()
    assert {item["metric_code"] for item in metrics} >= {
        "constituent_count", "weight_total", "historical.return_1m",
        "constituent.close_price", "constituent.weight", "constituent.return_1m", "industry.weight",
    }
    assert len([item for item in metrics if item["metric_code"] == "constituent.weight"]) == 30
    assert {item["module_code"] for item in modules} == {
        "constituents_performance", "final_analytics", "footnotes", "historical_performance",
    }
    assert all(item["source_dataset_ids"] for item in modules)
    assert {item["check_id"] for item in quality} >= {"QC-001", "QC-002", "QC-004"}
    bound = client.get(f"/api/v1/reports/{report_id}").json()["latest_document"]["content"]["module_bindings"]
    assert {value["module_snapshot_id"] for value in bound.values()} == {item["id"] for item in modules}
    drafted = client.post(f"/api/v1/reports/{report_id}/ai/in-review", json={"version": version, "user_prompt": "Approved outlook pending reviewer confirmation."})
    assert drafted.status_code == 200, drafted.text
    content = drafted.json()["content"]
    assert content["ai_provenance"]["provider"] == "deterministic-template"
    assert content["ai_provenance"]["metric_bindings"]
    assert "30 constituents" in content["sections"]["month_in_review"]["summary"]
    review = client.get(f"/api/v1/reports/{report_id}/review")
    assert next(item for item in review.json()["checks"] if item["check_id"] == "QC-008")["status"] == "PASSED"


def test_v3_ai_draft_replaces_initial_placeholder_review_blocks(client):
    with client.app.state.testing_sessionmaker() as db:
        product = db.scalar(select(ProductCatalog).where(ProductCatalog.product_code == "3033"))
        product.template_version = "3033-v3"
        product.design_token_version = "3033-v3"
        db.commit()

    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()
    initial = client.get(f"/api/v1/reports/{report['id']}").json()["latest_document"]["content"]
    snapshot = client.post(
        f"/api/v1/reports/{report['id']}/snapshots",
        json={"source_policy": "GOLDEN_FIXTURE"},
    )
    assert snapshot.status_code == 201, snapshot.text
    calculated = client.post(f"/api/v1/reports/{report['id']}/calculations")
    assert calculated.status_code == 200, calculated.text

    detail = client.get(f"/api/v1/reports/{report['id']}").json()
    placeholder_content = detail["latest_document"]["content"]
    placeholder_content["sections"]["month_in_review"] = initial["sections"]["month_in_review"]
    reset = client.patch(
        f"/api/v1/reports/{report['id']}/document",
        json={"version": detail["latest_document"]["version"], "content": placeholder_content},
    )
    assert reset.status_code == 200, reset.text

    drafted = client.post(
        f"/api/v1/reports/{report['id']}/ai/in-review",
        json={
            "version": reset.json()["version"],
            "user_prompt": "Approved v3 outlook pending reviewer confirmation.",
        },
    )

    assert drafted.status_code == 200, drafted.text
    review = drafted.json()["content"]["sections"]["month_in_review"]
    blocks = {block["block_id"]: block for block in review["blocks"]}
    assert "30 constituents" in review["summary"]
    assert "30 constituents" in blocks["summary"]["content"]
    assert "Differentiated constituent performance" in blocks["drivers"]["content"]
    assert "Earnings delivery and liquidity" in blocks["monitor"]["content"]
    assert "Approved v3 outlook" in blocks["outlook"]["content"]
    assert "Add monthly market review." not in blocks["summary"]["content"]


def test_ai_number_check_remains_advisory_for_unbound_numbers(client):
    report_id = prepared_report(client)
    detail = client.get(f"/api/v1/reports/{report_id}").json()
    drafted = client.post(
        f"/api/v1/reports/{report_id}/ai/in-review",
        json={"version": detail["latest_document"]["version"], "user_prompt": "Approved outlook."},
    ).json()
    content = drafted["content"]
    content["sections"]["month_in_review"]["outlook"] = "The fund is expected to return 99%."
    saved = client.patch(
        f"/api/v1/reports/{report_id}/document",
        json={"version": drafted["version"], "content": content},
    )
    assert saved.status_code == 200, saved.text
    review = client.get(f"/api/v1/reports/{report_id}/review").json()
    check = next(item for item in review["checks"] if item["check_id"] == "QC-008")
    assert check["status"] == "FAILED"
    assert "99%" in check["actual"]["unmatched"]
    finalized = client.post(
        f"/api/v1/reports/{report_id}/finalize",
        json={"version": saved.json()["version"]},
    )
    assert finalized.status_code == 200, finalized.text
    assert finalized.json()["status"] == "FINALIZED"
    events = client.get("/api/v1/audit").json()
    event = next(item for item in events if item["action"] == "report.finalized" and item["entity_id"] == report_id)
    assert "QC-008" in event["details"]["advisory_check_ids"]


def test_news_candidate_selection_and_order(client):
    report_id = prepared_report(client)
    created = []
    for index in range(2):
        response = client.post(f"/api/v1/reports/{report_id}/news/candidates", json={
            "source_name": "Approved source", "source_url": f"https://example.test/news-{index}",
            "published_at": datetime(2026, 6, index + 1, tzinfo=timezone.utc).isoformat(),
            "title": f"News {index}", "summary": f"Summary {index}", "security_code": "700", "ticker": "0700.HK", "importance": "HIGH",
        })
        assert response.status_code == 201
        created.append(response.json())
    detail = client.get(f"/api/v1/reports/{report_id}").json()
    version = detail["latest_document"]["version"]
    selected = client.put(f"/api/v1/reports/{report_id}/news", json={"version": version, "items": [
        {"news_item_id": created[1]["id"], "position": 0},
        {"news_item_id": created[0]["id"], "position": 1, "title_override": "Reviewed title"},
    ]})
    assert selected.status_code == 200, selected.text
    assert [item["title"] for item in selected.json()["items"]] == ["News 1", "Reviewed title"]
    preview = client.post(f"/api/v1/reports/{report_id}/preview")
    assert preview.text.index("News 1") < preview.text.index("Reviewed title")


def test_manual_news_can_be_outside_the_report_month(client):
    report_id = prepared_report(client)
    response = client.post(f"/api/v1/reports/{report_id}/news/candidates", json={
        "source_name": "Source",
        "source_url": "https://example.test/news-before-month",
        "published_at": datetime(2026, 5, 31, tzinfo=timezone.utc).isoformat(),
        "title": "Before the report month",
        "summary": "Out of range",
        "ticker": "0700.HK",
    })

    assert response.status_code == 201, response.text
    assert response.json()["title"] == "Before the report month"


def test_selected_news_survives_recalculation_and_renders_source_only(client):
    report_id = prepared_report(client)
    candidate = client.post(f"/api/v1/reports/{report_id}/news/candidates", json={
        "source_name": "Reuters",
        "source_url": "https://example.test/june-news",
        "published_at": datetime(2026, 6, 12, 8, 30, tzinfo=timezone.utc).isoformat(),
        "title": "June selected headline",
        "summary": "Selected report-month summary",
        "ticker": "0700.HK",
    })
    assert candidate.status_code == 201, candidate.text
    detail = client.get(f"/api/v1/reports/{report_id}").json()
    selected = client.put(f"/api/v1/reports/{report_id}/news", json={
        "version": detail["latest_document"]["version"],
        "items": [{"news_item_id": candidate.json()["id"], "position": 0}],
    })
    assert selected.status_code == 200, selected.text

    recalculated = client.post(f"/api/v1/reports/{report_id}/calculations")

    assert recalculated.status_code == 200, recalculated.text
    content = client.get(f"/api/v1/reports/{report_id}").json()["latest_document"]["content"]
    assert [item["title"] for item in content["sections"]["company_news"]] == ["June selected headline"]
    stored_news = content["sections"]["company_news"][0]
    assert stored_news["published_at"].startswith("2026-06-12")
    assert stored_news["source_url"] == "https://example.test/june-news"
    preview = client.post(f"/api/v1/reports/{report_id}/preview")
    assert "Reuters" in preview.text
    assert '<div class="news-meta">Reuters</div>' in preview.text
    assert "2026-06-12" not in preview.text
    assert "https://example.test/june-news" not in preview.text

    latest = client.get(f"/api/v1/reports/{report_id}").json()
    finalized = client.post(
        f"/api/v1/reports/{report_id}/finalize",
        json={"version": latest["latest_document"]["version"]},
    )
    assert finalized.status_code == 200, finalized.text
    downloads = {format_name: download_report(client, report_id, format_name) for format_name in ["docx"]}
    document = Document(io.BytesIO(downloads["docx"].content))
    docx_text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "Reuters" in docx_text
    assert "2026-06-12" not in docx_text
    assert "https://example.test/june-news" not in docx_text


def test_review_accepts_complete_golden_editorial(client):
    report_id = prepared_report(client)
    review = client.get(f"/api/v1/reports/{report_id}/review")
    assert review.status_code == 200
    assert review.json()["ready"] is True
    assert any(item["check_id"] == "QC-009" and item["status"] == "PASSED" for item in review.json()["checks"])


def test_review_layout_is_sanitized_versioned_and_rejects_overlap(client):
    report_id = prepared_report(client)
    detail = client.get(f"/api/v1/reports/{report_id}").json()
    content = detail["latest_document"]["content"]
    version = detail["latest_document"]["version"]
    content["sections"]["month_in_review"]["display_title"] = "June Market Reset"
    content["sections"]["month_in_review"]["title"] = "June Market Reset"
    content["sections"]["month_in_review"]["blocks"] = [
        {"block_id": "summary", "type": "rich_text", "title": "Summary", "content": '<p>Approved</p><script>alert(1)</script><a href="javascript:bad">bad</a>', "x": 0, "y": 0, "w": 12, "h": 4, "text_align": "center"},
        {"block_id": "outlook", "type": "outlook", "title": "Outlook", "content": "<p>Outlook</p>", "x": 0, "y": 4, "w": 6, "h": 4},
    ]
    saved = client.patch(f"/api/v1/reports/{report_id}/document", json={"version": version, "content": content})
    assert saved.status_code == 200, saved.text
    review = saved.json()["content"]["sections"]["month_in_review"]
    assert review["title"] == "Summary"
    assert review["display_title"] == "Summary"
    assert "<script>" not in review["blocks"][0]["content"]
    assert "javascript:" not in review["blocks"][0]["content"]
    assert review["blocks"][0]["text_align"] == "center"
    preview = client.post(f"/api/v1/reports/{report_id}/preview")
    assert preview.status_code == 200
    assert ">June Market Reset</h2>" not in preview.text
    assert ">Summary</h3>" in preview.text
    assert 'data-block-id="summary"' in preview.text
    assert 'class="review-layout-block align-center"' in preview.text
    assert "<script>" not in preview.text

    invalid_content = saved.json()["content"]
    invalid_content["sections"]["month_in_review"]["blocks"][1].update({"x": 5, "y": 2})
    rejected = client.patch(f"/api/v1/reports/{report_id}/document", json={"version": saved.json()["version"], "content": invalid_content})
    assert rejected.status_code == 422
    assert rejected.json()["error_code"] == "PAGE_ONE_PRESENTATION_INVALID"


def test_draft_preview_accepts_a_stale_version_without_persisting_it(client):
    report = client.post(
        "/api/v1/reports",
        json={"product_code": "3033", "report_date": "2026-06-30"},
    ).json()
    detail = client.get(f"/api/v1/reports/{report['id']}").json()
    stale_version = detail["latest_document"]["version"]
    stale_content = deepcopy(detail["latest_document"]["content"])
    stale_content["sections"]["month_in_review"]["blocks"][0]["content"] = (
        "<p>Unsaved stale draft remains previewable.</p>"
    )

    concurrent_content = deepcopy(detail["latest_document"]["content"])
    concurrent_content["sections"]["month_in_review"]["blocks"][0]["content"] = (
        "<p>Concurrent saved edit.</p>"
    )
    saved = client.patch(
        f"/api/v1/reports/{report['id']}/document",
        json={"version": stale_version, "content": concurrent_content},
    )
    assert saved.status_code == 200, saved.text

    preview = client.post(
        f"/api/v1/reports/{report['id']}/preview",
        json={"version": stale_version, "content": stale_content},
    )

    assert preview.status_code == 200, preview.text
    assert "Unsaved stale draft remains previewable." in preview.text
    assert client.get(f"/api/v1/reports/{report['id']}").json()["latest_document"][
        "version"
    ] == saved.json()["version"]


def test_review_title_content_spacing_is_saved_reloaded_and_previewed(client):
    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()
    detail = client.get(f"/api/v1/reports/{report['id']}").json()
    content = detail["latest_document"]["content"]
    expected_gaps = {
        "review:summary": 0.0,
        "review:drivers": 1.5,
        "review:monitor": 3.0,
        "review:outlook": 4.5,
        "historical_performance": 6.0,
    }
    elements = content["presentation"]["page_one"]["elements"]
    for element in elements:
        if element["id"] in expected_gaps:
            element["title_style"]["space_after_pt"] = expected_gaps[element["id"]]
    next(element for element in elements if element["id"] == "review:summary")[
        "title_style"
    ]["font_size_pt"] = 5

    saved = client.patch(
        f"/api/v1/reports/{report['id']}/document",
        json={"version": detail["latest_document"]["version"], "content": content},
    )

    assert saved.status_code == 200, saved.text
    persisted = client.get(f"/api/v1/reports/{report['id']}").json()[
        "latest_document"
    ]["content"]
    persisted_elements = {
        element["id"]: element
        for element in persisted["presentation"]["page_one"]["elements"]
    }
    for element_id, expected_gap in expected_gaps.items():
        assert persisted_elements[element_id]["title_style"]["space_after_pt"] == expected_gap
    assert persisted_elements["review:summary"]["title_style"]["font_size_pt"] == 14.04

    preview = client.post(f"/api/v1/reports/{report['id']}/preview")
    assert preview.status_code == 200, preview.text
    for element_id, expected_gap in expected_gaps.items():
        closing_tag = "</h3>" if element_id.startswith("review:") else "</h2>"
        heading = preview.text.split(f'data-layout-id="{element_id}"', 1)[1].split(
            closing_tag, 1
        )[0]
        assert f"margin-bottom:{expected_gap}pt" in heading


def _review_layout_measurements(markup: str) -> dict:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1000, "height": 1200})
        page.set_content(markup, wait_until="load")
        result = page.evaluate("""() => {
            const element = (selector) => document.querySelector(selector);
            const rect = (selector) => element(selector).getBoundingClientRect();
            const contentBottom = (id) => rect(`[data-block-id="${id}"] .review-layout-content`).bottom;
            const lineHeight = parseFloat(getComputedStyle(
                element('[data-block-id="summary"] .review-layout-content')
            ).lineHeight);
            const driver = rect('[data-block-id="drivers"]');
            const monitor = rect('[data-block-id="monitor"]');
            const outlook = rect('[data-block-id="outlook"]');
            const summary = rect('[data-block-id="summary"]');
            const history = rect('[data-page="1"] h2.center');
            const footer = document.querySelector('[data-page="1"] .page-footer');
            return {
                lineHeight,
                gaps: {
                    summaryToDrivers: driver.top - contentBottom('summary'),
                    monitorToOutlook: outlook.top - contentBottom('monitor'),
                    reviewToHistory: history.top - Math.max(contentBottom('drivers'), contentBottom('outlook')),
                },
                summary: { left: summary.left, right: summary.right },
                driver: { left: driver.left, right: driver.right, bottom: contentBottom('drivers') },
                monitor: { left: monitor.left, right: monitor.right },
                outlook: { left: outlook.left, right: outlook.right, top: outlook.top },
                historyBottom: rect('[data-page="1"] table.history').bottom,
                footerTop: footer ? footer.getBoundingClientRect().top : null,
            };
        }""")
        browser.close()
    return result


def test_review_preview_compacts_sparse_block_heights_without_changing_columns(client, tmp_path):
    report_id = prepared_report(client)
    detail = client.get(f"/api/v1/reports/{report_id}").json()
    content = detail["latest_document"]["content"]
    content["sections"]["month_in_review"]["blocks"] = [
        {"block_id": "summary", "type": "rich_text", "title": "Monthly summary", "content": "<p>Short summary.</p>", "x": 0, "y": 0, "w": 12, "h": 4},
        {"block_id": "drivers", "type": "key_drivers", "title": "Key Drivers", "content": "<p>Short driver.</p>", "x": 0, "y": 4, "w": 6, "h": 7},
        {"block_id": "monitor", "type": "areas_to_monitor", "title": "Key Areas to Monitor", "content": "<p>Short monitor.</p>", "x": 6, "y": 4, "w": 6, "h": 5},
        {"block_id": "outlook", "type": "outlook", "title": "Outlook", "content": "<p>Short outlook.</p>", "x": 6, "y": 9, "w": 6, "h": 4},
    ]
    saved = client.patch(
        f"/api/v1/reports/{report_id}/document",
        json={"version": detail["latest_document"]["version"], "content": content},
    )
    assert saved.status_code == 200, saved.text

    preview = client.post(f"/api/v1/reports/{report_id}/preview")
    assert preview.status_code == 200, preview.text
    finalized = client.post(f"/api/v1/reports/{report_id}/finalize", json={"version": saved.json()["version"]})
    assert finalized.status_code == 200, finalized.text
    downloads = {format_name: download_report(client, report_id, format_name) for format_name in ["html", "pdf"]}
    artifacts = {}
    for format_name, download in downloads.items():
        artifacts[format_name] = download.content
    continuous_html = artifacts["html"].decode("utf-8")
    pdf_path = tmp_path / "compact-review.pdf"
    pdf_path.write_bytes(artifacts["pdf"])
    assert len(pdfium.PdfDocument(str(pdf_path))) == 5

    for markup in (preview.text, continuous_html):
        measured = _review_layout_measurements(markup)
        assert all(0 <= gap <= measured["lineHeight"] * 2 for gap in measured["gaps"].values()), measured
        assert abs(measured["summary"]["left"] - measured["driver"]["left"]) <= 1
        assert abs(measured["summary"]["right"] - measured["monitor"]["right"]) <= 1
        assert measured["driver"]["right"] < measured["monitor"]["left"]
        assert abs(measured["monitor"]["left"] - measured["outlook"]["left"]) <= 1
        assert abs(measured["monitor"]["right"] - measured["outlook"]["right"]) <= 1
        if measured["footerTop"] is not None:
            assert measured["historyBottom"] < measured["footerTop"]


def test_review_preview_keeps_staggered_columns_independent(client):
    report_id = prepared_report(client)
    detail = client.get(f"/api/v1/reports/{report_id}").json()
    content = detail["latest_document"]["content"]
    long_driver = " ".join(["Long driver content stays in the left column."] * 45)
    content["sections"]["month_in_review"]["blocks"] = [
        {"block_id": "summary", "type": "rich_text", "title": "Monthly summary", "content": "<p>Short summary.</p>", "x": 0, "y": 0, "w": 12, "h": 4},
        {"block_id": "drivers", "type": "key_drivers", "title": "Key Drivers", "content": f"<p>{long_driver}</p>", "x": 0, "y": 4, "w": 6, "h": 10},
        {"block_id": "monitor", "type": "areas_to_monitor", "title": "Key Areas to Monitor", "content": "<p>Short monitor.</p>", "x": 6, "y": 4, "w": 6, "h": 4},
        {"block_id": "outlook", "type": "outlook", "title": "Outlook", "content": "<p>Short outlook.</p>", "x": 6, "y": 8, "w": 6, "h": 4},
    ]
    saved = client.patch(
        f"/api/v1/reports/{report_id}/document",
        json={"version": detail["latest_document"]["version"], "content": content},
    )
    assert saved.status_code == 200, saved.text

    preview = client.post(f"/api/v1/reports/{report_id}/preview")
    assert preview.status_code == 200, preview.text
    measured = _review_layout_measurements(preview.text)

    assert all(0 <= gap <= measured["lineHeight"] * 2 for gap in measured["gaps"].values()), measured
    assert measured["outlook"]["top"] < measured["driver"]["bottom"], measured
    assert measured["historyBottom"] < measured["footerTop"], measured


def test_manual_next_rebalancing_date_is_rendered_and_survives_recalculation(client):
    report_id = prepared_report(client)
    detail = client.get(f"/api/v1/reports/{report_id}").json()
    content = detail["latest_document"]["content"]
    assert content["next_rebalancing_date"] == "2026-09-04"
    content["next_rebalancing_date"] = "2026-10-15"
    content["next_rebalancing_date_source"] = "MANUAL"

    saved = client.patch(
        f"/api/v1/reports/{report_id}/document",
        json={"version": detail["latest_document"]["version"], "content": content},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["content"]["next_rebalancing_date_source"] == "MANUAL"
    preview = client.post(f"/api/v1/reports/{report_id}/preview")
    assert preview.status_code == 200
    assert "(*Next Rebalancing Date: 15 October 2026)" in preview.text

    recalculated = client.post(f"/api/v1/reports/{report_id}/calculations")
    assert recalculated.status_code == 200, recalculated.text
    refreshed = client.get(f"/api/v1/reports/{report_id}").json()["latest_document"]["content"]
    assert refreshed["next_rebalancing_date"] == "2026-10-15"
    assert refreshed["next_rebalancing_date_source"] == "MANUAL"


def test_review_layout_replaces_stale_legacy_placeholders_on_save(client):
    report_id = prepared_report(client)
    detail = client.get(f"/api/v1/reports/{report_id}").json()
    content = detail["latest_document"]["content"]
    review = content["sections"]["month_in_review"]
    review["summary"] = "Add monthly market review."
    review["outlook"] = "Add outlook."
    review["blocks"] = [
        {
            "block_id": "custom-commentary",
            "type": "rich_text",
            "title": "Monthly commentary",
            "content": "<p>Approved monthly commentary.</p>",
            "x": 0,
            "y": 0,
            "w": 12,
            "h": 4,
        },
    ]

    saved = client.patch(
        f"/api/v1/reports/{report_id}/document",
        json={"version": detail["latest_document"]["version"], "content": content},
    )

    assert saved.status_code == 200, saved.text
    saved_review = saved.json()["content"]["sections"]["month_in_review"]
    assert saved_review["summary"] == "Approved monthly commentary."
    assert saved_review["outlook"] == ""
    verdict = client.get(f"/api/v1/reports/{report_id}/review").json()
    assert next(item for item in verdict["checks"] if item["check_id"] == "QC-009")["status"] == "PASSED"


def test_review_blocks_render_to_html_and_editable_docx(client):
    report_id = prepared_report(client)
    detail = client.get(f"/api/v1/reports/{report_id}").json()
    content = detail["latest_document"]["content"]
    content["sections"]["month_in_review"]["display_title"] = "Custom June Review"
    content["sections"]["month_in_review"]["title"] = "Custom June Review"
    content["sections"]["month_in_review"]["blocks"] = [
        {"block_id": "summary", "type": "rich_text", "title": "Summary", "content": "<p>Editable custom review content</p>", "x": 0, "y": 0, "w": 12, "h": 4},
        {"block_id": "outlook", "type": "outlook", "title": "Outlook", "content": "<p>Approved outlook</p>", "x": 0, "y": 4, "w": 6, "h": 4},
    ]
    saved = client.patch(f"/api/v1/reports/{report_id}/document", json={"version": detail["latest_document"]["version"], "content": content})
    assert saved.status_code == 200, saved.text
    finalized = client.post(f"/api/v1/reports/{report_id}/finalize", json={"version": saved.json()["version"]})
    assert finalized.status_code == 200, finalized.text
    downloads = {format_name: download_report(client, report_id, format_name) for format_name in ["html", "docx"]}

    artifacts = {}
    for format_name, download in downloads.items():
        artifacts[format_name] = download.content
    assert b'data-block-id="summary"' in artifacts["html"]
    assert b"Editable custom review content" in artifacts["html"]
    docx = Document(io.BytesIO(artifacts["docx"]))
    text = "\n".join(
        [paragraph.text for paragraph in docx.paragraphs]
        + [cell.text for table in docx.tables for row in table.rows for cell in row.cells]
    )
    assert "Summary" in text
    assert "Custom June Review" not in text
    assert "Editable custom review content" in text


def test_review_title_survives_snapshot_rebinding_and_has_structured_validation(client):
    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()
    detail = client.get(f"/api/v1/reports/{report['id']}").json()
    content = detail["latest_document"]["content"]
    assert content["sections"]["month_in_review"]["display_title"] == "June in Review"
    content["sections"]["month_in_review"]["display_title"] = "Editable Monthly Perspective"
    content["sections"]["month_in_review"]["title"] = "Editable Monthly Perspective"
    saved = client.patch(
        f"/api/v1/reports/{report['id']}/document",
        json={"version": detail["latest_document"]["version"], "content": content},
    )
    assert saved.status_code == 200, saved.text

    rebound = client.post(f"/api/v1/reports/{report['id']}/snapshots", json={"source_policy": "GOLDEN_FIXTURE"})
    assert rebound.status_code == 201, rebound.text
    refreshed_detail = client.get(f"/api/v1/reports/{report['id']}").json()
    refreshed = refreshed_detail["latest_document"]["content"]
    assert refreshed["sections"]["month_in_review"]["display_title"] == "Editable Monthly Perspective"
    assert ">Editable Monthly Perspective</h3>" in client.post(f"/api/v1/reports/{report['id']}/preview").text

    refreshed["sections"]["month_in_review"]["blocks"][0]["title"] = "   "
    rejected = client.patch(
        f"/api/v1/reports/{report['id']}/document",
        json={"version": refreshed_detail["latest_document"]["version"], "content": refreshed},
    )
    assert rejected.status_code == 422
    assert rejected.json()["error_code"] == "REVIEW_BLOCK_TITLE_INVALID"
    assert rejected.json()["field"] == "sections.month_in_review.blocks.0.title"


def test_review_subtitle_and_title_body_indents_are_saved_and_previewed(client):
    report = client.post("/api/v1/reports", json={"report_date": "2026-08-31"}).json()
    detail = client.get(f"/api/v1/reports/{report['id']}").json()
    first_save = client.patch(
        f"/api/v1/reports/{report['id']}/document",
        json={
            "version": detail["latest_document"]["version"],
            "content": detail["latest_document"]["content"],
        },
    )
    assert first_save.status_code == 200, first_save.text
    content = deepcopy(first_save.json()["content"])
    summary = content["sections"]["month_in_review"]["blocks"][0]
    summary["title"] = "Editable market subheading"
    content["sections"]["month_in_review"]["title"] = summary["title"]
    content["sections"]["month_in_review"]["display_title"] = summary["title"]
    summary_element = next(
        element
        for element in content["presentation"]["page_one"]["elements"]
        if element["id"] == "review:summary"
    )
    summary_element["title_style"]["indent_level"] = 1
    summary_element["body_style"]["indent_level"] = 2

    saved = client.patch(
        f"/api/v1/reports/{report['id']}/document",
        json={"version": first_save.json()["version"], "content": content},
    )

    assert saved.status_code == 200, saved.text
    persisted = saved.json()["content"]
    persisted_summary = persisted["sections"]["month_in_review"]["blocks"][0]
    persisted_element = next(
        element
        for element in persisted["presentation"]["page_one"]["elements"]
        if element["id"] == "review:summary"
    )
    assert persisted_summary["title"] == "Editable market subheading"
    assert persisted_element["title_style"]["indent_level"] == 1
    assert persisted_element["body_style"]["indent_level"] == 2
    preview = client.post(f"/api/v1/reports/{report['id']}/preview")
    assert preview.status_code == 200, preview.text
    assert ">Editable market subheading</h3>" in preview.text
    assert "margin-left:2em" in preview.text
    assert "margin-left:4em" in preview.text
