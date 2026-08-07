from pathlib import Path

from app.rendering.visual_qa import verify_pdf


def test_reference_pdf_passes_itself(tmp_path):
    reference = Path(__file__).parents[1] / "fixtures" / "3033_202606" / "reference.pdf"
    result = verify_pdf(reference, reference, tmp_path)
    assert result["passed"] is True
    assert result["structural"]["page_count"] == 4
    assert all(item["pixel_difference_ratio"] == 0 for item in result["pages"])
