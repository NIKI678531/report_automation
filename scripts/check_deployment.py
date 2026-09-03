"""Answer "is this environment fit to serve traffic?" before it serves any.

`create_app()` already refuses to start on an unsafe configuration, but a failed container start
is a poor way to discover that a tenant id is missing: the message arrives in a crash loop, one
problem at a time, on a host nobody is watching. This runs the same checks plus the ones the
application only reaches at first use - the database is actually connectable, its migrations are at
head, the identity provider answers - and prints all of them at once.

    python scripts/check_deployment.py
    python scripts/check_deployment.py --token "$ACCESS_TOKEN"        # also resolve a real token
    python scripts/check_deployment.py --env-file deploy/prod.env     # check another environment

`--env-file` is what makes this usable before a rollout: the production settings live in a file
long before any production process reads them, and every guard below is a pure function of those
settings. A workstation can therefore prove the deployment configuration is clean without being
the deployment.

Exit code 0 means the checks that ran all passed. Nothing here writes, and the token is never
logged.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--token", help="A real access token to resolve. Never logged.")
    parser.add_argument(
        "--env-file",
        help="Check the environment described by this file instead of the current one. Its values "
             "override the process environment, which is the opposite of how the application loads "
             "backend/.env - here the file under test is the subject, not a fallback.",
    )
    parser.add_argument(
        "--skip-network", action="store_true",
        help="Report the identity configuration without contacting the tenant. Ignored with --token.",
    )
    return parser.parse_args()


# Arguments are parsed, and any --env-file applied, before the application is imported: `Settings`
# and the SQLAlchemy engine are both built at import time from os.environ, so loading afterwards
# would check the wrong environment and say nothing about it.
_arguments = _parse_arguments()
if _arguments.env_file:
    from dotenv import load_dotenv

    _env_path = Path(_arguments.env_file).expanduser()
    if not _env_path.is_file():
        raise SystemExit(f"--env-file {_env_path} does not exist.")
    load_dotenv(_env_path, override=True)

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from app.core import entra
from app.core.config import ConfigurationError, DEFAULT_DOWNLOAD_SECRET, settings
from app.core.database import engine
from app.core.entra import TokenError

OK, WARN, FAIL = "  ok  ", " warn ", " FAIL "

_failures = 0
_warnings = 0


def report(status: str, message: str) -> None:
    global _failures, _warnings
    if status is FAIL:
        _failures += 1
    elif status is WARN:
        _warnings += 1
    print(f"[{status}] {message}")


def section(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


# ---------------------------------------------------------------------------------------------
# Configuration - the same list create_app() refuses to start on
# ---------------------------------------------------------------------------------------------


def check_configuration() -> None:
    section(f"Configuration (AUTH_MODE={settings.auth_mode})")
    problems = settings.deployment_problems()
    for problem in problems:
        report(FAIL, problem)
    if not problems:
        report(OK, "No setting would refuse startup.")
    if settings.is_local_auth:
        report(
            WARN,
            "AUTH_MODE=LOCAL trusts X-User-Role / X-User-ID / X-Product-Scope from the caller. "
            "That is a workstation convenience and provides no security; the checks below are "
            "relaxed accordingly.",
        )
    if settings.is_local_auth and settings.download_secret == DEFAULT_DOWNLOAD_SECRET:
        # Outside LOCAL this is already a startup refusal above; saying it twice would inflate the count.
        report(WARN, "DOWNLOAD_SECRET is the public repository default. Harmless locally, fatal anywhere else.")
    report(OK, f"Artifact download links expire after {settings.download_ttl_seconds}s, bound to the requesting subject.")
    report(
        OK,
        f"Upload ceilings: {settings.upload_max_bytes // 1024 // 1024} MiB per file, "
        f"{settings.upload_batch_max_files} files and {settings.upload_batch_max_bytes // 1024 // 1024} MiB per batch. "
        "nginx client_max_body_size must be at least the batch ceiling.",
    )
    if settings.cors_allow_origins:
        report(OK, "CORS origins: " + ", ".join(settings.cors_allow_origins))
    else:
        report(WARN, "CORS_ALLOW_ORIGINS is empty; a browser on another origin cannot read any response.")


# ---------------------------------------------------------------------------------------------
# Database - reachable, MySQL, utf8mb4, and at head
# ---------------------------------------------------------------------------------------------


def check_database() -> None:
    url = make_url(settings.database_url)
    section(f"Database ({url.get_backend_name()}://{url.username or ''}@{url.host or 'local file'}/{url.database or ''})")
    if url.get_backend_name() == "sqlite":
        report(
            WARN if settings.is_local_auth else FAIL,
            "DATABASE_URL points at SQLite. It is a developer convenience: schema legal here is not "
            "always legal on InnoDB, and concurrency and durability do not match what was tested.",
        )
    try:
        with engine.connect() as connection:
            if url.get_backend_name() == "mysql":
                version = connection.execute(text("SELECT VERSION()")).scalar_one()
                report(OK, f"Connected to MySQL {version}.")
                charsets = connection.execute(
                    text(
                        "SELECT DISTINCT character_set_name FROM information_schema.columns "
                        "WHERE table_schema = DATABASE() AND character_set_name IS NOT NULL"
                    )
                ).scalars().all()
                # The legacy three-byte `utf8` silently truncates the Chinese a report is made of.
                wrong = sorted(set(charsets) - {"utf8mb4"})
                if wrong:
                    report(FAIL, f"Columns are not all utf8mb4: {', '.join(wrong)}.")
                elif charsets:
                    report(OK, "Every text column is utf8mb4.")
                if "charset" not in url.query:
                    report(OK, "Connection charset defaults to utf8mb4 (set by app.core.database).")
            else:
                connection.execute(text("SELECT 1"))
                report(OK, "Connected.")
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    except SQLAlchemyError as error:
        report(FAIL, f"Cannot connect or read alembic_version: {type(error).__name__}: {error}")
        return

    config = Config(str(ROOT / "backend" / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend" / "migrations"))
    head = ScriptDirectory.from_config(config).get_current_head()
    if revision is None:
        report(FAIL, f"No migrations have been applied. Run `alembic upgrade head` (head is {head}).")
    elif revision != head:
        report(FAIL, f"Schema is at {revision}, head is {head}. Run `alembic upgrade head`.")
    else:
        report(OK, f"Migrations are at head ({head}).")

    tables = set(inspect(engine).get_table_names())
    missing = {"reports", "report_documents", "data_snapshots", "render_artifacts", "audit_events"} - tables
    if missing:
        report(FAIL, "Core tables missing: " + ", ".join(sorted(missing)))
    else:
        report(OK, f"{len(tables)} tables present.")


# ---------------------------------------------------------------------------------------------
# Identity - PyJWT installed, the tenant answers, and a real token resolves to a real principal
# ---------------------------------------------------------------------------------------------


def check_identity(token: str | None, skip_network: bool) -> None:
    section("Identity")
    if settings.is_local_auth:
        report(WARN, "Skipped: LOCAL mode validates nothing. Set AUTH_MODE=ENTRA to check the tenant.")
        if token:
            report(WARN, "--token ignored in LOCAL mode.")
        return

    try:
        entra.ensure_available()
        report(OK, "PyJWT with cryptography is installed.")
    except Exception as error:  # ImportError surfaced as a TokenError/ConfigurationError
        report(FAIL, f'{error} Install it with: pip install -e "./backend[entra]"')
        return

    report(OK, f"Audience pinned to {settings.entra_audience}.")
    report(OK, f"Issuer pinned to {settings.resolved_entra_issuer}.")
    # An unsafe algorithm list is already a startup refusal in the configuration section above.
    if not [name for name in settings.entra_allowed_algorithms if name.startswith("HS") or name == "NONE"]:
        report(OK, f"Algorithms allowed: {', '.join(settings.entra_allowed_algorithms)}.")
    report(
        OK,
        f"Role claim `{settings.entra_role_claim}`, product scope claim "
        f"`{settings.entra_product_scope_claim or '(none - every token is unrestricted)'}`.",
    )
    if not settings.entra_product_scope_claim:
        report(WARN, "ENTRA_PRODUCT_SCOPE_CLAIM is empty, so every authenticated caller sees every product.")

    if skip_network and not token:
        report(WARN, "JWKS fetch skipped by --skip-network; the tenant has not actually been reached.")
        return
    try:
        document = entra._fetch_jwks()  # the app's own fetch path, size guard and timeout included
    except TokenError as error:
        report(FAIL, f"{error.error_code}: {error.message} {error.fix_hint}")
        return
    keys = document.get("keys", [])
    algorithms = sorted({key.get("alg") for key in keys if key.get("alg")})
    report(OK, f"JWKS reachable: {len(keys)} signing key(s), algorithms {', '.join(algorithms) or 'unspecified'}.")

    if not token:
        report(
            WARN,
            "No token supplied. Re-run with --token \"$ACCESS_TOKEN\" to confirm the directory really "
            "issues the role and product-scope claims this API reads.",
        )
        return
    try:
        identity = entra.verify_bearer_token(token.strip())
    except TokenError as error:
        report(FAIL, f"{error.error_code}: {error.message} {error.fix_hint}")
        return
    report(OK, f"Token accepted. Subject {identity.subject}, role {identity.role}.")
    scope = "*  (unrestricted)" if "*" in identity.product_scope else ", ".join(sorted(identity.product_scope))
    report(OK, f"Product scope: {scope or '(empty)'}")


# ---------------------------------------------------------------------------------------------
# Artifact storage
# ---------------------------------------------------------------------------------------------


def check_storage(skip_network: bool = False) -> None:
    section(f"Artifact storage (STORAGE_BACKEND={settings.storage_backend})")
    try:
        # Imported here rather than at module scope so an unimplemented backend is reported as one
        # finding among the others instead of a traceback before anything has been printed.
        from app.core.storage import LocalObjectStorage, storage
    except ConfigurationError as error:
        report(FAIL, str(error))
        return

    if isinstance(storage, LocalObjectStorage):
        root = storage.root
        if not root.exists():
            report(WARN, f"{root} does not exist yet; it is created on the first render.")
        else:
            probe = root / ".preflight-write-check"
            try:
                probe.write_bytes(b"")
                probe.unlink()
                report(OK, f"{root} is writable.")
            except OSError as error:
                report(FAIL, f"{root} is not writable: {error}")
        report(
            OK if settings.is_local_auth else FAIL,
            "Artifacts are kept on local disk through the filesystem implementation of the "
            "object-storage port. Correct on a workstation; in a deployment with no persistent "
            "volume every artifact is lost on restart and a second replica cannot serve one the "
            "first produced.",
        )
        return

    where = settings.s3_endpoint_url or f"the {settings.s3_region} region"
    prefix = f"{settings.s3_prefix}/" if settings.s3_prefix else "(bucket root)"
    report(OK, f"Artifacts go to bucket {settings.s3_bucket} at {where}, under {prefix}.")
    if not (settings.s3_access_key_id and settings.s3_secret_access_key):
        report(
            WARN,
            "No S3_ACCESS_KEY_ID / S3_SECRET_ACCESS_KEY set. That is correct if the pod assumes a "
            "role; otherwise the first render fails on credentials.",
        )
    if skip_network:
        report(WARN, "Bucket reachability skipped by --skip-network; nothing has actually been stored or read.")
        return
    try:
        storage.client.head_bucket(Bucket=settings.s3_bucket)
        report(OK, "Bucket reachable and the credentials can address it.")
    except ConfigurationError as error:
        report(FAIL, str(error))
    except Exception as error:  # botocore raises vendor-specific subclasses
        report(FAIL, f"Cannot reach the bucket: {type(error).__name__}: {error}")


def main() -> int:
    arguments = _arguments

    check_configuration()
    check_database()
    check_identity(arguments.token, arguments.skip_network)
    check_storage(arguments.skip_network)

    print()
    if _failures:
        print(f"{_failures} blocking problem(s), {_warnings} warning(s). This environment must not serve traffic.")
        return 1
    print(f"No blocking problems. {_warnings} warning(s) to read before go-live.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
