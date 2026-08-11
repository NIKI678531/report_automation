"""The one finding contract shared by ingestion, industry mapping and the quality gate.

Parsers used to ``raise ValueError`` on the first bad row, so a file with seventeen problems
surfaced one problem per upload attempt. A ``Finding`` is the accumulating alternative: parsing
runs to completion, every problem is reported once, and the caller decides whether the collected
severities are fatal.

Every finding list in this codebase — parser findings, slot overlay findings, industry mapping
findings and ``calculation.quality_checks`` results — uses the same keys:

    check_id / severity / status / message / fix_hint  (+ optional row / field / entity_id)

``check_id`` names the rule that produced the finding. It is deliberately *not* called
``error_code``: ``error_code`` belongs to the HTTP error envelope in CLAUDE.md
(``error_code / field / entity_id / message / severity / fix_hint``), which describes a single
failed request, whereas a finding is one entry in a list of results that may have passed.
``normalize`` is the only place allowed to upgrade a legacy row that still says ``error_code`` or
omits ``status``; nothing else may guess with ``.get("status", "FAILED")``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

BLOCKING = "BLOCKING"
WARNING = "WARNING"
INFO = "INFO"

PASSED = "PASSED"
FAILED = "FAILED"

# A malformed file can produce one finding per row; cap the payload so a 50k-row paste cannot
# blow up the response, the JSON column, or the browser table that renders it.
MAX_FINDINGS = 200


@dataclass(frozen=True)
class Finding:
    check_id: str
    severity: str
    message: str
    fix_hint: str
    status: str = FAILED
    row: int | None = None
    field: str | None = None
    entity_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize(items: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Bring stored findings onto the current contract.

    Snapshots written before the contract was unified carry ``error_code`` and no ``status``.
    They are immutable, so they are upgraded on read here — in one place — rather than by every
    consumer defaulting on its own.
    """
    normalized: list[dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        result = {key: value for key, value in item.items() if key != "error_code"}
        result["check_id"] = item.get("check_id") or item.get("error_code") or "UNKNOWN"
        result["severity"] = item.get("severity") or BLOCKING
        result["status"] = item.get("status") or FAILED
        result.setdefault("message", "")
        result.setdefault("fix_hint", "")
        normalized.append(result)
    return normalized


def is_blocking(item: dict[str, Any]) -> bool:
    """True when a normalized finding must stop the workflow."""
    return item.get("severity") == BLOCKING and item.get("status") != PASSED


def blocking_findings(items: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [item for item in normalize(items) if is_blocking(item)]


def counts(items: Iterable[dict[str, Any]] | None) -> dict[str, int]:
    normalized = normalize(items)
    unresolved = [item for item in normalized if item["status"] != PASSED]
    return {
        "blocking": len([item for item in unresolved if item["severity"] == BLOCKING]),
        "warnings": len([item for item in unresolved if item["severity"] == WARNING]),
        "info": len([item for item in unresolved if item["severity"] == INFO]),
    }


class FindingCollector:
    """Accumulates findings during a parse, bounded by ``MAX_FINDINGS``."""

    def __init__(self, limit: int = MAX_FINDINGS) -> None:
        self._limit = limit
        self._findings: list[Finding] = []
        self._suppressed = 0

    def add(
        self,
        check_id: str,
        message: str,
        *,
        severity: str = BLOCKING,
        fix_hint: str = "",
        row: int | None = None,
        field: str | None = None,
        entity_id: str | None = None,
    ) -> None:
        if len(self._findings) >= self._limit:
            self._suppressed += 1
            return
        self._findings.append(
            Finding(
                check_id=check_id,
                severity=severity,
                message=message,
                fix_hint=fix_hint,
                row=row,
                field=field,
                entity_id=entity_id,
            )
        )

    def extend(self, findings: Iterable[Finding]) -> None:
        for finding in findings:
            if len(self._findings) >= self._limit:
                self._suppressed += 1
                continue
            self._findings.append(finding)

    @property
    def findings(self) -> list[Finding]:
        if not self._suppressed:
            return list(self._findings)
        truncated = Finding(
            check_id="FINDINGS_TRUNCATED",
            severity=INFO,
            message=f"{self._suppressed} further findings were suppressed after the first {self._limit}.",
            fix_hint="Fix the reported problems and upload again to see the remainder.",
        )
        return [*self._findings, truncated]

    @property
    def blocking(self) -> list[Finding]:
        return [item for item in self._findings if item.severity == BLOCKING]

    @property
    def warnings(self) -> list[Finding]:
        return [item for item in self._findings if item.severity == WARNING]

    def has_blocking(self) -> bool:
        return any(item.severity == BLOCKING for item in self._findings)

    def summary(self) -> dict[str, int]:
        return {
            "blocking": len(self.blocking),
            "warnings": len(self.warnings),
            "info": len([item for item in self._findings if item.severity == INFO]),
        }

    def as_dicts(self) -> list[dict[str, Any]]:
        return [item.as_dict() for item in self.findings]
