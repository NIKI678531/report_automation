"""Versioned 3033 compliance notice used by the continuous HTML reader."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


IMPORTANT_INFORMATION_VERSION = "csop-3033-important-information-v2"
IMPORTANT_INFORMATION_CHECKSUM = "58c9131d84a0492e6e802a63133b29b503699b4b56b49849d548bf91f50279c7"
IMPORTANT_INFORMATION_RESOURCE_PATH = (
    Path(__file__).resolve().parent
    / "resources"
    / f"{IMPORTANT_INFORMATION_VERSION}.json"
)


class ImportantInformationResourceError(RuntimeError):
    """The approved reader notice is missing, malformed, or no longer immutable."""


@dataclass(frozen=True)
class ImportantInformationResource:
    version: str
    product_code: str
    title: str
    paragraphs: tuple[str, ...]
    checksum: str

    def template_context(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "product_code": self.product_code,
            "title": self.title,
            "paragraphs": self.paragraphs,
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
def load_important_information() -> ImportantInformationResource:
    try:
        raw = json.loads(IMPORTANT_INFORMATION_RESOURCE_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ImportantInformationResourceError(
            "The approved important-information resource is unavailable."
        ) from error

    if not isinstance(raw, dict):
        raise ImportantInformationResourceError(
            "The approved important-information resource is invalid."
        )
    version = raw.get("version")
    product_code = raw.get("product_code")
    title = raw.get("title")
    paragraphs = raw.get("paragraphs")
    if (
        version != IMPORTANT_INFORMATION_VERSION
        or product_code != "3033"
        or title != "Key Risks Reminder"
        or not isinstance(paragraphs, list)
        or len(paragraphs) != 3
        or any(not isinstance(paragraph, str) or not paragraph.strip() for paragraph in paragraphs)
    ):
        raise ImportantInformationResourceError(
            "The approved important-information resource is invalid."
        )

    actual_checksum = _canonical_checksum(raw)
    if actual_checksum != IMPORTANT_INFORMATION_CHECKSUM:
        raise ImportantInformationResourceError(
            "The approved important-information resource checksum is invalid."
        )
    return ImportantInformationResource(
        version=version,
        product_code=product_code,
        title=title,
        paragraphs=tuple(paragraphs),
        checksum=actual_checksum,
    )


def important_information_audit_fields(
    product_code: str,
    format_name: str,
) -> dict[str, str]:
    if str(product_code) != "3033" or format_name != "html":
        return {}
    return {
        "important_information_version": IMPORTANT_INFORMATION_VERSION,
        "important_information_checksum": IMPORTANT_INFORMATION_CHECKSUM,
    }
