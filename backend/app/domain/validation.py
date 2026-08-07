"""Structured validation findings shared by every ingestion parser.

Parsers used to ``raise ValueError`` on the first bad row, so a file with seventeen problems
surfaced one problem per upload attempt. A ``Finding`` is the accumulating alternative: parsing
runs to completion, every problem is reported once, and the caller decides whether the collected
severities are fatal.

The field names match the error contract declared in CLAUDE.md
(``error_code / field / entity_id / message / severity / fix_hint``).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

BLOCKING = "BLOCKING"
WARNING = "WARNING"
INFO = "INFO"

# A malformed file can produce one finding per row; cap the payload so a 50k-row paste cannot
# blow up the response, the JSON column, or the browser table that renders it.
MAX_FINDINGS = 200


@dataclass(frozen=True)
class Finding:
    error_code: str
    severity: str
    message: str
    fix_hint: str
    row: int | None = None
    field: str | None = None
    entity_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class FindingCollector:
    """Accumulates findings during a parse, bounded by ``MAX_FINDINGS``."""

    def __init__(self, limit: int = MAX_FINDINGS) -> None:
        self._limit = limit
        self._findings: list[Finding] = []
        self._suppressed = 0

    def add(
        self,
        error_code: str,
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
                error_code=error_code,
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
            error_code="FINDINGS_TRUNCATED",
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
