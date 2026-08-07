from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageChops, ImageStat


def _render(pdf_path: Path, destination: Path, scale: float = 2.0) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    document = pdfium.PdfDocument(str(pdf_path))
    paths = []
    for index, page in enumerate(document):
        path = destination / f"page-{index + 1:02d}.png"
        page.render(scale=scale).to_pil().convert("RGB").save(path)
        paths.append(path)
    return paths


def _difference(reference: Path, actual: Path, destination: Path) -> dict:
    expected = Image.open(reference).convert("RGB")
    observed = Image.open(actual).convert("RGB")
    if expected.size != observed.size:
        observed = observed.resize(expected.size)
    diff = ImageChops.difference(expected, observed)
    diff.save(destination)
    stat = ImageStat.Stat(diff)
    mean = sum(stat.mean) / len(stat.mean)
    extrema = diff.convert("L").point(lambda value: 255 if value > 12 else 0)
    different = sum(1 for value in extrema.getdata() if value)
    return {"mean_absolute_error": round(mean / 255, 6), "pixel_difference_ratio": round(different / (expected.width * expected.height), 6)}


def verify_pdf(actual_pdf: Path, reference_pdf: Path, evidence_root: Path) -> dict:
    actual_document = pdfium.PdfDocument(str(actual_pdf))
    reference_document = pdfium.PdfDocument(str(reference_pdf))
    actual_sizes = [[round(page.get_width(), 2), round(page.get_height(), 2)] for page in actual_document]
    reference_sizes = [[round(page.get_width(), 2), round(page.get_height(), 2)] for page in reference_document]
    actual_pages = _render(actual_pdf, evidence_root / "actual-pages")
    reference_pages = _render(reference_pdf, evidence_root / "reference-pages")
    (evidence_root / "diff-pages").mkdir(parents=True, exist_ok=True)
    comparisons = [
        {"page": index + 1, **_difference(reference, actual, evidence_root / "diff-pages" / f"page-{index + 1:02d}.png")}
        for index, (reference, actual) in enumerate(zip(reference_pages, actual_pages))
    ]
    structural = {
        "page_count": len(actual_document),
        "expected_page_count": 4,
        "page_count_passed": len(actual_document) == 4,
        "page_sizes": actual_sizes,
        "a4_sizes_passed": all(abs(width - 595.2) <= 1 and abs(height - 841.92) <= 1 for width, height in actual_sizes),
        "reference_sizes_match": len(actual_sizes) == len(reference_sizes) and all(
            abs(actual[0] - reference[0]) <= 1 and abs(actual[1] - reference[1]) <= 1
            for actual, reference in zip(actual_sizes, reference_sizes)
        ),
    }
    visual_passed = len(comparisons) == 4 and all(page["pixel_difference_ratio"] <= 0.005 for page in comparisons)
    manifest = {
        "schema_version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "actual_pdf": str(actual_pdf.resolve()),
        "reference_pdf": str(reference_pdf.resolve()),
        "thresholds": {"pixel_difference_ratio": 0.005},
        "structural": structural,
        "pages": comparisons,
        "visual_passed": visual_passed,
        "passed": structural["page_count_passed"] and structural["a4_sizes_passed"] and structural["reference_sizes_match"] and visual_passed,
    }
    evidence_root.mkdir(parents=True, exist_ok=True)
    (evidence_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
