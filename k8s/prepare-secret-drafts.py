import argparse
import os
from pathlib import Path
import re
import secrets
from urllib.parse import parse_qs, urlsplit

from dotenv import dotenv_values
import yaml


ROOT = Path(__file__).resolve().parent.parent
CORE_KEYS = {"DATABASE_URL", "REDIS_URL", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"}


def acceptable(key: str, value: str | None) -> bool:
    if not value or not value.strip():
        return False
    if any(marker in value.lower() for marker in ("replace-me", "replace_with", "replace-with", "example.invalid", "${")):
        return False
    if key in {"DATABASE_URL", "REDIS_URL", "DA_REPORT_OBJECT_URL"}:
        try:
            url = urlsplit(value)
            if not url.hostname or url.hostname.lower() in {"localhost", "127.0.0.1", "::1", "db", "redis"}:
                return False
            if key == "DATABASE_URL":
                return url.scheme == "mysql+pymysql" and parse_qs(url.query).get("charset") == ["utf8mb4"]
            if key == "REDIS_URL":
                return url.scheme in {"redis", "rediss"}
            return url.scheme == "https"
        except ValueError:
            return False
    if key == "DA_REPORT_SQLITE_SHA256":
        return re.fullmatch(r"[0-9a-fA-F]{64}", value) is not None
    return True


def build_drafts(root: Path, namespace: str) -> tuple[dict, dict]:
    if not re.fullmatch(r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?", namespace) or "replace-me" in namespace:
        raise ValueError("A confirmed namespace is required.")
    documents = {}
    statuses = {}
    for environment in ("uat", "prd"):
        template = root / "k8s" / environment / "secret.example.yaml.txt"
        document = yaml.safe_load(template.read_text(encoding="utf-8"))
        if document["metadata"]["name"] != f"ih-{environment}-remote-fund-cmt-auto-srvapp-secret":
            raise ValueError("Unexpected secret template identity.")
        document["metadata"]["namespace"] = namespace
        document["metadata"]["annotations"] = {"fund-commentary/configuration-status": "draft-not-approved"}
        candidates = ["backend/.env", ".env"] if environment == "uat" else []
        candidates.extend([f"backend/.env.{environment}", f".env.{environment}", f"k8s/{environment}/.env.secrets"])
        values = {}
        sources = {}
        for relative in candidates:
            source = root / relative
            if source.is_file():
                for key, value in dotenv_values(source, interpolate=False).items():
                    if key in document["stringData"]:
                        values[key] = value
                        sources[key] = relative
        statuses[environment] = {}
        for key in document["stringData"]:
            if key == "DOWNLOAD_SECRET":
                document["stringData"][key] = secrets.token_urlsafe(48)
                statuses[environment][key] = "GENERATED_INDEPENDENTLY"
            elif acceptable(key, values.get(key)):
                document["stringData"][key] = values[key]
                statuses[environment][key] = f"COPIED_UNVERIFIED: {sources[key]}"
            else:
                document["stringData"][key] = ""
                statuses[environment][key] = "MISSING_CORE" if key in CORE_KEYS else "MISSING_PROVIDER_OR_OPTIONAL"
                if values.get(key):
                    statuses[environment][key] += " (local value unsuitable for cluster)"
        documents[environment] = document
    return documents, statuses


def write_drafts(root: Path, namespace: str) -> dict:
    paths = {environment: root / "k8s" / environment / "secrets" / "secret.local.yaml" for environment in ("uat", "prd")}
    report_path = root / "k8s" / "secret-readiness.local.md"
    if any(path.exists() for path in [*paths.values(), report_path]):
        raise ValueError("Drafts already exist; refusing to overwrite credentials or rotate signing keys.")
    documents, statuses = build_drafts(root, namespace)
    lines = [
        "# Local Secret Readiness",
        "",
        "DRAFT ONLY: do not apply until the missing settings and environment permissions are approved.",
        "Generic local settings are candidates for UAT only. PRD reads only PRD-specific sources.",
        "Copied values have not been validated against live services; no secret values appear in this report.",
        "The two DOWNLOAD_SECRET values were newly generated, not rotated in any running service.",
        "Do not replace an established environment signing key without an approved rotation plan.",
        "",
    ]
    for environment, fields in statuses.items():
        lines.extend([f"## {environment.upper()}", "", "| Key | Status |", "| --- | --- |"])
        lines.extend(f"| {key} | {status} |" for key, status in fields.items())
        lines.append("")
    lines.extend([
        "## Outside the Secret",
        "",
        "Confirm ConfigMap ENTRA_TENANT_ID, ENTRA_AUDIENCE, CORS_ALLOW_ORIGINS, S3_BUCKET, S3_ENDPOINT_URL and S3_REGION.",
        "Confirm frontend SERVER_NAME, release image tags, Ingress host and the account-specific ACM certificate.",
        "Local SQLite paths do not replace an external MySQL application database or an HTTPS DA-Report snapshot.",
        "With NEWS_PROVIDER=DA_REPORT, MARKETAUX_API_KEY may remain empty; FMP/CDB/DA-Report are required for their enabled workflows.",
        "Both YAML files contain sensitive plaintext. They are gitignored, not encrypted; never share their contents in chat or commits.",
    ])
    contents = {paths[environment]: yaml.safe_dump(document, allow_unicode=False, sort_keys=False) for environment, document in documents.items()}
    contents[report_path] = "\n".join(lines) + "\n"
    for path, content in contents.items():
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write(content)
    return statuses


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare ignored local UAT/PRD Secret drafts; never contact a cluster or print values.")
    parser.add_argument("--namespace", required=True)
    arguments = parser.parse_args()
    try:
        statuses = write_drafts(ROOT, arguments.namespace)
    except (ValueError, OSError, yaml.YAMLError):
        print("Draft generation stopped. Check namespace, templates, permissions and existing output files; values suppressed.")
        return 1
    for environment, fields in statuses.items():
        print(f"{environment}: wrote ignored secrets/secret.local.yaml (DRAFT ONLY)")
        for key, status in fields.items():
            print(f"  {key}: {status}")
    print("Read k8s/secret-readiness.local.md for the missing settings. No cluster operation performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())