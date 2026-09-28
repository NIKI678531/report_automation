"""Versioned, immutable legal disclaimer used by every report renderer.

The resource is deliberately outside ``ReportDocument``. A document may be years old, or may
contain an untrusted field called ``disclaimer``; neither is allowed to select or alter the legal
copy that is current when an artifact is generated.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


DISCLAIMER_VERSION = "csop-hk-professional-investor-v1"
DISCLAIMER_CHECKSUM = "6f41352bc7639c65a2c190aa22bf543b0c0e4d039c753a9c57d9f7c7602423df"
DISCLAIMER_RESOURCE_PATH = (
    Path(__file__).resolve().parent / "resources" / f"{DISCLAIMER_VERSION}.json"
)


class DisclaimerResourceError(RuntimeError):
    """The deployed compliance resource is missing, malformed or no longer immutable."""


@dataclass(frozen=True)
class DisclaimerResource:
    version: str
    title: str
    paragraphs: tuple[str, ...]
    issuer: str
    checksum: str

    def template_context(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "title": self.title,
            "paragraphs": self.paragraphs,
            "issuer": self.issuer,
            "checksum": self.checksum,
        }


def _canonical_checksum(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@lru_cache(maxsize=1)
def load_disclaimer() -> DisclaimerResource:
    """Load and verify the one approved disclaimer resource.

    The expected checksum is compiled into the renderer identity. Updating legal text therefore
    requires an explicit resource version/checksum change instead of silently changing every
    historical report the next time it is downloaded.
    """
    try:
        raw = json.loads(DISCLAIMER_RESOURCE_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DisclaimerResourceError("The approved disclaimer resource is unavailable.") from error

    if not isinstance(raw, dict):
        raise DisclaimerResourceError("The approved disclaimer resource is invalid.")
    version = raw.get("version")
    title = raw.get("title")
    paragraphs = raw.get("paragraphs")
    issuer = raw.get("issuer")
    if (
        version != DISCLAIMER_VERSION
        or not isinstance(title, str)
        or not title.strip()
        or not isinstance(paragraphs, list)
        or len(paragraphs) != 6
        or any(not isinstance(paragraph, str) or not paragraph.strip() for paragraph in paragraphs)
        or not isinstance(issuer, str)
        or not issuer.strip()
    ):
        raise DisclaimerResourceError("The approved disclaimer resource is invalid.")

    actual_checksum = _canonical_checksum(raw)
    if actual_checksum != DISCLAIMER_CHECKSUM:
        raise DisclaimerResourceError("The approved disclaimer resource checksum is invalid.")
    return DisclaimerResource(
        version=version,
        title=title,
        paragraphs=tuple(paragraphs),
        issuer=issuer,
        checksum=actual_checksum,
    )


def disclaimer_audit_fields() -> dict[str, str]:
    """Return stable metadata even when loading the deployed resource later fails."""
    return {
        "disclaimer_version": DISCLAIMER_VERSION,
        "disclaimer_checksum": DISCLAIMER_CHECKSUM,
    }
