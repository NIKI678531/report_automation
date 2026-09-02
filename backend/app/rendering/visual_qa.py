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

PAGE4_REQUIRED_TEXT = (
    "Top 10 Index Constituents",
    "Index Sectors Breakdown",
    "Top Performers",
    "Bottom Performers",
    "Portfolio Analysis",
)

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
    def _page4_content(document: pdfium.PdfDocument, image_path: Path) -> dict:
        if len(document) < 4:
            return {"required_text_passed": False, "missing_text": list(PAGE4_REQUIRED_TEXT), "donut_passed": False}
        text = document[3].get_textpage().get_text_bounded()
        missing_text = [value for value in PAGE4_REQUIRED_TEXT if value not in text]
        image = Image.open(image_path).convert("RGB")
        width, height = image.size
        roi = image.crop((int(width * 0.60), int(height * 0.10), int(width * 0.87), int(height * 0.29)))
        colored: list[tuple[int, int, tuple[int, int, int]]] = []
        color_bins: dict[tuple[int, int, int], int] = {}
        nonwhite = 0
        for y in range(roi.height):
            for x in range(roi.width):
                red, green, blue = roi.getpixel((x, y))
                if min(red, green, blue) < 245:
                    nonwhite += 1
                if max(red, green, blue) - min(red, green, blue) >= 35 and min(red, green, blue) < 220:
                    colored.append((x, y, (red, green, blue)))
                    bucket = (red // 32, green // 32, blue // 32)
                    color_bins[bucket] = color_bins.get(bucket, 0) + 1
        nonwhite_ratio = nonwhite / (roi.width * roi.height)
        dominant_colors = len([count for count in color_bins.values() if count >= 40])
        center_white_ratio = 0.0
        if colored:
            left = min(item[0] for item in colored)
            right = max(item[0] for item in colored)
            top = min(item[1] for item in colored)
            bottom = max(item[1] for item in colored)
            center_x = (left + right) // 2
            center_y = (top + bottom) // 2
            half_size = max(4, int(min(right - left, bottom - top) * 0.12))
            center = roi.crop((center_x - half_size, center_y - half_size, center_x + half_size, center_y + half_size))
            white = sum(1 for red, green, blue in center.getdata() if min(red, green, blue) >= 245)
            center_white_ratio = white / max(center.width * center.height, 1)
        donut_passed = nonwhite_ratio >= 0.08 and dominant_colors >= 3 and center_white_ratio >= 0.80
        return {
            "required_text_passed": not missing_text,
            "missing_text": missing_text,
            "donut_passed": donut_passed,
            "donut_roi_nonwhite_ratio": round(nonwhite_ratio, 6),
            "donut_dominant_color_count": dominant_colors,
            "donut_center_white_ratio": round(center_white_ratio, 6),
        }
    page4_content = _page4_content(actual_document, actual_pages[3]) if len(actual_pages) >= 4 else _page4_content(actual_document, Path())
    manifest = {
        "schema_version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "actual_pdf": str(actual_pdf.resolve()),
        "reference_pdf": str(reference_pdf.resolve()),
        "thresholds": {"pixel_difference_ratio": 0.005},
        "structural": structural,
        "page4_content": page4_content,
        "pages": comparisons,
        "visual_passed": visual_passed,
        "passed": structural["page_count_passed"] and structural["a4_sizes_passed"] and structural["reference_sizes_match"] and page4_content["required_text_passed"] and page4_content["donut_passed"] and visual_passed,
    }
    evidence_root.mkdir(parents=True, exist_ok=True)
    (evidence_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
