from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

from app.rendering.visual_qa import verify_pdf


if __name__ == "__main__":
    actual = Path(sys.argv[1]) if len(sys.argv) > 1 else next((ROOT / "output" / "pdf").glob("*.pdf"))
    reference = ROOT / "tests" / "fixtures" / "3033_202606" / "reference.pdf"
    evidence = ROOT / "artifacts" / "visual" / "latest"
    result = verify_pdf(actual, reference, evidence)
    print(f"Visual QA passed={result['passed']}; evidence={evidence / 'manifest.json'}")
    raise SystemExit(0 if result["passed"] else 2)
