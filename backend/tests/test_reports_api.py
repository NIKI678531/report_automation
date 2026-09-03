import io
import unicodedata

from docx import Document
from app.domain.localization import simplified_to_traditional


def create_report(client):
    response = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}, headers={"X-Request-ID": "test-create"})
    assert response.status_code == 201, response.text
    return response.json()


def test_delete_draft_soft_deletes_it_from_the_report_list_and_keeps_audit(client):
    report = create_report(client)

    deleted = client.delete(
        f"/api/v1/reports/{report['id']}?version={report['version']}",
        headers={"X-Request-ID": "test-delete-draft"},
    )

    assert deleted.status_code == 204, deleted.text
    assert report["id"] not in {item["id"] for item in client.get("/api/v1/reports").json()}
    archived = client.get("/api/v1/reports?include_archived=true")
    assert archived.status_code == 200
    assert report["id"] in {item["id"] for item in archived.json()}
    retained = client.get(f"/api/v1/reports/{report['id']}")
    assert retained.status_code == 200
    assert retained.json()["status"] == "ARCHIVED"
    event = next(
        item for item in client.get(f"/api/v1/audit?report_id={report['id']}").json()
        if item["action"] == "report.deleted"
    )
    assert event["details"] == {
        "deletion_mode": "SOFT_DELETE",
        "previous_status": "DRAFT",
        "retained_for_audit": True,
    }


def test_archived_report_rejects_mutation(client):
    report = create_report(client)
    client.delete(f"/api/v1/reports/{report['id']}?version={report['version']}")
    detail = client.get(f"/api/v1/reports/{report['id']}").json()

    updated = client.patch(
        f"/api/v1/reports/{report['id']}/document",
        json={"version": detail["latest_document"]["version"], "content": detail["latest_document"]["content"]},
    )
    refreshed = client.post(
        f"/api/v1/reports/{report['id']}/automatic-data/refresh",
        json={"version": detail["version"]},
    )
    deleted_again = client.delete(
        f"/api/v1/reports/{report['id']}?version={detail['version']}",
    )

    assert updated.status_code == 409
    assert updated.json()["error_code"] == "REPORT_ARCHIVED"
    assert refreshed.status_code == 409
    assert refreshed.json()["error_code"] == "REPORT_ARCHIVED"
    assert deleted_again.status_code == 409
    assert deleted_again.json()["error_code"] == "REPORT_ARCHIVED"


def test_delete_finalized_report_and_reject_stale_version(client):
    report = create_report(client)
    finalized = client.post(
        f"/api/v1/reports/{report['id']}/finalize",
        json={"version": 1},
    ).json()

    stale = client.delete(f"/api/v1/reports/{report['id']}?version={report['version']}")
    assert stale.status_code == 409
    assert stale.json()["error_code"] == "VERSION_CONFLICT"

    deleted = client.delete(
        f"/api/v1/reports/{report['id']}?version={finalized['version']}",
    )
    assert deleted.status_code == 204, deleted.text
    assert client.get(f"/api/v1/reports/{report['id']}").json()["status"] == "ARCHIVED"


