import argparse
import base64
import json
from pathlib import Path
import re
import subprocess

from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parent
REQUIRED = {"DATABASE_URL", "REDIS_URL", "DOWNLOAD_SECRET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"}


def build_secret(environment: str, namespace: str, env_file: Path) -> dict:
    if environment not in {"uat", "prd"}:
        raise ValueError("Environment must be uat or prd.")
    if not re.fullmatch(r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?", namespace) or "replace-me" in namespace:
        raise ValueError("Supply the namespace confirmed by the platform team.")
    if not env_file.is_file():
        raise ValueError("The environment secret file does not exist.")
    expected = set(dotenv_values(ROOT / environment / ".env.example", interpolate=False))
    values = dotenv_values(env_file, interpolate=False)
    if set(values) != expected:
        raise ValueError("Secret keys must exactly match the environment template, including optional keys.")
    if any(not values.get(key) or "replace-me" in values[key].lower() for key in REQUIRED):
        raise ValueError("Required secret values must be filled from the approved secret store.")
    if any(value is None for value in values.values()):
        raise ValueError("Each key must have an equals sign; unused optional values may be empty.")
    if len(values["DOWNLOAD_SECRET"]) < 32:
        raise ValueError("DOWNLOAD_SECRET must contain at least 32 generated characters.")
    base = f"ih-{environment}-remote-fund-cmt-auto"
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": f"{base}-srvapp-secret",
            "namespace": namespace,
            "labels": {"app": base, "component": "srvapp", "env": environment},
        },
        "type": "Opaque",
        "data": {key: base64.b64encode(value.encode("utf-8")).decode("ascii") for key, value in values.items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and apply one complete environment Secret without printing values.")
    parser.add_argument("environment", choices=("uat", "prd"))
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--check", action="store_true", help="Validate locally; do not contact Kubernetes.")
    arguments = parser.parse_args()
    try:
        secret = build_secret(arguments.environment, arguments.namespace, arguments.env_file)
    except ValueError as error:
        parser.exit(1, f"{error}\n")
    if arguments.check:
        print(f"Validated {len(secret['data'])} secret keys; no cluster operation performed.")
        return 0
    result = subprocess.run(
        ["kubectl", "--context", arguments.context, "--namespace", arguments.namespace,
         "apply", "--server-side", "--field-manager=fund-commentary-secrets", "-f", "-"],
        input=json.dumps(secret), text=True, capture_output=True, timeout=60,
    )
    if result.returncode:
        print("Secret apply failed. Ask the platform team to verify context, namespace, RBAC and field ownership; values were not printed.")
        return 1
    print(f"Updated {secret['metadata']['name']} in {arguments.namespace}. Restart backend pods after an approved configuration change.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())