from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.rendering.visual_qa import verify_pdf


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare a downloaded PDF with the approved visual baseline.")
    parser.add_argument("pdf", type=Path, help="PDF saved by an on-demand download")
    args = parser.parse_args()
    actual = args.pdf
    if not actual.is_file():
        parser.error("The downloaded PDF does not exist.")
    reference = ROOT / "backend" / "tests" / "fixtures" / "3033_202606" / "reference.pdf"
    evidence = ROOT / "var" / "artifacts" / "visual" / "latest"
    result = verify_pdf(actual, reference, evidence)
    print(f"Visual QA passed={result['passed']}; evidence={evidence / 'manifest.json'}")
    raise SystemExit(0 if result["passed"] else 2)
