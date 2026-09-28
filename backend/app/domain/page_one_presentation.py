"""Canonical page-one presentation model.

The editor, HTML renderer and DOCX renderer all need the same answer to three questions:
which page-one elements exist, how their twelve-column topology is ordered, and which small set
of typography controls is legal.  Keeping those rules behind this module's small interface avoids
letting each caller grow a slightly different interpretation of the document JSON.

``row``/``row_span`` describe ordering and adjacency only.  They deliberately do not represent a
physical height; renderers remain content-driven as required by ADR-0025.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from html import escape
import re
from typing import Any, Mapping


PRESENTATION_SCHEMA_VERSION = 1
PAGE_COLUMNS = 12
MAX_ROW = 200
MAX_ROW_SPAN = 40
MIN_VERTICAL_NUDGE_STEPS = -200
MAX_VERTICAL_NUDGE_STEPS = 200
MIN_FOOTNOTE_BOTTOM_NUDGE_STEPS = -3
MAX_FOOTNOTE_BOTTOM_NUDGE_STEPS = 4

REVIEW_FONT_SIZE_ROLES = frozenset({"review-10", "review-11"})
HISTORICAL_TABLE_FONT_SIZE_ROLES = frozenset({"history-9", "history-10", "history-11"})
FOOTNOTE_FONT_SIZE_ROLES = frozenset({"footnote-8", "footnote-9", "footnote-10"})
LINE_HEIGHT_ROLES = frozenset({"1.0", "1.2", "1.4"})
TEXT_ALIGNMENTS = frozenset({"left", "center", "right", "justify"})

HISTORICAL_PERFORMANCE_ID = "historical_performance"
HISTORICAL_FOOTNOTE_ID = "footnote:historical"
REVIEW_ID_PREFIX = "review:"

_BASE_ELEMENT_KEYS = frozenset({
    "id", "row", "row_span", "x", "w", "vertical_nudge_steps",
})
_HISTORICAL_ELEMENT_KEYS = _BASE_ELEMENT_KEYS | {
    "table_font_size_role", "table_line_height_role",
}
_FOOTNOTE_ELEMENT_KEYS = _BASE_ELEMENT_KEYS | {"bottom_nudge_steps", "paragraph_styles"}
_PARAGRAPH_STYLE_KEYS = frozenset({
    "paragraph_index", "font_size_role", "line_height_role", "text_align",
})


@dataclass(frozen=True)
class PageOnePresentationError(ValueError):
    """A structured error suitable for the shared HTTP error envelope."""

    message: str
    field: str = "presentation.page_one"
    entity_id: str | None = None
    error_code: str = "PAGE_ONE_PRESENTATION_INVALID"
    fix_hint: str = (
        "Keep page-one elements in the 12-column flow, use supported style roles, and do not "
        "overlap layout rectangles."
    )

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class PageOneLayoutOverflowError(ValueError):
    """Raised by render adapters after measuring content against page one's safe area."""

    findings: tuple[Mapping[str, Any], ...]
    error_code: str = "PAGE_ONE_LAYOUT_OVERFLOW"
    fix_hint: str = (
        "Shorten page-one content or move blocks upward until the preview no longer enters the "
        "footer safe area."
    )

    def __str__(self) -> str:
        return "Page-one content enters the footer safe area."


