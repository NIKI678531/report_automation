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
    "Top 10 3033.HK Constituents",
    "3033.HK Sectors Breakdown",
    "Top Performers",
    "Bottom Performers",
    "Portfolio Analysis",
)

PAGE5_REQUIRED_TEXT = (
    "Disclaimer",
    "This document is not for public distribution outside Hong Kong.",
    "For the Index Provider Disclaimer, please refer to the Product’s offering document.",
    "Issuer: CSOP Asset Management Limited",
)

POINTS_PER_MM = 72 / 25.4


def verify_pdf(
    actual_pdf: Path,
    reference_pdf: Path,
    evidence_root: Path,
    *,
    opening_page_count: int = 1,
) -> dict:
    """Verify a paged export, including v4's explicitly-created opening pages.

    The approved reference has the four business pages and predates the appended disclaimer.
    Additional v4 opening pages therefore shift reference pages 2-4 without changing them.
    """

    if not 1 <= opening_page_count <= 96:
        raise ValueError("opening_page_count must be between 1 and 96")
    actual_document = pdfium.PdfDocument(str(actual_pdf))
    reference_document = pdfium.PdfDocument(str(reference_pdf))
    actual_sizes = [[round(page.get_width(), 2), round(page.get_height(), 2)] for page in actual_document]
    reference_sizes = [[round(page.get_width(), 2), round(page.get_height(), 2)] for page in reference_document]
    actual_pages = _render(actual_pdf, evidence_root / "actual-pages")
    reference_pages = _render(reference_pdf, evidence_root / "reference-pages")
    (evidence_root / "diff-pages").mkdir(parents=True, exist_ok=True)
    actual_reference_indexes = [0, opening_page_count, opening_page_count + 1, opening_page_count + 2]
    comparisons = [
        {
            "page": actual_index + 1,
            "reference_page": reference_index + 1,
            **_difference(
                reference_pages[reference_index],
                actual_pages[actual_index],
                evidence_root / "diff-pages" / f"page-{actual_index + 1:02d}.png",
            ),
        }
        for reference_index, actual_index in enumerate(actual_reference_indexes)
        if reference_index < len(reference_pages) and actual_index < len(actual_pages)
    ]
    expected_page_count = opening_page_count + 4
    structural = {
        "page_count": len(actual_document),
        "expected_page_count": expected_page_count,
        "opening_page_count": opening_page_count,
        "page_count_passed": len(actual_document) == expected_page_count,
        "page_sizes": actual_sizes,
        "a4_sizes_passed": all(abs(width - 595.2) <= 1 and abs(height - 841.92) <= 1 for width, height in actual_sizes),
        # The approved visual reference predates the legal fifth page. Keep comparing its four
        # report pages exactly while validating the new page independently below.
        "reference_sizes_match": len(reference_sizes) == 4 and len(actual_sizes) == expected_page_count and all(
            abs(actual_sizes[actual_index][0] - reference_sizes[reference_index][0]) <= 1
            and abs(actual_sizes[actual_index][1] - reference_sizes[reference_index][1]) <= 1
            for reference_index, actual_index in enumerate(actual_reference_indexes)
        ),
    }
    visual_passed = len(comparisons) == len(reference_pages) == 4 and all(page["pixel_difference_ratio"] <= 0.005 for page in comparisons)
    def _page4_content(document: pdfium.PdfDocument, image_path: Path, page_index: int) -> dict:
        if len(document) <= page_index:
            return {"required_text_passed": False, "missing_text": list(PAGE4_REQUIRED_TEXT), "donut_passed": False}
        text = document[page_index].get_textpage().get_text_bounded()
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
    analytics_index = opening_page_count + 2
    disclaimer_index = opening_page_count + 3
    page4_content = (
        _page4_content(actual_document, actual_pages[analytics_index], analytics_index)
        if len(actual_pages) > analytics_index
        else _page4_content(actual_document, Path(), analytics_index)
    )
    page5_text_page = actual_document[disclaimer_index].get_textpage() if len(actual_document) > disclaimer_index else None
    page5_text = page5_text_page.get_text_bounded() if page5_text_page is not None else ""
    disclaimer_start = page5_text.find("Disclaimer")
    disclaimer_end = page5_text.find(PAGE5_REQUIRED_TEXT[-1])
    disclaimer_end = (
        disclaimer_end + len(PAGE5_REQUIRED_TEXT[-1])
        if disclaimer_end >= 0
        else -1
    )
    page5_bounds = None
    page5_safe_area = None
    page5_safe_area_passed = False
    if page5_text_page is not None and disclaimer_start >= 0 and disclaimer_end > disclaimer_start:
        rectangle_count = page5_text_page.count_rects(
            disclaimer_start,
            disclaimer_end - disclaimer_start,
        )
        rectangles = [page5_text_page.get_rect(index) for index in range(rectangle_count)]
        if rectangles:
            page_width = actual_document[disclaimer_index].get_width()
            page_height = actual_document[disclaimer_index].get_height()
            page5_bounds = {
                "left": round(min(rectangle[0] for rectangle in rectangles), 2),
                "bottom": round(min(rectangle[1] for rectangle in rectangles), 2),
                "right": round(max(rectangle[2] for rectangle in rectangles), 2),
                "top": round(max(rectangle[3] for rectangle in rectangles), 2),
            }
            # These limits mirror the paged template's outer content margins and reserve the
            # complete header/footer bands. They intentionally measure only the approved legal
            # copy, excluding the running chrome and TESTING watermark.
            page5_safe_area = {
                "left": round(10 * POINTS_PER_MM, 2),
                "bottom": round(15 * POINTS_PER_MM, 2),
                "right": round(page_width - 8 * POINTS_PER_MM, 2),
                "top": round(page_height - 13 * POINTS_PER_MM, 2),
            }
            tolerance = 1.0
            page5_safe_area_passed = (
                page5_bounds["left"] >= page5_safe_area["left"] - tolerance
                and page5_bounds["bottom"] >= page5_safe_area["bottom"] - tolerance
                and page5_bounds["right"] <= page5_safe_area["right"] + tolerance
                and page5_bounds["top"] <= page5_safe_area["top"] + tolerance
            )
    page5_content = {
        "required_text_passed": all(value in page5_text for value in PAGE5_REQUIRED_TEXT),
        "missing_text": [value for value in PAGE5_REQUIRED_TEXT if value not in page5_text],
        "content_bounds": page5_bounds,
        "safe_area": page5_safe_area,
        "safe_area_passed": page5_safe_area_passed,
    }
    manifest = {
        "schema_version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "actual_pdf": str(actual_pdf.resolve()),
        "reference_pdf": str(reference_pdf.resolve()),
        "thresholds": {"pixel_difference_ratio": 0.005},
        "structural": structural,
        "page4_content": page4_content,
        "page5_content": page5_content,
        "pages": comparisons,
        "visual_passed": visual_passed,
        "passed": structural["page_count_passed"] and structural["a4_sizes_passed"] and structural["reference_sizes_match"] and page4_content["required_text_passed"] and page4_content["donut_passed"] and page5_content["required_text_passed"] and page5_content["safe_area_passed"] and visual_passed,
    }
    evidence_root.mkdir(parents=True, exist_ok=True)
    (evidence_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
