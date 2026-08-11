from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.rendering.visual_qa import verify_pdf


if __name__ == "__main__":
    actual = Path(sys.argv[1]) if len(sys.argv) > 1 else max(
        (ROOT / "var" / "output" / "pdf").glob("*.pdf"),
        key=lambda path: path.stat().st_mtime,
    )
    reference = ROOT / "backend" / "tests" / "fixtures" / "3033_202606" / "reference.pdf"
    evidence = ROOT / "var" / "artifacts" / "visual" / "latest"
    result = verify_pdf(actual, reference, evidence)
    print(f"Visual QA passed={result['passed']}; evidence={evidence / 'manifest.json'}")
    raise SystemExit(0 if result["passed"] else 2)
