"""Visual regression anchor for the canonical four-page output.

This suite renders the *actual* PDF from the golden fixture and compares it with the
supplied reference. It deliberately does not compare the reference with itself: that
earlier shape passed unconditionally and could never observe a rendering regression.
"""
from pathlib import Path

import pypdfium2 as pdfium

from app.rendering.visual_qa import verify_pdf

REFERENCE = Path(__file__).parent / "fixtures" / "3033_202606" / "reference.pdf"

# Recorded baselines, not targets. The specification asks for <= 0.5%; the current output
# is far from that (see docs/implementation-status.md). Asserting "never worse than the
# recorded value" is what turns this suite red on a regression while staying honest about
# the gap that remains. Measured from this exact deterministic path -- do not copy numbers
# from a hand-edited document version.
PIXEL_DIFFERENCE_BASELINE = {1: 0.266693, 2: 0.212917, 3: 0.162226, 4: 0.105307}

# A ratchet only works in one direction, so every raise is recorded with its cause. Editing a
# number here without adding an entry is how a real regression gets absorbed silently.
BASELINE_RAISES = [
    {
        "date": "2026-08-12",
        "previous": {1: 0.266646, 2: 0.212917, 3: 0.160804, 4: 0.105307},
        "reason": (
            "Phase 0.3 fixture split. Two footnotes now say something different because they are "
            "generated rather than transcribed. Page 1: the historical footnote names its source, "
            "and that source is now labelled SYNTHETIC_BACK_SOLVED instead of GOLDEN_FIXTURE, "
            "because the series is back-solved from the reference report's own returns and saying "
            "so is the point. Page 3: the constituents footnote used to be a sentence copied out "
            "of reference.pdf that the payload carried as if it were input; it is now built by "
            "build_lineage_footnotes from the fixture's real dataset lineage, so it names "
            "HSTECH_eod_con_20260630.csv and the HSICS version instead. Both pages move away from "
            "the reference wording on purpose -- the reference is a report, not a lineage record."
        ),
    },
    {
        "date": "2026-08-12",
        "previous": {1: 0.256911, 2: 0.202090, 3: 0.146989, 4: 0.092542},
        "reason": (
            "Phase 0.1 TESTING lane. The golden fixture is transcribed from the approved report "
            "rather than derived from a source system, so it now binds on the TESTING lane and "
            "every page renders the watermark and corner chip. The reference PDF carries neither, "
            "so the mark itself counts as difference. The marked pixels are the mark, not a "
            "rendering regression."
        ),
    },
]

# The reference prints sector weights as on-chart data labels with one decimal place.
PAGE4_REQUIRED_LABELS = ("47.8%", "49.3%", "1.7%", "1.3%")


def render_golden_pdf(client, destination: Path) -> Path:
    """Drive the real lifecycle to a finalized PDF and return its path on disk."""
    report = client.post(
        "/api/v1/reports",
        json={"report_date": "2026-06-30"},
        headers={"X-Request-ID": "visual-qa"},
    ).json()
    snapshot = client.post(
        f"/api/v1/reports/{report['id']}/snapshots",
        json={"source_policy": "GOLDEN_FIXTURE", "mapping_version": "hstech-v1"},
    )
    assert snapshot.status_code == 201, snapshot.text
    calculated = client.post(f"/api/v1/reports/{report['id']}/calculations")
    assert calculated.status_code == 200, calculated.text

    detail = client.get(f"/api/v1/reports/{report['id']}").json()
    finalized = client.post(
        f"/api/v1/reports/{report['id']}/finalize",
        json={"version": detail["version"]},
    )
    assert finalized.status_code == 200, finalized.text

    rendered = client.post(
        f"/api/v1/reports/{report['id']}/renders",
        json={"formats": ["pdf"]},
        headers={"Idempotency-Key": "visual-qa-render"},
    )
    assert rendered.status_code == 202, rendered.text
    job = rendered.json()[0]
    assert job["status"] == "SUCCEEDED", job

    signed = client.get(f"/api/v1/artifacts/{job['artifact_id']}/download").json()
    download = client.get(signed["download_url"])
    assert download.status_code == 200

    destination.write_bytes(download.content)
    return destination


def test_actual_pdf_holds_the_reference_structure(client, tmp_path):
    actual = render_golden_pdf(client, tmp_path / "actual.pdf")
    result = verify_pdf(actual, REFERENCE, tmp_path / "evidence")

    structural = result["structural"]
    assert structural["page_count"] == 4
    assert structural["a4_sizes_passed"] is True
    assert structural["reference_sizes_match"] is True
    assert result["page4_content"]["required_text_passed"] is True
    assert result["page4_content"]["donut_passed"] is True
    assert result["page4_content"]["donut_dominant_color_count"] >= 3


def test_pixel_difference_does_not_regress(client, tmp_path):
    actual = render_golden_pdf(client, tmp_path / "actual.pdf")
    result = verify_pdf(actual, REFERENCE, tmp_path / "evidence")

    for page in result["pages"]:
        baseline = PIXEL_DIFFERENCE_BASELINE[page["page"]]
        assert page["pixel_difference_ratio"] <= baseline + 1e-6, (
            f"page {page['page']} regressed: {page['pixel_difference_ratio']} > {baseline}"
        )


def test_page4_prints_sector_weights_as_on_chart_labels(client, tmp_path):
    """The reference labels the ring itself; the legend carries names only."""
    actual = render_golden_pdf(client, tmp_path / "actual.pdf")
    text = pdfium.PdfDocument(str(actual))[3].get_textpage().get_text_bounded()

    missing = [label for label in PAGE4_REQUIRED_LABELS if label not in text]
    assert not missing, f"page 4 is missing sector data labels: {missing}"
    # Two decimals belong to the return and price columns, never to the sector breakdown.
    assert "47.75%" not in text
    assert "49.27%" not in text
