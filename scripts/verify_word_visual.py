from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.rendering.visual_qa import verify_cross_format_pdf


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Compare a canonical downloaded PDF with a PDF saved from the matching DOCX in "
            "Microsoft Word."
        )
    )
    parser.add_argument("canonical_pdf", type=Path)
    parser.add_argument("word_pdf", type=Path)
    parser.add_argument("--threshold", type=float, default=0.23)
    parser.add_argument("--mean-threshold", type=float, default=0.11)
    args = parser.parse_args()
    for candidate in (args.canonical_pdf, args.word_pdf):
        if not candidate.is_file():
            parser.error(f"The PDF does not exist: {candidate}")
    evidence = ROOT / "var" / "artifacts" / "visual" / "word-latest"
    result = verify_cross_format_pdf(
        args.canonical_pdf,
        args.word_pdf,
        evidence,
        max_pixel_difference_ratio=args.threshold,
        max_mean_absolute_error=args.mean_threshold,
    )
    print(f"Word visual QA passed={result['passed']}; evidence={evidence / 'manifest.json'}")
    raise SystemExit(0 if result["passed"] else 2)
