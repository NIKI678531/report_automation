"""Apply one complete environment Secret without sourcing shell or printing its contents."""
import argparse
import base64
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
COMMON_KEYS = (
    "DATABASE_URL", "DOWNLOAD_SECRET",
    "DA_REPORT_DATABASE_URL", "DATAWAREHOUSE_MYSQL_HOST",
    "DATAWAREHOUSE_MYSQL_DATABASE", "DATAWAREHOUSE_MYSQL_USERNAME", "DATAWAREHOUSE_MYSQL_PASSWORD",
    "FMP_API_KEY", "TRANSLATION_API_KEY",
)
KEYS_BY_ENVIRONMENT = {
    "prd": COMMON_KEYS,
    "uat": (*COMMON_KEYS[:3], "DA_REPORT_OBJECT_URL", "DA_REPORT_SQLITE_SHA256", *COMMON_KEYS[3:]),
}
REQUIRED = {"DATABASE_URL", "DOWNLOAD_SECRET"}


def build_secret(environment: str, namespace: str, env_file: Path) -> dict:
    if environment not in {"uat", "prd"}:
        raise ValueError("Environment must be uat or prd.")
    if namespace != "ih":
        raise ValueError("This deployment uses the platform namespace ih.")
    keys = KEYS_BY_ENVIRONMENT[environment]
    values = {}
    for line in env_file.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or key not in keys or key in values:
            raise ValueError("Invalid, duplicate or unexpected secret key; values suppressed.")
        # Match Compose raw env_file: no interpolation, shell evaluation or quote removal.
        if value.startswith(("'", '\"')):
            raise ValueError("Use literal KEY=value without surrounding quotes.")
        values[key] = value
    if set(values) != set(keys):
        raise ValueError("Supply every key from .env.<env>.example, including empty optional keys.")
    if any(not values[key].strip() or "replace-me" in values[key].lower() for key in REQUIRED):
        raise ValueError("Fill every required secret from the environment's secret store.")
    if environment == "prd" and (not values["DA_REPORT_DATABASE_URL"].strip() or "replace-me" in values["DA_REPORT_DATABASE_URL"].lower()):
        raise ValueError("Production requires its own DA_REPORT_DATABASE_URL (ADR-0030).")
    if len(values["DOWNLOAD_SECRET"]) < 32:
        raise ValueError("DOWNLOAD_SECRET must contain at least 32 generated characters.")
    base = f"ih-{environment}-remote-fund-cmt-auto"
    return {"apiVersion": "v1", "kind": "Secret", "metadata": {
        "name": f"{base}-srvapp-secret", "namespace": namespace,
        "labels": {"app": base, "component": "srvapp", "env": environment},
    }, "type": "Opaque", "data": {
        key: base64.b64encode(values[key].encode()).decode("ascii") for key in keys
    }}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("environment", choices=("uat", "prd"))
    parser.add_argument("--context", help="Explicit target kubectl context; required unless --check.")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--check", action="store_true", help="Validate locally without contacting Kubernetes.")
    args = parser.parse_args()
    if not args.check and not args.context:
        parser.error("--context is required when applying a Secret.")
    try:
        secret = build_secret(args.environment, "ih", args.env_file or ROOT / f".env.{args.environment}")
    except (ValueError, OSError):
        print("Secret validation failed: check the file, literal format and complete keys; values suppressed.")
        return 1
    if args.check:
        print(f"Validated {len(secret['data'])} keys; no cluster operation performed.")
        return 0
    try:
        result = subprocess.run(
            ["kubectl", "--context", args.context, "--namespace", "ih", "apply", "--server-side",
             "--field-manager=fund-commentary-secrets", "-f", "-"],
            input=json.dumps(secret), text=True, capture_output=True, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        print("Secret apply failed or timed out; values suppressed.")
        return 1
    if result.returncode:
        print("Secret apply failed: check context, RBAC and field ownership; values suppressed.")
        return 1
    print(f"Updated {secret['metadata']['name']}; restart the backend Deployment to use changed values.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