def test_report_golden_lifecycle_and_preview(client):
    import pypdfium2 as pdfium
    report = create_report(client)
    snapshot = client.post(
        f"/api/v1/reports/{report['id']}/snapshots",
        json={"source_policy": "GOLDEN_FIXTURE", "mapping_version": "hstech-v1"},
    )
    assert snapshot.status_code == 201, snapshot.text
    assert snapshot.json()["status"] == "VALID"
    assert len(snapshot.json()["payload"]["constituents"]) == 30
    assert all(item["status"] == "PASSED" for item in snapshot.json()["quality_results"])

    detail = client.get(f"/api/v1/reports/{report['id']}").json()
    assert detail["status"] == "DATA_READY"
    calculated = client.post(f"/api/v1/reports/{report['id']}/calculations")
    assert calculated.status_code == 200, calculated.text
    detail = client.get(f"/api/v1/reports/{report['id']}").json()
    assert detail["active_snapshot_id"]
    assert detail["latest_document"]["version"] == calculated.json()["document_version"]
    content = detail["latest_document"]["content"]
    review = content["sections"]["month_in_review"]
    review["title"] = "June Technology Review"
    review["display_title"] = "June Technology Review"
    review["blocks"] = [
        {"block_id": "summary", "type": "rich_text", "title": "Market Context", "content": "<p>Approved market context.</p>", "x": 0, "y": 0, "w": 12, "h": 4},
        {"block_id": "outlook", "type": "outlook", "title": "Forward View", "content": "<p>Approved forward view.</p>", "x": 0, "y": 4, "w": 12, "h": 4},
    ]
    saved = client.patch(
        f"/api/v1/reports/{report['id']}/document",
        json={"version": detail["latest_document"]["version"], "content": content},
    )
    assert saved.status_code == 200, saved.text

    preview = client.post(f"/api/v1/reports/{report['id']}/preview")
    assert preview.status_code == 200
    assert preview.text.count('class="report-page"') == 4
    assert "The Performance of HSTECH Constituents" in preview.text
    assert "June Technology Review" not in preview.text
    assert "Market Context" in preview.text
    assert '<svg class="donut"' in preview.text
    assert preview.text.count('data-sector-slice=') >= 3
    assert "conic-gradient" not in preview.text
    assert "border-left:.8mm solid var(--blue)" not in preview.text
    assert "background:#f7f9fc" not in preview.text

    finalized = client.post(f"/api/v1/reports/{report['id']}/finalize", json={"version": saved.json()["version"]})
    assert finalized.status_code == 200, finalized.text
    assert finalized.json()["status"] == "FINALIZED"
    clear_finalized = client.post(
        f"/api/v1/reports/{report['id']}/datasets/constituent_returns/clear",
        json={"version": finalized.json()["version"]},
    )
    assert clear_finalized.status_code == 409
    assert clear_finalized.json()["error_code"] == "REPORT_FINALIZED"

    rendered = client.post(
        f"/api/v1/reports/{report['id']}/renders",
        json={"formats": ["html", "pdf", "docx"]},
        headers={"Idempotency-Key": "golden-render"},
    )
    assert rendered.status_code == 202, rendered.text
    assert [job["status"] for job in rendered.json()] == ["SUCCEEDED", "SUCCEEDED", "SUCCEEDED"]
    for job in rendered.json():
        signed = client.get(f"/api/v1/artifacts/{job['artifact_id']}/download")
        assert signed.status_code == 200
        assert "signature=" in signed.json()["download_url"]
        download = client.get(signed.json()["download_url"])
        assert download.status_code == 200
        assert len(download.content) > 1000
        if job["format"] == "pdf":
            pdf = pdfium.PdfDocument(download.content)
            assert len(pdf) == 4
            first_page_text = pdf[0].get_textpage().get_text_range()
            assert "June Technology Review" not in first_page_text
            assert "Market Context" in first_page_text
            assert "Forward View" in first_page_text
    artifacts = client.get(f"/api/v1/reports/{report['id']}").json()["artifacts"]
    assert len({item["content_manifest_checksum"] for item in artifacts}) == 1
    assert artifacts[0]["content_manifest_checksum"]


def test_recalculation_replaces_existing_final_analytics_snapshot(client):
    from copy import deepcopy

    from sqlalchemy import select

    from app.domain.document import checksum
    from app.domain.models import DataSnapshot, ModuleSnapshot

    report = create_report(client)
    created_snapshot = client.post(
        f"/api/v1/reports/{report['id']}/snapshots",
        json={"source_policy": "GOLDEN_FIXTURE", "mapping_version": "hstech-v1"},
    )
    assert created_snapshot.status_code == 201, created_snapshot.text
    first_calculation = client.post(f"/api/v1/reports/{report['id']}/calculations")
    assert first_calculation.status_code == 200, first_calculation.text
    before = client.get(f"/api/v1/reports/{report['id']}").json()
    snapshot_id = before["active_snapshot_id"]

    with client.app.state.testing_sessionmaker() as session:
        previous = session.scalar(select(ModuleSnapshot).where(
            ModuleSnapshot.snapshot_id == snapshot_id,
            ModuleSnapshot.module_code == "final_analytics",
        ))
        assert previous is not None
        previous_id = previous.id
        previous_checksum = previous.checksum
        previous_payload = deepcopy(previous.payload)

        snapshot = session.get(DataSnapshot, snapshot_id)
        assert snapshot is not None
        changed_payload = deepcopy(snapshot.payload)
        changed_payload["constituents"][0]["return_1m"] = 0.999
        snapshot.payload = changed_payload
        snapshot.checksum = checksum(changed_payload)
        session.commit()

    recalculated = client.post(f"/api/v1/reports/{report['id']}/calculations")
    assert recalculated.status_code == 200, recalculated.text
    after = client.get(f"/api/v1/reports/{report['id']}").json()
    binding = after["latest_document"]["content"]["module_bindings"]["final_analytics"]

    with client.app.state.testing_sessionmaker() as session:
        refreshed = session.scalar(select(ModuleSnapshot).where(
            ModuleSnapshot.snapshot_id == snapshot_id,
            ModuleSnapshot.module_code == "final_analytics",
        ))
        assert refreshed is not None
        assert refreshed.id == previous_id
        assert refreshed.checksum != previous_checksum
        assert refreshed.payload != previous_payload
        assert refreshed.payload == after["latest_document"]["content"]["sections"]["analytics"]
        assert binding == {"module_snapshot_id": refreshed.id, "checksum": refreshed.checksum}


