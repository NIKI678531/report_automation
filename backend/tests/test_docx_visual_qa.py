from datetime import date
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from app.domain.document import initial_document
from app.rendering.artifacts import _render_file, render_docx
from app.rendering.visual_qa import verify_cross_format_pdf


def _report() -> SimpleNamespace:
    return SimpleNamespace(
        report_date=date(2026, 6, 30),
        language_mode="EN",
        product_name="CSOP Hang Seng TECH Index ETF",
        product_code="3033",
        benchmark_code="HSTECH",
    )


def _content() -> dict:
    content = initial_document(
        "word-visual-qa",
        date(2026, 6, 30),
        "3033-v5",
        "3033-v5",
        "3033.HK",
        "Hang Seng TECH Index",
        "EN",
    )
    copy = {
        "summary": "Technology shares advanced during the month as sentiment improved.",
        "drivers": "Earnings expectations and liquidity supported the largest constituents.",
        "monitor": "Investors continue to monitor rates, currencies and market volatility.",
        "outlook": "The portfolio remains focused on the Hang Seng TECH Index methodology.",
    }
    for block in content["sections"]["month_in_review"]["blocks"]:
        block["content"] = f"<p>{copy[block['block_id']]}</p>"
    content["sections"]["historical_performance"]["rows"] = [
        {
            "name": "3033.HK",
            "return_1m": "0.0123",
            "return_3m": "0.0456",
            "return_6m": "0.0789",
            "return_ytd": "0.1011",
        },
        {
            "name": "HSTECH Index",
            "return_1m": "0.0119",
            "return_3m": "0.0448",
            "return_6m": "0.0775",
            "return_ytd": "0.0998",
        },
    ]
    content["sections"]["footnotes"]["historical"] = (
        "Source: CSOP. Past performance is not indicative of future performance."
    )
    return content


def test_docx_renderer_stays_within_the_canonical_paged_pdf(tmp_path: Path):
    office = shutil.which("libreoffice") or shutil.which("soffice")
    if office is None:
        pytest.skip("LibreOffice is required for the automated DOCX layout guard.")

    content = _content()
    canonical_pdf = tmp_path / "canonical.pdf"
    docx = tmp_path / "report.docx"
    _render_file(_report(), SimpleNamespace(content=content), "pdf", canonical_pdf)
    render_docx(_report(), content, docx)

    converted = tmp_path / "converted"
    converted.mkdir()
    profile = tmp_path / "libreoffice-profile"
    subprocess.run(
        [
            office,
            f"-env:UserInstallation={profile.resolve().as_uri()}",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(converted),
            str(docx),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    word_pdf = converted / "report.pdf"
    assert word_pdf.is_file()

    result = verify_cross_format_pdf(
        canonical_pdf,
        word_pdf,
        tmp_path / "word-visual-evidence",
    )

    assert result["structural"]["page_count_passed"] is True
    assert result["structural"]["canonical_a4_passed"] is True
    assert result["structural"]["word_a4_passed"] is True
    assert result["visual_passed"] is True