def _int(value: Any, *, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PageOnePresentationError(f"{field} must be an integer.", field)
    normalized = value
    if not minimum <= normalized <= maximum:
        raise PageOnePresentationError(
            f"{field} must be between {minimum} and {maximum}.", field
        )
    return normalized


def _paragraph_count(value: object) -> int:
    text = str(value or "").replace("\r\n", "\n")
    return max(1, len([part for part in re.split(r"\n\s*\n", text) if part.strip()]))


def _default_footnote_styles(count: int) -> list[dict[str, Any]]:
    return [
        {
            "paragraph_index": index,
            "font_size_role": "footnote-8",
            "line_height_role": "1.2",
            "text_align": "left",
        }
        for index in range(count)
    ]


def _legacy_review_blocks(content: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Lift the four fixed legacy Review modules into the v3 block contract.

    A newly-created v2 document has only ``summary/drivers/monitor/outlook``.  Returning a
    presentation without matching Review elements leaves the browser adapter to invent them and
    can put them on top of the provisionally placed table.  The domain adapter owns this conversion
    so API clients and every renderer see the same complete topology.
    """

    review = ((content.get("sections") or {}).get("month_in_review") or {})
    language_mode = str(content.get("language_mode") or "EN")
    review_title = str(review.get("display_title") or review.get("title") or "Review")
    titles = {
        "ZH_HANS": ("主要驱动因素", "重点关注领域", "展望"),
        "ZH_HANT": ("主要驅動因素", "重點關注領域", "展望"),
    }
    drivers_title, monitor_title, outlook_title = titles.get(
        language_mode, ("Key Drivers", "Key Areas to Monitor", "Outlook")
    )

    def paragraph(value: object) -> str:
        text = str(value or "")
        if text.casefold().strip() in {"add monthly market review.", "add outlook."}:
            text = ""
        return f"<p>{escape(text)}</p>"

    def item_list(value: object) -> str:
        rows = value if isinstance(value, list) else []
        if not rows:
            return "<p></p>"
        items = []
        for raw in rows:
            item = raw if isinstance(raw, Mapping) else {}
            title = escape(str(item.get("title") or ""))
            body = escape(str(item.get("body") or ""))
            items.append(f"<li><strong>{title}</strong><br>{body}</li>")
        return f"<ol>{''.join(items)}</ol>"

    return [
        {
            "block_id": "summary", "type": "rich_text", "title": review_title,
            "content": paragraph(review.get("summary")),
            "x": 0, "y": 0, "w": 12, "h": 4, "text_align": "left",
        },
        {
            "block_id": "drivers", "type": "key_drivers", "title": drivers_title,
            "content": item_list(review.get("drivers")),
            "x": 0, "y": 4, "w": 6, "h": 7, "text_align": "left",
        },
        {
            "block_id": "monitor", "type": "areas_to_monitor", "title": monitor_title,
            "content": item_list(review.get("monitor")),
            "x": 6, "y": 4, "w": 6, "h": 5, "text_align": "left",
        },
        {
            "block_id": "outlook", "type": "outlook", "title": outlook_title,
            "content": paragraph(review.get("outlook")),
            "x": 6, "y": 9, "w": 6, "h": 4, "text_align": "left",
        },
    ]


def _legacy_elements(content: Mapping[str, Any]) -> list[dict[str, Any]]:
    sections = content.get("sections")
    if not isinstance(sections, Mapping):
        raise PageOnePresentationError("sections must be an object.", "sections")
    review = sections.get("month_in_review") or {}
    blocks = review.get("blocks") if isinstance(review, Mapping) else None
    footnotes = sections.get("footnotes") if "footnotes" in sections else None
    if "footnotes" not in sections:
        footnotes = {}
    if not isinstance(footnotes, Mapping):
        raise PageOnePresentationError(
            "sections.footnotes must be an object.",
            "sections.footnotes",
            HISTORICAL_FOOTNOTE_ID,
        )
    elements: list[dict[str, Any]] = []
    max_bottom = 0
    if isinstance(blocks, list):
        for raw in blocks:
            if not isinstance(raw, Mapping) or not str(raw.get("block_id") or "").strip():
                continue
            try:
                row = int(raw["y"])
                row_span = int(raw["h"])
                x = int(raw["x"])
                width = int(raw["w"])
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            elements.append({
                "id": f"{REVIEW_ID_PREFIX}{str(raw['block_id']).strip()}",
                "row": row,
                "row_span": row_span,
                "x": x,
                "w": width,
                "vertical_nudge_steps": 0,
            })
            max_bottom = max(max_bottom, row + row_span)
    elements.extend((
        {
            "id": HISTORICAL_PERFORMANCE_ID,
            "row": max_bottom,
            "row_span": 1,
            "x": 0,
            "w": PAGE_COLUMNS,
            "vertical_nudge_steps": 0,
            "table_font_size_role": "history-10",
            "table_line_height_role": "1.2",
        },
        {
            "id": HISTORICAL_FOOTNOTE_ID,
            "row": max_bottom + 1,
            "row_span": 1,
            "x": 0,
            "w": PAGE_COLUMNS,
            "vertical_nudge_steps": 0,
            "bottom_nudge_steps": 0,
            "paragraph_styles": _default_footnote_styles(
                _paragraph_count(footnotes.get("historical"))
            ),
        },
    ))
    return elements


def _interval_groups(
    blocks: list[dict[str, Any]],
    *,
    start_key: str,
    size_key: str,
) -> list[list[dict[str, Any]]]:
    """Return connected components of half-open intervals on one layout axis."""

    ordered = sorted(
        blocks,
        key=lambda block: (
            int(block[start_key]),
            int(block[start_key]) + int(block[size_key]),
            int(block["y"]),
            int(block["x"]),
            str(block["block_id"]),
        ),
    )
    groups: list[list[dict[str, Any]]] = []
    group_end: int | None = None
    for block in ordered:
        start = int(block[start_key])
        end = start + int(block[size_key])
        if group_end is None or start >= group_end:
            groups.append([block])
            group_end = end
        else:
            groups[-1].append(block)
            group_end = max(group_end, end)
    return groups


def _flow_node(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    """Compile non-overlapping rectangles into renderer-neutral flow containers."""

    ordered = sorted(
        blocks,
        key=lambda block: (int(block["y"]), int(block["x"]), str(block["block_id"])),
    )
    left = min(int(block["x"]) for block in ordered)
    right = max(int(block["x"]) + int(block["w"]) for block in ordered)
    top = min(int(block["y"]) for block in ordered)
    bottom = max(int(block["y"]) + int(block["h"]) for block in ordered)
    bounds = {"x": left, "y": top, "w": right - left, "h": bottom - top}
    if len(ordered) == 1:
        return {**bounds, "kind": "block", "block": ordered[0]}

    column_groups = _interval_groups(ordered, start_key="x", size_key="w")
    if len(column_groups) > 1:
        return {
            **bounds,
            "kind": "columns",
            "children": [_flow_node(group) for group in column_groups],
        }

    row_groups = _interval_groups(ordered, start_key="y", size_key="h")
    if len(row_groups) > 1:
        return {
            **bounds,
            "kind": "stack",
            "children": [_flow_node(group) for group in row_groups],
        }

    fallback_rows: dict[int, list[dict[str, Any]]] = {}
    for block in ordered:
        fallback_rows.setdefault(int(block["y"]), []).append(block)
    children = [
        _flow_node(row) if len(row) > 1 else _flow_node([row[0]])
        for _, row in sorted(fallback_rows.items())
    ]
    if len(children) == 1:
        children = [_flow_node([block]) for block in ordered]
    return {**bounds, "kind": "fallback", "children": children}


def _layout_geometry(element: Mapping[str, Any]) -> tuple[int, int, int, int]:
    try:
        return (
            int(element["row"]), int(element["row_span"]), int(element["x"]), int(element["w"])
        )
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        element_id = str(element.get("id") or "").strip() or None
        raise PageOnePresentationError(
            "Every page-one element requires integer row, row_span, x and w geometry.",
            "presentation.page_one.elements",
            element_id,
        ) from error


def _legacy_geometry(block: Mapping[str, Any]) -> tuple[int, int, int, int] | None:
    try:
        return int(block["y"]), int(block["h"]), int(block["x"]), int(block["w"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


class PageOnePresentationResolver:
    """Adapt and validate page-one presentation through one deep module interface."""

    @staticmethod
    def supports(content: Mapping[str, Any]) -> bool:
        return content.get("template_version") in {"3033-v2", "3033-v3"} or "presentation" in content

    def adapt_document(self, content: Mapping[str, Any]) -> dict[str, Any]:
        """Return a v3-shaped copy without mutating or persisting the source document."""

        result = deepcopy(dict(content))
        if not self.supports(result):
            return result
        sections = result.get("sections")
        if not isinstance(sections, Mapping):
            raise PageOnePresentationError("sections must be an object.", "sections")
        review = sections.get("month_in_review")
        if not isinstance(review, dict):
            raise PageOnePresentationError(
                "sections.month_in_review must be an object.",
                "sections.month_in_review",
            )
        if "blocks" not in review or review["blocks"] == []:
            review["blocks"] = _legacy_review_blocks(result)
            review["layout_schema_version"] = 3
        elif not isinstance(review["blocks"], list):
            raise PageOnePresentationError(
                "sections.month_in_review.blocks must be a list.",
                "sections.month_in_review.blocks",
            )
        if "presentation" not in result:
            result["presentation"] = {
                "schema_version": PRESENTATION_SCHEMA_VERSION,
                "page_one": {"elements": _legacy_elements(result)},
            }
        result["presentation"] = self._normalize_presentation(result)
        self._sync_legacy_block_geometry(result)
        return result

    def reconcile_submission(
        self,
        submitted: Mapping[str, Any],
        current: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """Reconcile v2 block geometry and v3 presentation during the compatibility window.

        Old clients still edit ``x/y/w/h`` while the v3 editor edits presentation elements.  A
        value changed on only one side wins; contradictory edits on both sides are rejected.  The
        method is pure, so preview and persistence use exactly the same reconciliation.
        """

        result = deepcopy(dict(submitted))
        current_is_v3 = str((current or {}).get("template_version") or "") == "3033-v3"
        if not self.supports(result):
            if current_is_v3:
                raise PageOnePresentationError(
                    "A v3 document must include its page-one presentation.",
                    "presentation",
                )
            return result
        if current is None:
            return result
        baseline = self.adapt_document(current)
        incoming_presentation = result.get("presentation")
        if not isinstance(incoming_presentation, Mapping):
            if current_is_v3:
                raise PageOnePresentationError(
                    "A v3 document must include its page-one presentation.",
                    "presentation",
                )
            return result

        incoming_page_one = incoming_presentation.get("page_one")
        if not isinstance(incoming_page_one, Mapping):
            raise PageOnePresentationError(
                "presentation.page_one must be an object.",
                "presentation.page_one",
            )
        incoming_element_list = incoming_page_one.get("elements")
        if not isinstance(incoming_element_list, list):
            raise PageOnePresentationError(
                "presentation.page_one.elements must be a list.",
                "presentation.page_one.elements",
            )

        incoming_sections = result.get("sections")
        if not isinstance(incoming_sections, Mapping):
            raise PageOnePresentationError(
                "sections must be an object.",
                "sections",
            )
        incoming_review_value = incoming_sections.get("month_in_review")
        if not isinstance(incoming_review_value, Mapping):
            raise PageOnePresentationError(
                "sections.month_in_review must be an object.",
                "sections.month_in_review",
            )
        incoming_blocks_value = incoming_review_value.get("blocks")
        if not isinstance(incoming_blocks_value, list):
            raise PageOnePresentationError(
                "sections.month_in_review.blocks must be a list.",
                "sections.month_in_review.blocks",
            )
        incoming_footnotes_value = incoming_sections.get("footnotes")
        if not isinstance(incoming_footnotes_value, Mapping):
            raise PageOnePresentationError(
                "sections.footnotes must be an object.",
                "sections.footnotes",
            )

        baseline_elements = {
            str(item.get("id")): item
            for item in ((baseline.get("presentation") or {}).get("page_one") or {}).get("elements", [])
            if isinstance(item, Mapping)
        }
        incoming_elements = {
            str(item.get("id")): item
            for item in incoming_element_list
            if isinstance(item, Mapping)
        }
        baseline_blocks = {
            str(item.get("block_id")): item
            for item in (((baseline.get("sections") or {}).get("month_in_review") or {}).get("blocks") or [])
            if isinstance(item, Mapping)
        }
        incoming_blocks = {
            str(item.get("block_id")): item
            for item in incoming_blocks_value
            if isinstance(item, Mapping)
        }

        if current_is_v3 and set(incoming_blocks) != set(baseline_blocks):
            raise PageOnePresentationError(
                "Review block identities are fixed after the v3 layout is created.",
                "sections.month_in_review.blocks",
            )
        if current_is_v3 and set(incoming_elements) != set(baseline_elements):
            raise PageOnePresentationError(
                "Page-one element identities are fixed after the v3 layout is created.",
                "presentation.page_one.elements",
            )
        if current_is_v3:
            # Validate geometry, style roles and nested shapes before compatibility comparison.
            # This keeps malformed draft payloads on the stable structured 422 path instead of
            # leaking AttributeError/KeyError/TypeError as a server error.
            self._normalize_presentation(result)

        baseline_review = ((baseline.get("sections") or {}).get("month_in_review") or {})
        incoming_review = incoming_review_value

        if current_is_v3:
            baseline_terms_value = baseline.get("terminology_overrides")
            incoming_terms_value = result.get("terminology_overrides")
            if baseline_terms_value is None:
                baseline_terms_value = {}
            if incoming_terms_value is None:
                incoming_terms_value = {}
            if not isinstance(incoming_terms_value, Mapping):
                raise PageOnePresentationError(
                    "Terminology overrides must be an object.",
                    "terminology_overrides",
                )
            baseline_terms = baseline_terms_value if isinstance(baseline_terms_value, Mapping) else {}
            incoming_terms = incoming_terms_value
            for field in ("product_name", "benchmark_name"):
                baseline_value = str(baseline_terms.get(field) or "")
                incoming_value = str(incoming_terms.get(field) or "")
                if incoming_value != baseline_value:
                    raise PageOnePresentationError(
                        "Product and benchmark headings are fixed for this template.",
                        f"terminology_overrides.{field}",
                    )

        # During the compatibility window an older client can still edit the four legacy prose
        # fields while carrying unchanged v3 blocks returned by GET. Preserve that edit by
        # updating only the matching block content. If the block itself changed, the v3 editor is
        # authoritative. Once a document is already v3, module titles are immutable server-side
        # as well as hidden in the UI.
        generated_blocks = {
            str(block["block_id"]): block for block in _legacy_review_blocks(result)
        }
        for block_id, legacy_field in (
            ("summary", "summary"),
            ("drivers", "drivers"),
            ("monitor", "monitor"),
            ("outlook", "outlook"),
        ):
            baseline_block = baseline_blocks.get(block_id)
            incoming_block = incoming_blocks.get(block_id)
            if baseline_block is None or incoming_block is None:
                continue
            legacy_changed = incoming_review.get(legacy_field) != baseline_review.get(legacy_field)
            block_changed = incoming_block.get("content") != baseline_block.get("content")
            if legacy_changed and not block_changed:
                incoming_block["content"] = generated_blocks[block_id]["content"]

        baseline_title = str(
            baseline_review.get("display_title") or baseline_review.get("title") or ""
        ).strip()
        incoming_title = str(
            incoming_review.get("display_title") or incoming_review.get("title") or ""
        ).strip()
        baseline_summary = baseline_blocks.get("summary")
        incoming_summary = incoming_blocks.get("summary")
        if str(current.get("template_version") or "") == "3033-v3":
            for block_id, incoming_block in incoming_blocks.items():
                baseline_block = baseline_blocks.get(block_id)
                if baseline_block is not None and incoming_block.get("title") != baseline_block.get("title"):
                    raise PageOnePresentationError(
                        "Review module titles are fixed for this template.",
                        f"sections.month_in_review.blocks.{block_id}.title",
                        f"{REVIEW_ID_PREFIX}{block_id}",
                    )
            if incoming_title != baseline_title:
                raise PageOnePresentationError(
                    "The Review module title is fixed for this template.",
                    "sections.month_in_review.display_title",
                    f"{REVIEW_ID_PREFIX}summary",
                )
        elif (
            incoming_title != baseline_title
            and baseline_summary is not None
            and incoming_summary is not None
            and incoming_summary.get("title") == baseline_summary.get("title")
        ):
            incoming_summary["title"] = incoming_title

        mutable_elements = list(incoming_element_list)
        by_id = {
            str(item.get("id")): item for item in mutable_elements if isinstance(item, dict)
        }
        legacy_geometry_changed = False
        for block_id, block in incoming_blocks.items():
            element_id = f"{REVIEW_ID_PREFIX}{block_id}"
            current_block = baseline_blocks.get(block_id)
            current_element = baseline_elements.get(element_id)
            incoming_element = incoming_elements.get(element_id)
            if current_block is None or current_element is None or incoming_element is None:
                continue
            legacy_changed = _legacy_geometry(block) != _legacy_geometry(current_block)
            presentation_changed = _layout_geometry(incoming_element) != _layout_geometry(current_element)
            if legacy_changed and presentation_changed:
                if _legacy_geometry(block) != _layout_geometry(incoming_element):
                    raise PageOnePresentationError(
                        "Review geometry was changed inconsistently by two editor schema versions.",
                        f"presentation.page_one.elements.{element_id}",
                        element_id,
                    )
            elif legacy_changed:
                row, row_span, x, width = _legacy_geometry(block) or (0, 1, 0, PAGE_COLUMNS)
                by_id[element_id].update({"row": row, "row_span": row_span, "x": x, "w": width})
                legacy_geometry_changed = True

        # A v2 client has no controls for the table/footnote rows. When its block rectangles grow,
        # keep those unchanged fixed elements immediately after the Review flow rather than
        # turning a valid legacy edit into an overlap during the atomic v3 upgrade.
        if legacy_geometry_changed:
            review_elements = [
                element for element_id, element in by_id.items()
                if element_id.startswith(REVIEW_ID_PREFIX)
            ]
            max_bottom = max(
                (sum(_layout_geometry(element)[:2]) for element in review_elements),
                default=0,
            )
            for element_id, row in (
                (HISTORICAL_PERFORMANCE_ID, max_bottom),
                (HISTORICAL_FOOTNOTE_ID, max_bottom + 1),
            ):
                incoming_element = incoming_elements.get(element_id)
                baseline_element = baseline_elements.get(element_id)
                if (
                    incoming_element is not None
                    and baseline_element is not None
                    and _layout_geometry(incoming_element) == _layout_geometry(baseline_element)
                ):
                    by_id[element_id]["row"] = row

        # A legacy client removes a block without knowing about presentation. Remove its unchanged
        # element too; a deliberately edited orphan remains an error instead of disappearing.
        for block_id in set(baseline_blocks) - set(incoming_blocks):
            element_id = f"{REVIEW_ID_PREFIX}{block_id}"
            incoming_element = incoming_elements.get(element_id)
            current_element = baseline_elements.get(element_id)
            if incoming_element is not None and current_element is not None and (
                _layout_geometry(incoming_element) == _layout_geometry(current_element)
            ):
                mutable_elements.remove(by_id[element_id])

        result["presentation"] = deepcopy(dict(incoming_presentation))
        result["presentation"]["page_one"] = deepcopy(dict(incoming_page_one))
        result["presentation"]["page_one"]["elements"] = mutable_elements
        return result

    def canonicalize_document(self, content: Mapping[str, Any]) -> dict[str, Any]:
        """Validate presentation and return a copy with compatibility geometry synchronized."""

        return self.adapt_document(content)

    def retarget_footnote_styles(self, content: Mapping[str, Any]) -> dict[str, Any]:
        """Fit trusted layout styles to newly replaced footnote paragraphs.

        Snapshot refreshes and language variants can replace approved footnote prose outside the
        document-edit API. Paragraph-indexed styles from the old text cannot point past the new
        text. This internal-content helper drops those stale indexes and supplies canonical
        defaults for new paragraphs; normal API submissions continue through strict validation
        and are never repaired silently.
        """

        result = deepcopy(dict(content))
        presentation = result.get("presentation")
        page_one = presentation.get("page_one") if isinstance(presentation, Mapping) else None
        elements = page_one.get("elements") if isinstance(page_one, Mapping) else None
        if not isinstance(elements, list):
            return result
        paragraph_count = _paragraph_count(
            ((result.get("sections") or {}).get("footnotes") or {}).get("historical")
        )
        defaults = {
            style["paragraph_index"]: style
            for style in _default_footnote_styles(paragraph_count)
        }
        for element in elements:
            if not isinstance(element, dict) or element.get("id") != HISTORICAL_FOOTNOTE_ID:
                continue
            for style in element.get("paragraph_styles") or []:
                if not isinstance(style, Mapping):
                    continue
                index = style.get("paragraph_index")
                if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < paragraph_count:
                    defaults[index] = deepcopy(dict(style))
            element["paragraph_styles"] = [defaults[index] for index in range(paragraph_count)]
            break
        return result

    @staticmethod
    def compile_review_flow(blocks: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Compile Review geometry once for HTML, PDF, and DOCX format adapters."""

        return _flow_node(deepcopy(blocks)) if blocks else None

    @staticmethod
    def assert_no_overflow(findings: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...]) -> None:
        """Convert renderer measurements into the stable domain error used by finalize/export."""

        if findings:
            raise PageOneLayoutOverflowError(tuple(deepcopy(list(findings))))

    def resolve_for_render(
        self,
        content: Mapping[str, Any],
        tokens: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Resolve validated topology and token roles for every renderer.

        Renderers receive physical values, never raw user-controlled role names or nudge values.
        This keeps the HTML/PDF and DOCX implementations as thin format adapters over the same
        presentation semantics.
        """

        document = self.adapt_document(content)
        raw_elements = document["presentation"]["page_one"]["elements"]
        review_tokens = tokens.get("review") if isinstance(tokens.get("review"), Mapping) else {}
        font_tokens = tokens.get("font") if isinstance(tokens.get("font"), Mapping) else {}
        body_pt = float(font_tokens.get("bodyPt", 10))
        step_lines = float(review_tokens.get("verticalNudgeStepLines", 0.5))
        font_sizes = {
            "review-10": 10.0,
            "review-11": 11.0,
            "history-9": 9.0,
            "history-10": 10.0,
            "history-11": 11.0,
            "footnote-8": 8.0,
            "footnote-9": 9.0,
            "footnote-10": 10.0,
            **{
                str(role): float(size)
                for role, size in (review_tokens.get("fontSizeRolesPt") or {}).items()
            },
        }
        line_heights = {
            "1.0": 1.0,
            "1.2": 1.2,
            "1.4": 1.4,
            **{
                str(role): float(size)
                for role, size in (review_tokens.get("lineHeightRoles") or {}).items()
            },
        }
        default_review_font_role = str(
            review_tokens.get("defaultReviewFontSizeRole") or "review-10"
        )
        default_review_line_role = str(
            review_tokens.get("defaultReviewLineHeightRole") or "1.2"
        )
        default_history_font_role = str(
            review_tokens.get("defaultHistoricalTableFontSizeRole") or "history-10"
        )
        default_history_line_role = str(
            review_tokens.get("defaultHistoricalTableLineHeightRole") or "1.2"
        )
        if default_review_font_role not in REVIEW_FONT_SIZE_ROLES:
            raise PageOnePresentationError(
                "The template has an unsupported default Review font-size role.",
                "design_tokens.review.defaultReviewFontSizeRole",
            )
        if default_review_line_role not in LINE_HEIGHT_ROLES:
            raise PageOnePresentationError(
                "The template has an unsupported default Review line-height role.",
                "design_tokens.review.defaultReviewLineHeightRole",
            )
        if default_history_font_role not in HISTORICAL_TABLE_FONT_SIZE_ROLES:
            raise PageOnePresentationError(
                "The template has an unsupported default Historical table font-size role.",
                "design_tokens.review.defaultHistoricalTableFontSizeRole",
            )
        if default_history_line_role not in LINE_HEIGHT_ROLES:
            raise PageOnePresentationError(
                "The template has an unsupported default Historical table line-height role.",
                "design_tokens.review.defaultHistoricalTableLineHeightRole",
            )
        elements = {
            item["id"]: {
                **deepcopy(item),
                "vertical_nudge_pt": round(item["vertical_nudge_steps"] * step_lines * body_pt, 4),
            }
            for item in raw_elements
        }
        review = ((document.get("sections") or {}).get("month_in_review") or {})
        review_blocks: list[dict[str, Any]] = []
        for block in review.get("blocks") or []:
            if not isinstance(block, Mapping):
                continue
            element = elements.get(f"{REVIEW_ID_PREFIX}{block.get('block_id')}")
            if element is not None:
                review_blocks.append({
                    **deepcopy(dict(block)),
                    "layout_id": element["id"],
                    "vertical_nudge_pt": element["vertical_nudge_pt"],
                })

        footnote = elements[HISTORICAL_FOOTNOTE_ID]
        footnote_text = str(
            ((document.get("sections") or {}).get("footnotes") or {}).get("historical") or ""
        ).replace("\r\n", "\n")
        paragraphs = [part for part in re.split(r"\n\s*\n", footnote_text) if part.strip()] or [""]
        styles = {item["paragraph_index"]: item for item in footnote["paragraph_styles"]}
        resolved_paragraphs = []
        for index, text in enumerate(paragraphs):
            style = styles[index]
            resolved_paragraphs.append({
                "paragraph_index": index,
                "text": text,
                "font_size_role": style["font_size_role"],
                "font_size_pt": font_sizes[style["font_size_role"]],
                "line_height_role": style["line_height_role"],
                "line_height": line_heights[style["line_height_role"]],
                "text_align": style["text_align"],
            })
        baseline_bottom_mm = float(review_tokens.get("footnoteBaselineBottomMm", 20))
        footnote_step_lines = float(review_tokens.get("footnoteBottomNudgeStepLines", 0.5))
        footnote_step_mm = font_sizes["footnote-8"] * footnote_step_lines * 25.4 / 72
        footnote["bottom_mm"] = round(
            baseline_bottom_mm + footnote["bottom_nudge_steps"] * footnote_step_mm,
            4,
        )
        footnote["bottom_nudge_pt"] = round(
            footnote["bottom_nudge_steps"] * font_sizes["footnote-8"] * footnote_step_lines,
            4,
        )
        footnote["paragraphs"] = resolved_paragraphs
        historical = elements[HISTORICAL_PERFORMANCE_ID]
        historical["table_font_size_pt"] = font_sizes[historical["table_font_size_role"]]
        historical["table_line_height"] = line_heights[historical["table_line_height_role"]]
        return {
            "document": document,
            "elements": elements,
            "review_blocks": review_blocks,
            "review_layout": self.compile_review_flow(review_blocks),
            "historical": historical,
            "footnote": footnote,
            "style_roles": {
                "font_size_pt": font_sizes,
                "line_height": line_heights,
                "defaults": {
                    "review_font_size_role": default_review_font_role,
                    "review_font_size_pt": font_sizes[default_review_font_role],
                    "review_line_height_role": default_review_line_role,
                    "review_line_height": line_heights[default_review_line_role],
                },
            },
        }

    def _normalize_presentation(self, content: Mapping[str, Any]) -> dict[str, Any]:
        raw = content.get("presentation")
        if not isinstance(raw, Mapping):
            raise PageOnePresentationError("presentation must be an object.", "presentation")
        if set(raw) - {"schema_version", "page_one"}:
            raise PageOnePresentationError(
                "presentation contains unsupported fields.", "presentation"
            )
        schema_version = raw.get("schema_version")
        if type(schema_version) is not int or schema_version != PRESENTATION_SCHEMA_VERSION:
            raise PageOnePresentationError(
                f"presentation.schema_version must be {PRESENTATION_SCHEMA_VERSION}.",
                "presentation.schema_version",
            )
        page_one = raw.get("page_one")
        if not isinstance(page_one, Mapping) or set(page_one) - {"elements"}:
            raise PageOnePresentationError(
                "presentation.page_one must contain only elements.", "presentation.page_one"
            )
        raw_elements = page_one.get("elements")
        if not isinstance(raw_elements, list) or len(raw_elements) > 42:
            raise PageOnePresentationError(
                "presentation.page_one.elements must be a list with at most 42 entries.",
                "presentation.page_one.elements",
            )

        sections = content.get("sections")
        if not isinstance(sections, Mapping):
            raise PageOnePresentationError("sections must be an object.", "sections")
        review = sections.get("month_in_review")
        if not isinstance(review, Mapping):
            raise PageOnePresentationError(
                "sections.month_in_review must be an object.",
                "sections.month_in_review",
            )
        blocks = review.get("blocks")
        if not isinstance(blocks, list) or any(not isinstance(item, Mapping) for item in blocks):
            raise PageOnePresentationError(
                "sections.month_in_review.blocks must be a list of objects.",
                "sections.month_in_review.blocks",
            )
        block_id_list: list[str] = []
        for index, item in enumerate(blocks):
            raw_block_id = item.get("block_id")
            block_id = raw_block_id.strip() if isinstance(raw_block_id, str) else ""
            if not block_id or raw_block_id != block_id or len(block_id) > 120:
                raise PageOnePresentationError(
                    "Every Review block requires a stable, trimmed id of at most 120 characters.",
                    f"sections.month_in_review.blocks.{index}.block_id",
                )
            if block_id in block_id_list:
                raise PageOnePresentationError(
                    f"Duplicate Review block id: {block_id}.",
                    f"sections.month_in_review.blocks.{index}.block_id",
                    f"{REVIEW_ID_PREFIX}{block_id}",
                )
            block_id_list.append(block_id)
        block_ids = set(block_id_list)
        elements: list[dict[str, Any]] = []
        ids: set[str] = set()
        for index, raw_element in enumerate(raw_elements):
            if not isinstance(raw_element, Mapping):
                raise PageOnePresentationError(
                    f"Page-one element {index} must be an object.",
                    f"presentation.page_one.elements.{index}",
                )
            element_id = str(raw_element.get("id") or "").strip()
            field = f"presentation.page_one.elements.{index}"
            if not element_id or len(element_id) > 120 or element_id in ids:
                raise PageOnePresentationError(
                    "Every page-one element requires a unique id of at most 120 characters.",
                    f"{field}.id",
                    element_id or None,
                )
            if element_id not in {HISTORICAL_PERFORMANCE_ID, HISTORICAL_FOOTNOTE_ID} and not element_id.startswith(REVIEW_ID_PREFIX):
                raise PageOnePresentationError(
                    f"Unsupported page-one element id: {element_id}.", f"{field}.id", element_id
                )
            if element_id.startswith(REVIEW_ID_PREFIX) and element_id[len(REVIEW_ID_PREFIX):] not in block_ids:
                raise PageOnePresentationError(
                    f"Page-one element {element_id} does not reference a Review block.",
                    f"{field}.id",
                    element_id,
                )
            allowed_keys = (
                _FOOTNOTE_ELEMENT_KEYS
                if element_id == HISTORICAL_FOOTNOTE_ID
                else _HISTORICAL_ELEMENT_KEYS
                if element_id == HISTORICAL_PERFORMANCE_ID
                else _BASE_ELEMENT_KEYS
            )
            if set(raw_element) - allowed_keys:
                raise PageOnePresentationError(
                    f"Page-one element {element_id} contains unsupported fields.", field, element_id
                )
            row = _int(raw_element.get("row"), field=f"{field}.row", minimum=0, maximum=MAX_ROW)
            row_span = _int(
                raw_element.get("row_span"), field=f"{field}.row_span", minimum=1, maximum=MAX_ROW_SPAN
            )
            x = _int(raw_element.get("x"), field=f"{field}.x", minimum=0, maximum=PAGE_COLUMNS - 1)
            width = _int(raw_element.get("w"), field=f"{field}.w", minimum=1, maximum=PAGE_COLUMNS)
            if x + width > PAGE_COLUMNS:
                raise PageOnePresentationError(
                    f"Page-one element {element_id} exceeds the 12-column canvas.", field, element_id
                )
            vertical_nudge = _int(
                raw_element.get("vertical_nudge_steps", 0),
                field=f"{field}.vertical_nudge_steps",
                minimum=MIN_VERTICAL_NUDGE_STEPS,
                maximum=MAX_VERTICAL_NUDGE_STEPS,
            )
            if element_id in {HISTORICAL_PERFORMANCE_ID, HISTORICAL_FOOTNOTE_ID} and (x != 0 or width != PAGE_COLUMNS):
                raise PageOnePresentationError(
                    f"{element_id} must remain full width.", field, element_id
                )
            normalized = {
                "id": element_id,
                "row": row,
                "row_span": row_span,
                "x": x,
                "w": width,
                "vertical_nudge_steps": vertical_nudge,
            }
            if element_id == HISTORICAL_PERFORMANCE_ID:
                font_size_role = str(
                    raw_element.get("table_font_size_role", "history-10")
                )
                line_height_role = str(
                    raw_element.get("table_line_height_role", "1.2")
                )
                if font_size_role not in HISTORICAL_TABLE_FONT_SIZE_ROLES:
                    raise PageOnePresentationError(
                        f"Unsupported Historical table font-size role: {font_size_role}.",
                        f"{field}.table_font_size_role",
                        HISTORICAL_PERFORMANCE_ID,
                    )
                if line_height_role not in LINE_HEIGHT_ROLES:
                    raise PageOnePresentationError(
                        f"Unsupported Historical table line-height role: {line_height_role}.",
                        f"{field}.table_line_height_role",
                        HISTORICAL_PERFORMANCE_ID,
                    )
                normalized.update({
                    "table_font_size_role": font_size_role,
                    "table_line_height_role": line_height_role,
                })
            elif element_id == HISTORICAL_FOOTNOTE_ID:
                normalized.update(self._normalize_footnote(raw_element, content, field))
            elements.append(normalized)
            ids.add(element_id)

        missing_review = block_ids - {
            item["id"][len(REVIEW_ID_PREFIX):]
            for item in elements
            if item["id"].startswith(REVIEW_ID_PREFIX)
        }
        if missing_review:
            block_map = {str(item["block_id"]).strip(): item for item in blocks}
            for block_id in sorted(missing_review):
                block = block_map.get(block_id)
                if block is None:
                    raise PageOnePresentationError(
                        f"Review block {block_id} has no canonical definition.",
                        "sections.month_in_review.blocks",
                        f"{REVIEW_ID_PREFIX}{block_id}",
                    )
                geometry = _legacy_geometry(block)
                if geometry is None:
                    raise PageOnePresentationError(
                        f"Review block {block_id} has no page-one element.",
                        "presentation.page_one.elements",
                        f"{REVIEW_ID_PREFIX}{block_id}",
                    )
                row, row_span, x, width = geometry
                elements.append({
                    "id": f"{REVIEW_ID_PREFIX}{block_id}",
                    "row": row,
                    "row_span": row_span,
                    "x": x,
                    "w": width,
                    "vertical_nudge_steps": 0,
                })

            # A v2 client can add Review blocks to an in-memory adapted document without knowing
            # that the fixed elements were provisionally placed at rows 0/1. Preserve the legacy
            # contract by flowing the table and footnote after the newly discovered blocks.
            review_bottom = max(
                item["row"] + item["row_span"]
                for item in elements
                if item["id"].startswith(REVIEW_ID_PREFIX)
            )
            fixed = {item["id"]: item for item in elements if item["id"] in {
                HISTORICAL_PERFORMANCE_ID, HISTORICAL_FOOTNOTE_ID,
            }}
            historical = fixed.get(HISTORICAL_PERFORMANCE_ID)
            footnote = fixed.get(HISTORICAL_FOOTNOTE_ID)
            if historical is not None and historical["row"] < review_bottom:
                historical["row"] = review_bottom
            if historical is not None and footnote is not None:
                historical_bottom = historical["row"] + historical["row_span"]
                if footnote["row"] < historical_bottom:
                    footnote["row"] = historical_bottom

        required = {HISTORICAL_PERFORMANCE_ID, HISTORICAL_FOOTNOTE_ID}
        missing_fixed = required - {item["id"] for item in elements}
        if missing_fixed:
            raise PageOnePresentationError(
                f"Missing required page-one elements: {', '.join(sorted(missing_fixed))}.",
                "presentation.page_one.elements",
            )

        by_id = {item["id"]: item for item in elements}
        review_elements = [
            item for item in elements if item["id"].startswith(REVIEW_ID_PREFIX)
        ]
        review_bottom = max(
            (item["row"] + item["row_span"] for item in review_elements),
            default=0,
        )
        historical = by_id[HISTORICAL_PERFORMANCE_ID]
        footnote = by_id[HISTORICAL_FOOTNOTE_ID]
        if historical["row"] < review_bottom:
            raise PageOnePresentationError(
                "Historical Performance must follow all Review blocks.",
                "presentation.page_one.elements",
                HISTORICAL_PERFORMANCE_ID,
            )
        if footnote["row"] < historical["row"] + historical["row_span"]:
            raise PageOnePresentationError(
                "The historical footnote must follow Historical Performance.",
                "presentation.page_one.elements",
                HISTORICAL_FOOTNOTE_ID,
            )

        ordered = sorted(elements, key=lambda item: (item["row"], item["x"], item["id"]))
        for index, left in enumerate(ordered):
            for right in ordered[index + 1:]:
                horizontal = left["x"] < right["x"] + right["w"] and right["x"] < left["x"] + left["w"]
                vertical = left["row"] < right["row"] + right["row_span"] and right["row"] < left["row"] + left["row_span"]
                if horizontal and vertical:
                    raise PageOnePresentationError(
                        f"Page-one elements {left['id']} and {right['id']} overlap.",
                        "presentation.page_one.elements",
                        left["id"],
                    )
        return {"schema_version": PRESENTATION_SCHEMA_VERSION, "page_one": {"elements": ordered}}

    def _normalize_footnote(
        self,
        raw: Mapping[str, Any],
        content: Mapping[str, Any],
        field: str,
    ) -> dict[str, Any]:
        bottom_nudge = _int(
            raw.get("bottom_nudge_steps", 0),
            field=f"{field}.bottom_nudge_steps",
            minimum=MIN_FOOTNOTE_BOTTOM_NUDGE_STEPS,
            maximum=MAX_FOOTNOTE_BOTTOM_NUDGE_STEPS,
        )
        sections = content.get("sections")
        if not isinstance(sections, Mapping):
            raise PageOnePresentationError("sections must be an object.", "sections")
        footnotes = sections.get("footnotes") if "footnotes" in sections else None
        if "footnotes" not in sections:
            footnotes = {}
        if not isinstance(footnotes, Mapping):
            raise PageOnePresentationError(
                "sections.footnotes must be an object.",
                "sections.footnotes",
                HISTORICAL_FOOTNOTE_ID,
            )
        paragraph_count = _paragraph_count(footnotes.get("historical"))
        raw_styles = raw.get("paragraph_styles", [])
        if not isinstance(raw_styles, list):
            raise PageOnePresentationError(
                "Historical footnote paragraph_styles must be a list.",
                f"{field}.paragraph_styles",
                HISTORICAL_FOOTNOTE_ID,
            )
        styles = {item["paragraph_index"]: item for item in _default_footnote_styles(paragraph_count)}
        seen: set[int] = set()
        for index, raw_style in enumerate(raw_styles):
            style_field = f"{field}.paragraph_styles.{index}"
            if not isinstance(raw_style, Mapping) or set(raw_style) != _PARAGRAPH_STYLE_KEYS:
                raise PageOnePresentationError(
                    "Each footnote paragraph style must contain only paragraph_index, "
                    "font_size_role, line_height_role and text_align.",
                    style_field,
                    HISTORICAL_FOOTNOTE_ID,
                )
            paragraph_index = _int(
                raw_style.get("paragraph_index"),
                field=f"{style_field}.paragraph_index",
                minimum=0,
                maximum=paragraph_count - 1,
            )
            if paragraph_index in seen:
                raise PageOnePresentationError(
                    f"Footnote paragraph {paragraph_index} has duplicate styles.",
                    style_field,
                    HISTORICAL_FOOTNOTE_ID,
                )
            font_size_role = str(raw_style.get("font_size_role") or "")
            line_height_role = str(raw_style.get("line_height_role") or "")
            text_align = str(raw_style.get("text_align") or "")
            if font_size_role not in FOOTNOTE_FONT_SIZE_ROLES:
                raise PageOnePresentationError(
                    f"Unsupported footnote font-size role: {font_size_role}.",
                    f"{style_field}.font_size_role",
                    HISTORICAL_FOOTNOTE_ID,
                )
            if line_height_role not in LINE_HEIGHT_ROLES:
                raise PageOnePresentationError(
                    f"Unsupported line-height role: {line_height_role}.",
                    f"{style_field}.line_height_role",
                    HISTORICAL_FOOTNOTE_ID,
                )
            if text_align not in TEXT_ALIGNMENTS:
                raise PageOnePresentationError(
                    f"Unsupported paragraph alignment: {text_align}.",
                    f"{style_field}.text_align",
                    HISTORICAL_FOOTNOTE_ID,
                )
            styles[paragraph_index] = {
                "paragraph_index": paragraph_index,
                "font_size_role": font_size_role,
                "line_height_role": line_height_role,
                "text_align": text_align,
            }
            seen.add(paragraph_index)
        return {
            "bottom_nudge_steps": bottom_nudge,
            "paragraph_styles": [styles[index] for index in range(paragraph_count)],
        }

    @staticmethod
    def _sync_legacy_block_geometry(content: dict[str, Any]) -> None:
        elements = {
            item["id"]: item
            for item in content["presentation"]["page_one"]["elements"]
            if item["id"].startswith(REVIEW_ID_PREFIX)
        }
        review = ((content.get("sections") or {}).get("month_in_review") or {})
        blocks = review.get("blocks") if isinstance(review, dict) else None
        if not isinstance(blocks, list):
            return
        for block in blocks:
            if not isinstance(block, dict):
                continue
            element = elements.get(f"{REVIEW_ID_PREFIX}{str(block.get('block_id') or '').strip()}")
            if element:
                block.update({
                    "x": element["x"],
                    "y": element["row"],
                    "w": element["w"],
                    "h": element["row_span"],
                })
        review["layout_schema_version"] = 3


page_one_presentation = PageOnePresentationResolver()