def test_unfinished_report_preview_keeps_layout_and_fixed_portfolio_rows(client):
    report = create_report(client)

    preview = client.post(f"/api/v1/reports/{report['id']}/preview")

    assert preview.status_code == 200, preview.text
    assert preview.text.count('class="report-page"') == 4
    assert "Historical Performance of 3033.HK" in preview.text
    assert "Company News" in preview.text
    assert "Add monthly market review." not in preview.text
    assert "Add outlook." not in preview.text
    assert "Add key drivers." not in preview.text
    assert "No company news has been selected." not in preview.text
    assert 'data-metric-code="AUM"' in preview.text
    assert "Asset Under Management (HKD)^" in preview.text
    assert 'data-metric-code="AVERAGE_DAILY_TURNOVER"' in preview.text
    assert "Average Daily Turnover (HKD)^^" in preview.text
    assert 'data-metric-code="NUMBER_OF_HOLDINGS"' in preview.text
    assert 'data-layout-mode="paged"' in preview.text
    assert preview.text.count(
        '<header class="page-header">Monthly Commentary | June 30, 2026</header>'
    ) == 4
    assert preview.text.count('<footer class="page-footer">') == 4
    assert preview.text.count('alt="CSOP Asset Management"') == 4
    for page in range(1, 5):
        assert f'<span class="page-number">{page}</span>' in preview.text


