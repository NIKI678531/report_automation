from pathlib import Path

from app.rendering.visual_qa import verify_pdf


def test_reference_pdf_passes_itself(tmp_path):
    reference = Path(__file__).parent / "fixtures" / "3033_202606" / "reference.pdf"
    result = verify_pdf(reference, reference, tmp_path)
    assert result["passed"] is True
    assert result["structural"]["page_count"] == 4
    assert all(item["pixel_difference_ratio"] == 0 for item in result["pages"])
    assert result["page4_content"]["required_text_passed"] is True
    assert result["page4_content"]["donut_passed"] is True
    assert result["page4_content"]["donut_dominant_color_count"] >= 3