def test_simplified_chinese_variant_rebuilds_snapshot_lineage_and_is_independent(client):
    from sqlalchemy import select

    from app.domain.models import DataSnapshot, MetricValue, SnapshotDataset

    source = create_report(client)
    created_snapshot = client.post(
        f"/api/v1/reports/{source['id']}/snapshots",
        json={"source_policy": "GOLDEN_FIXTURE", "mapping_version": "hstech-v1"},
    )
    assert created_snapshot.status_code == 201, created_snapshot.text
    calculated = client.post(f"/api/v1/reports/{source['id']}/calculations")
    assert calculated.status_code == 200, calculated.text
    source_detail = client.get(f"/api/v1/reports/{source['id']}").json()

    response = client.post(
        f"/api/v1/reports/{source['id']}/language-variants",
        json={
            "language_mode": "ZH_HANS",
            "source_document_version": source_detail["latest_document"]["version"],
        },
        headers={"X-Request-ID": "test-zh-variant"},
    )
    assert response.status_code == 201, response.text
    variant = client.get(f"/api/v1/reports/{response.json()['id']}").json()
    assert variant["language_mode"] == "ZH_HANS"
    assert variant["translation_source_report_id"] == source["id"]
    assert variant["active_snapshot_id"] != source_detail["active_snapshot_id"]
    assert variant["latest_document"]["content"]["sections"]["month_in_review"]["summary"] == ""
    assert variant["latest_document"]["content"]["month_name"] == "6月"

    with client.app.state.testing_sessionmaker() as session:
        target_snapshot = session.get(DataSnapshot, variant["active_snapshot_id"])
        assert target_snapshot.source_snapshot_id == source_detail["active_snapshot_id"]
        source_datasets = list(session.scalars(select(SnapshotDataset).where(
            SnapshotDataset.snapshot_id == source_detail["active_snapshot_id"]
        )))
        target_datasets = list(session.scalars(select(SnapshotDataset).where(
            SnapshotDataset.snapshot_id == variant["active_snapshot_id"]
        )))
        assert {item.dataset_type: item.checksum for item in target_datasets} == {
            item.dataset_type: item.checksum for item in source_datasets
        }
        source_metrics = {(item.metric_code, item.dimension_key): item.raw_value for item in session.scalars(select(MetricValue).where(MetricValue.snapshot_id == source_detail["active_snapshot_id"]))}
        target_metrics = {(item.metric_code, item.dimension_key): item.raw_value for item in session.scalars(select(MetricValue).where(MetricValue.snapshot_id == variant["active_snapshot_id"]))}
        assert target_metrics == source_metrics

    review = client.get(f"/api/v1/reports/{variant['id']}/review").json()
    assert any(item["check_id"] == "LANG-ZH-001" for item in review["warnings"])
    preview = client.post(f"/api/v1/reports/{variant['id']}/preview")
    assert preview.status_code == 200, preview.text
    assert 'lang="zh-CN"' in preview.text
    assert '@font-face{font-family:"Embedded Noto Sans CJK SC"' in preview.text
    # The face must travel inside the document rather than be named and hoped for. Which container
    # carries it depends on the host: a variable .ttf on Windows, Debian's .ttc collection in the
    # image and on CI — asserting one of them asserts the developer's laptop, not the property.
    assert 'src:url("data:font/' in preview.text
    assert "公司新闻" in preview.text
    assert "Company News" not in preview.text
    assert 'data-layout-mode="paged"' in preview.text
    assert preview.text.count('<header class="page-header">') == 4
    assert preview.text.count('<footer class="page-footer">') == 4
    assert preview.text.count('alt="CSOP Asset Management"') == 4

    duplicate = client.post(
        f"/api/v1/reports/{source['id']}/language-variants",
        json={
            "language_mode": "ZH_HANS",
            "source_document_version": source_detail["latest_document"]["version"],
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error_code"] == "LANGUAGE_VARIANT_EXISTS"
    assert duplicate.json()["existing_report_id"] == variant["id"]

    content = variant["latest_document"]["content"]
    first_security = content["sections"]["constituents"][0]["security_code"]
    first_industry = content["sections"]["analytics"]["sector_chart"]["series"][0]["code"]
    content["sections"]["month_in_review"]["blocks"] = [{
        "block_id": "summary", "type": "rich_text", "title": "月度回顾",
        "content": "<p>已审核的中文月度回顾。</p>", "x": 0, "y": 0, "w": 12, "h": 4,
        "text_align": "left",
    }]
    content["terminology_overrides"] = {
        "product_name": "南方东英测试产品",
        "benchmark_name": "恒生科技指数",
        "securities": {first_security: "人工证券名称"},
        "industries": {first_industry: "人工行业名称"},
    }
    saved = client.patch(
        f"/api/v1/reports/{variant['id']}/document",
        json={"version": variant["latest_document"]["version"], "content": content},
    )
    assert saved.status_code == 200, saved.text
    finalized = client.post(
        f"/api/v1/reports/{variant['id']}/finalize",
        json={"version": saved.json()["version"]},
    )
    assert finalized.status_code == 200, finalized.text
    rendered = client.post(
        f"/api/v1/reports/{variant['id']}/renders",
        json={"formats": ["html", "pdf", "docx"]},
        headers={"Idempotency-Key": "zh-hans-render"},
    )
    assert rendered.status_code == 202, rendered.text
    assert [job["status"] for job in rendered.json()] == ["SUCCEEDED"] * 3

    outputs = {}
    for job in rendered.json():
        signed = client.get(f"/api/v1/artifacts/{job['artifact_id']}/download").json()
        response = client.get(signed["download_url"])
        assert "_ZH-HANS_" in response.headers["content-disposition"]
        outputs[job["format"]] = response.content

    html = outputs["html"].decode("utf-8")
    assert 'data-layout-mode="continuous"' in html
    assert '<header class="page-header">' not in html
    assert '<footer class="page-footer">' not in html
    assert "南方东英测试产品" in html
    assert "人工证券名称" in html
    assert "人工行业名称" in html
    assert " million" not in html

    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(outputs["pdf"])
    assert len(pdf) == 4
    pdf_text = "\n".join(page.get_textpage().get_text_range() for page in pdf)
    searchable_text = unicodedata.normalize("NFKC", pdf_text)
    assert "月度回顾" in searchable_text
    assert "人工证券名称" in searchable_text
    assert "公司新闻" in searchable_text
    pdf.close()

    document = Document(io.BytesIO(outputs["docx"]))
    docx_text = "\n".join(
        [paragraph.text for paragraph in document.paragraphs]
        + [cell.text for table in document.tables for row in table.rows for cell in row.cells]
    )
    assert "月度回顾" in docx_text
    assert "人工证券名称" in docx_text
    assert "人工行业名称" in docx_text


def test_language_switch_syncs_module_choices_in_both_directions(client):
    source = create_report(client)
    client.post(
        f"/api/v1/reports/{source['id']}/snapshots",
        json={"source_policy": "GOLDEN_FIXTURE", "mapping_version": "hstech-v1"},
    )
    client.post(f"/api/v1/reports/{source['id']}/calculations")
    source_detail = client.get(f"/api/v1/reports/{source['id']}").json()
    created = client.post(
        f"/api/v1/reports/{source['id']}/language-variants",
        json={
            "language_mode": "ZH_HANS",
            "source_document_version": source_detail["latest_document"]["version"],
        },
    )
    assert created.status_code == 201, created.text
    target_id = created.json()["id"]
    initial_target_snapshot_id = client.get(f"/api/v1/reports/{target_id}").json()["active_snapshot_id"]

    source_detail = client.get(f"/api/v1/reports/{source['id']}").json()
    cleared_returns = client.post(
        f"/api/v1/reports/{source['id']}/datasets/constituent_returns/clear",
        json={"version": source_detail["version"]},
    )
    assert cleared_returns.status_code == 200, cleared_returns.text

    candidate = client.post(f"/api/v1/reports/{source['id']}/news/candidates", json={
        "source_name": "Approved source",
        "source_url": "https://example.test/language-sync",
        "published_at": "2026-06-12T08:30:00+00:00",
        "title": "Selected English headline",
        "summary": "Selected English summary",
        "security_code": "700",
        "ticker": "0700.HK",
        "importance": "HIGH",
    })
    assert candidate.status_code == 201, candidate.text
    source_detail = client.get(f"/api/v1/reports/{source['id']}").json()
    selected = client.put(f"/api/v1/reports/{source['id']}/news", json={
        "version": source_detail["latest_document"]["version"],
        "items": [{"news_item_id": candidate.json()["id"], "position": 0}],
    })
    assert selected.status_code == 200, selected.text
    source_detail = client.get(f"/api/v1/reports/{source['id']}").json()
    source_content = source_detail["latest_document"]["content"]
    source_content["sections"]["month_in_review"]["blocks"] = [{
        "block_id": "summary",
        "type": "rich_text",
        "title": "Monthly Review",
        "content": "<p>English commentary stays English.</p>",
        "x": 2,
        "y": 1,
        "w": 8,
        "h": 4,
        "text_align": "left",
    }]
    source_content["next_rebalancing_date"] = "2026-09-04"
    source_content["next_rebalancing_date_source"] = "MANUAL"
    saved = client.patch(f"/api/v1/reports/{source['id']}/document", json={
        "version": source_detail["latest_document"]["version"],
        "content": source_content,
    })
    assert saved.status_code == 200, saved.text

    source_detail = client.get(f"/api/v1/reports/{source['id']}").json()
    target_detail = client.get(f"/api/v1/reports/{target_id}").json()
    synced = client.post(
        f"/api/v1/reports/{source['id']}/language-variants/{target_id}/sync",
        json={
            "source_document_version": source_detail["latest_document"]["version"],
            "target_document_version": target_detail["latest_document"]["version"],
        },
    )
    assert synced.status_code == 200, synced.text
    target_detail = client.get(f"/api/v1/reports/{target_id}").json()
    target_content = target_detail["latest_document"]["content"]
    assert target_detail["active_snapshot_id"] != initial_target_snapshot_id
    assert [item["news_item_id"] for item in target_content["sections"]["company_news"]] == [candidate.json()["id"]]
    assert target_content["sections"]["month_in_review"]["blocks"][0]["x"] == 2
    assert target_content["sections"]["month_in_review"]["blocks"][0]["content"] == ""
    assert target_content["next_rebalancing_date"] == "2026-09-04"

    cleared = client.put(f"/api/v1/reports/{target_id}/news", json={
        "version": target_detail["latest_document"]["version"],
        "items": [],
    })
    assert cleared.status_code == 200, cleared.text
    target_detail = client.get(f"/api/v1/reports/{target_id}").json()
    target_content = target_detail["latest_document"]["content"]
    target_content["sections"]["month_in_review"]["blocks"][0].update({
        "content": "<p>中文内容保留在中文版。</p>",
        "x": 0,
        "w": 12,
    })
    saved = client.patch(f"/api/v1/reports/{target_id}/document", json={
        "version": target_detail["latest_document"]["version"],
        "content": target_content,
    })
    assert saved.status_code == 200, saved.text

    target_detail = client.get(f"/api/v1/reports/{target_id}").json()
    source_detail = client.get(f"/api/v1/reports/{source['id']}").json()
    synced_back = client.post(
        f"/api/v1/reports/{target_id}/language-variants/{source['id']}/sync",
        json={
            "source_document_version": target_detail["latest_document"]["version"],
            "target_document_version": source_detail["latest_document"]["version"],
        },
    )
    assert synced_back.status_code == 200, synced_back.text
    source_content = client.get(f"/api/v1/reports/{source['id']}").json()["latest_document"]["content"]
    assert source_content["sections"]["company_news"] == []
    assert source_content["sections"]["month_in_review"]["blocks"][0]["x"] == 0
    assert source_content["sections"]["month_in_review"]["blocks"][0]["w"] == 12
    assert source_content["sections"]["month_in_review"]["blocks"][0]["content"] == "<p>English commentary stays English.</p>"


def test_traditional_variant_converts_chinese_editorial_and_preserves_manual_target(client):
    source_response = client.post("/api/v1/reports", json={
        "product_code": "3033",
        "report_date": "2026-06-30",
        "language_mode": "ZH_HANS",
    })
    assert source_response.status_code == 201, source_response.text
    source = client.get(f"/api/v1/reports/{source_response.json()['id']}").json()
    manual_news = client.post(f"/api/v1/reports/{source['id']}/news/candidates", json={
        "source_name": "人工来源",
        "source_url": "https://example.test/manual-chinese-news",
        "published_at": "2026-06-12T08:30:00+00:00",
        "title": "腾讯推出新软件",
        "summary": "公司更新网络服务。",
        "ticker": "0700.HK",
        "importance": "HIGH",
    })
    assert manual_news.status_code == 201, manual_news.text
    selected_news = client.put(f"/api/v1/reports/{source['id']}/news", json={
        "version": source["latest_document"]["version"],
        "items": [{"news_item_id": manual_news.json()["id"], "position": 0}],
    })
    assert selected_news.status_code == 200, selected_news.text
    source = client.get(f"/api/v1/reports/{source['id']}").json()
    source_content = source["latest_document"]["content"]
    source_content["sections"]["month_in_review"]["blocks"] = [{
        "block_id": "summary",
        "type": "rich_text",
        "title": "月度回顾",
        "content": "<p>科技软件与网络。</p>",
        "x": 0,
        "y": 0,
        "w": 12,
        "h": 4,
        "text_align": "left",
    }]
    source_content["sections"]["footnotes"]["historical"] = "历史数据说明。"
    source_content["terminology_overrides"]["product_name"] = "南方东英测试产品"
    saved_source = client.patch(
        f"/api/v1/reports/{source['id']}/document",
        json={"version": source["latest_document"]["version"], "content": source_content},
    )
    assert saved_source.status_code == 200, saved_source.text
    source = client.get(f"/api/v1/reports/{source['id']}").json()

    created = client.post(
        f"/api/v1/reports/{source['id']}/language-variants",
        json={
            "language_mode": "ZH_HANT",
            "source_document_version": source["latest_document"]["version"],
        },
    )
    assert created.status_code == 201, created.text
    target_id = created.json()["id"]
    target = client.get(f"/api/v1/reports/{target_id}").json()
    target_content = target["latest_document"]["content"]
    target_block = target_content["sections"]["month_in_review"]["blocks"][0]
    assert target["language_mode"] == "ZH_HANT"
    assert target_block["title"] == "月度回顧"
    assert target_block["content"] == "<p>科技軟件與網絡。</p>"
    assert target_content["sections"]["footnotes"]["historical"] == simplified_to_traditional("历史数据说明。")
    assert target_content["terminology_overrides"]["product_name"] == "南方東英測試產品"
    assert target_content["sections"]["company_news"][0]["title"] == "騰訊推出新軟件"
    provenance = target_content["translation_provenance"]
    assert provenance["method"] == "CHINESE_VARIANT_SYNC"
    assert provenance["fields"]["sections.month_in_review.blocks.summary.content"]["source_document_version"] == source["latest_document"]["version"]
    assert provenance["fields"][f"sections.company_news.{manual_news.json()['id']}.title_override"]["method"] == "OPENCC_S2T"

    target_news = client.put(f"/api/v1/reports/{target_id}/news", json={
        "version": target["latest_document"]["version"],
        "items": [{
            "news_item_id": manual_news.json()["id"],
            "position": 0,
            "title_override": "人工繁體新聞標題",
        }],
    })
    assert target_news.status_code == 200, target_news.text
    target = client.get(f"/api/v1/reports/{target_id}").json()
    target_content = target["latest_document"]["content"]
    target_block = target_content["sections"]["month_in_review"]["blocks"][0]
    target_block["content"] = "<p>人工繁體內容。</p>"
    saved_target = client.patch(
        f"/api/v1/reports/{target_id}/document",
        json={"version": target["latest_document"]["version"], "content": target_content},
    )
    assert saved_target.status_code == 200, saved_target.text

    source = client.get(f"/api/v1/reports/{source['id']}").json()
    source_news = client.put(f"/api/v1/reports/{source['id']}/news", json={
        "version": source["latest_document"]["version"],
        "items": [{
            "news_item_id": manual_news.json()["id"],
            "position": 0,
            "title_override": "腾讯更新软件",
        }],
    })
    assert source_news.status_code == 200, source_news.text
    source = client.get(f"/api/v1/reports/{source['id']}").json()
    source_content = source["latest_document"]["content"]
    source_block = source_content["sections"]["month_in_review"]["blocks"][0]
    source_block["title"] = "更新月度回顾"
    source_block["content"] = "<p>更新后的软件内容。</p>"
    source_content["sections"]["footnotes"]["historical"] = "更新后的历史数据说明。"
    saved_source = client.patch(
        f"/api/v1/reports/{source['id']}/document",
        json={"version": source["latest_document"]["version"], "content": source_content},
    )
    assert saved_source.status_code == 200, saved_source.text

    source = client.get(f"/api/v1/reports/{source['id']}").json()
    target = client.get(f"/api/v1/reports/{target_id}").json()
    synced = client.post(
        f"/api/v1/reports/{source['id']}/language-variants/{target_id}/sync",
        json={
            "source_document_version": source["latest_document"]["version"],
            "target_document_version": target["latest_document"]["version"],
        },
    )
    assert synced.status_code == 200, synced.text
    target = client.get(f"/api/v1/reports/{target_id}").json()
    target_content = target["latest_document"]["content"]
    target_block = target_content["sections"]["month_in_review"]["blocks"][0]
    assert target_block["title"] == "更新月度回顧"
    assert target_block["content"] == "<p>人工繁體內容。</p>"
    assert target_content["sections"]["company_news"][0]["title"] == "人工繁體新聞標題"
    assert target_content["sections"]["footnotes"]["historical"] == simplified_to_traditional("更新后的历史数据说明。")
    assert "sections.month_in_review.blocks.summary.content" not in target_content["translation_provenance"]["fields"]

    finalized = client.post(
        f"/api/v1/reports/{target_id}/finalize",
        json={"version": target["version"]},
    )
    assert finalized.status_code == 200, finalized.text
    rejected_sync = client.post(
        f"/api/v1/reports/{source['id']}/language-variants/{target_id}/sync",
        json={
            "source_document_version": source["latest_document"]["version"],
            "target_document_version": target["latest_document"]["version"],
        },
    )
    assert rejected_sync.status_code == 409
    assert rejected_sync.json()["error_code"] == "REPORT_FINALIZED"

    preview = client.post(f"/api/v1/reports/{target_id}/preview")
    assert preview.status_code == 200, preview.text
    assert 'lang="zh-HK"' in preview.text
    assert preview.text.count('<header class="page-header">') == 4

    rendered = client.post(
        f"/api/v1/reports/{target_id}/renders",
        json={"formats": ["html", "pdf", "docx"]},
        headers={"Idempotency-Key": "zh-hant-render"},
    )
    assert rendered.status_code == 202, rendered.text
    assert [job["status"] for job in rendered.json()] == ["SUCCEEDED"] * 3
    outputs = {}
    for job in rendered.json():
        signed = client.get(f"/api/v1/artifacts/{job['artifact_id']}/download").json()
        response = client.get(signed["download_url"])
        assert "_ZH-HANT_" in response.headers["content-disposition"]
        outputs[job["format"]] = response.content

    html = outputs["html"].decode("utf-8")
    assert 'lang="zh-HK"' in html
    assert "language-zh-hant" in html
    assert '@font-face{font-family:"Embedded Noto Sans CJK TC"' in html
    assert "人工繁體內容" in html
    assert "公司新聞" in html

    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(outputs["pdf"])
    assert len(pdf) == 4
    pdf.close()
    document = Document(io.BytesIO(outputs["docx"]))
    assert len(document.sections) == 4
    assert document.styles["Normal"].font.name == "Noto Sans CJK TC"
    docx_text = "\n".join(
        [paragraph.text for paragraph in document.paragraphs]
        + [cell.text for table in document.tables for row in table.rows for cell in row.cells]
    )
    assert "人工繁體內容" in docx_text


def test_simplified_variant_converts_traditional_editorial(client):
    source_response = client.post("/api/v1/reports", json={
        "product_code": "3033",
        "report_date": "2026-05-31",
        "language_mode": "ZH_HANT",
    })
    assert source_response.status_code == 201, source_response.text
    source = client.get(f"/api/v1/reports/{source_response.json()['id']}").json()
    content = source["latest_document"]["content"]
    content["sections"]["month_in_review"]["blocks"] = [{
        "block_id": "summary",
        "type": "rich_text",
        "title": "月度回顧",
        "content": "<p>科技軟件與網絡。</p>",
        "x": 0,
        "y": 0,
        "w": 12,
        "h": 4,
        "text_align": "left",
    }]
    saved = client.patch(
        f"/api/v1/reports/{source['id']}/document",
        json={"version": source["latest_document"]["version"], "content": content},
    )
    assert saved.status_code == 200, saved.text
    source = client.get(f"/api/v1/reports/{source['id']}").json()

    created = client.post(
        f"/api/v1/reports/{source['id']}/language-variants",
        json={
            "language_mode": "ZH_HANS",
            "source_document_version": source["latest_document"]["version"],
        },
    )
    assert created.status_code == 201, created.text
    target = client.get(f"/api/v1/reports/{created.json()['id']}").json()
    block = target["latest_document"]["content"]["sections"]["month_in_review"]["blocks"][0]
    assert block["title"] == "月度回顾"
    assert block["content"] == "<p>科技软件与网络。</p>"
    assert target["latest_document"]["content"]["translation_provenance"]["fields"][
        "sections.month_in_review.blocks.summary.content"
    ]["method"] == "OPENCC_T2S"

def test_optimistic_lock_returns_conflict(client):
    report = create_report(client)
    detail = client.get(f"/api/v1/reports/{report['id']}").json()
    content = detail["latest_document"]["content"]
    response = client.patch(f"/api/v1/reports/{report['id']}/document", json={"version": 99, "content": content})
    assert response.status_code == 409
    assert response.json()["error_code"] == "VERSION_CONFLICT"


def test_finalize_allows_missing_snapshot_for_direct_download(client):
    report = create_report(client)
    review = client.get(f"/api/v1/reports/{report['id']}/review")
    assert review.status_code == 200
    assert review.json()["ready"] is False
    assert any(item["check_id"] == "SNAPSHOT_REQUIRED" for item in review.json()["blocking"])

    response = client.post(f"/api/v1/reports/{report['id']}/finalize", json={"version": 1})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "FINALIZED"

    rendered = client.post(
        f"/api/v1/reports/{report['id']}/renders",
        json={"formats": ["html"]},
        headers={"Idempotency-Key": "direct-incomplete-download"},
    )
    assert rendered.status_code == 202, rendered.text
    assert rendered.json()[0]["status"] == "SUCCEEDED"
    assert rendered.json()[0]["artifact_id"]


def test_finalized_report_creates_a_separate_revision(client):
    report = create_report(client)
    client.post(f"/api/v1/reports/{report['id']}/snapshots", json={"source_policy": "GOLDEN_FIXTURE"})
    calculated = client.post(f"/api/v1/reports/{report['id']}/calculations").json()
    client.post(f"/api/v1/reports/{report['id']}/finalize", json={"version": calculated["document_version"]})
    response = client.post(f"/api/v1/reports/{report['id']}/revisions", json={"reason": "Correct approved commentary"})
    assert response.status_code == 201, response.text
    revision = response.json()
    assert revision["id"] != report["id"]
    assert revision["parent_report_id"] == report["id"]
    assert revision["revision"] == 2
    assert revision["status"] == "DRAFT"
    assert client.get(f"/api/v1/reports/{report['id']}").json()["status"] == "FINALIZED"


def test_finalize_treats_missing_calculation_module_snapshots_as_advisory(client):
    report = create_report(client)
    client.post(f"/api/v1/reports/{report['id']}/snapshots", json={"source_policy": "GOLDEN_FIXTURE"})
    response = client.post(f"/api/v1/reports/{report['id']}/finalize", json={"version": 2})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "FINALIZED"
    events = client.get("/api/v1/audit").json()
    finalized = next(item for item in events if item["action"] == "report.finalized" and item["entity_id"] == report["id"])
    assert "CALCULATION_REQUIRED" in finalized["details"]["advisory_check_ids"]


def test_review_uses_the_same_calculation_gate_as_finalize(client):
    report = create_report(client)
    client.post(f"/api/v1/reports/{report['id']}/snapshots", json={"source_policy": "GOLDEN_FIXTURE"})

    review = client.get(f"/api/v1/reports/{report['id']}/review")

    assert review.status_code == 200, review.text
    assert review.json()["ready"] is False
    assert any(item["check_id"] == "CALCULATION_REQUIRED" for item in review.json()["blocking"])
