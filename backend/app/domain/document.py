import hashlib
import json
from copy import deepcopy
from datetime import date
from html import escape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

from .localization import is_chinese, is_zh_hans, is_zh_hant, month_name
from .page_one_presentation import (
    LINE_HEIGHT_ROLES,
    REVIEW_FONT_SIZE_ROLES,
    TEXT_ALIGNMENTS,
    PageOnePresentationError,
    page_one_presentation,
)
from .rich_text import rich_text_plain_text, sanitize_rich_text


REVIEW_BLOCK_TYPES = {"rich_text", "heading", "bullet_list", "key_drivers", "areas_to_monitor", "outlook", "metric_callout", "image", "data_table", "page_break"}
REVIEW_TEXT_ALIGNMENTS = {"left", "center", "right", "justify"}
REBALANCING_DATE_SOURCES = {"SNAPSHOT", "MANUAL"}


class DocumentValidationError(ValueError):
    def __init__(self, error_code: str, message: str, field: str, fix_hint: str, entity_id: str | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.field = field
        self.entity_id = entity_id
        self.fix_hint = fix_hint


class ReviewHtmlSanitizer(HTMLParser):
    allowed_tags = {"p", "strong", "em", "ul", "ol", "li", "a", "br", "h2", "h3", "blockquote"}
    paragraph_attributes = {
        "data-font-size-role": REVIEW_FONT_SIZE_ROLES,
        "data-line-height-role": LINE_HEIGHT_ROLES,
        "data-text-align": TEXT_ALIGNMENTS,
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "font" or any(key.casefold() == "style" for key, _ in attrs):
            raise PageOnePresentationError(
                "Review content cannot contain inline CSS or font declarations.",
                "sections.month_in_review.blocks.content",
            )
        if tag not in self.allowed_tags:
            return
        if tag in {"p", "li"}:
            normalized: list[tuple[str, str]] = []
            seen: set[str] = set()
            for key, value in attrs:
                key = key.casefold()
                if key in seen or key not in self.paragraph_attributes:
                    raise PageOnePresentationError(
                        f"Review {tag} contains unsupported formatting attribute {key!r}.",
                        "sections.month_in_review.blocks.content",
                    )
                value = str(value or "")
                if value not in self.paragraph_attributes[key]:
                    raise PageOnePresentationError(
                        f"Review {tag} contains unsupported value {value!r} for {key}.",
                        "sections.month_in_review.blocks.content",
                    )
                seen.add(key)
                normalized.append((key, value))
            serialized = "".join(
                f' {key}="{escape(value, quote=True)}"' for key, value in sorted(normalized)
            )
            self.parts.append(f"<{tag}{serialized}>")
            return
        if tag == "a":
            href = next((value for key, value in attrs if key == "href"), None)
            parsed = urlparse(href or "")
            if parsed.scheme in {"http", "https", "mailto"}:
                self.parts.append(f'<a href="{escape(href or "", quote=True)}">')
                return
            self.parts.append("<a>")
            return
        self.parts.append(f"<{tag}>")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.allowed_tags and tag != "br":
            self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self.parts.append(escape(data))


def sanitize_review_html(value: str) -> str:
    return sanitize_rich_text(
        value,
        error_factory=lambda message: PageOnePresentationError(
            message,
            "sections.month_in_review.blocks.content",
        ),
        legacy_font_roles=REVIEW_FONT_SIZE_ROLES,
        legacy_line_roles=LINE_HEIGHT_ROLES,
    )


class ReviewTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def review_plain_text(value: str) -> str:
    return " ".join(rich_text_plain_text(value).split())


def _has_substantive_review_text(block: dict[str, Any]) -> bool:
    text = review_plain_text(str(block.get("content", "")))
    normalized = text.casefold()
    return bool(text) and normalized not in {
        "add monthly market review.",
        "add outlook.",
        "no content yet.",
        "start writing...",
    } and not normalized.startswith("add the approved")


def has_substantive_review_blocks(review: dict[str, Any]) -> bool:
    """Return whether a Review already contains editor-authored block copy.

    Initial v3 documents carry the complete page-one topology, including placeholder blocks.
    Those placeholders must not outrank editorial text supplied later by snapshot binding or the
    assisted-draft action.  Once any block contains substantive copy, however, the block model is
    canonical and snapshot rebinding must preserve the editor's work.
    """

    blocks = review.get("blocks")
    return isinstance(blocks, list) and any(
        isinstance(block, dict) and _has_substantive_review_text(block)
        for block in blocks
    )


def review_display_title(document: dict[str, Any]) -> str:
    review = document.get("sections", {}).get("month_in_review", {})
    for field in ("display_title", "title"):
        value = review.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    month_name = str(document.get("month_name", "")).strip()
    return f"{month_name} in Review" if month_name else "Review"


def validate_document_content(content: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(content)
    # Validate the authoritative v3 topology before the compatibility block fields. This keeps
    # all page-one geometry failures on the PAGE_ONE_PRESENTATION_INVALID contract instead of
    # leaking the legacy REVIEW_LAYOUT_INVALID fallback from an x/y/w/h check below.
    if result.get("template_version") in {"3033-v3", "3033-v4"} or "presentation" in result:
        result = page_one_presentation.canonicalize_document(result)
    sections = result.get("sections")
    if not isinstance(sections, dict):
        raise ValueError("sections must be an object")
    review = sections.get("month_in_review")
    if not isinstance(review, dict):
        raise ValueError("month_in_review must be an object")
    title_value = review.get("display_title")
    if not isinstance(title_value, str):
        title_value = review.get("title", review_display_title(result))
    title = str(title_value).strip()
    if not title:
        raise DocumentValidationError(
            "REVIEW_TITLE_INVALID",
            "Review title cannot be empty.",
            "sections.month_in_review.display_title",
            "Enter a Review title before saving.",
        )
    if len(title) > 200:
        raise DocumentValidationError(
            "REVIEW_TITLE_INVALID",
            "Review title cannot exceed 200 characters.",
            "sections.month_in_review.display_title",
            "Shorten the Review title to 200 characters or fewer.",
        )
    review["title"] = title
    review["display_title"] = title
    rebalancing_date = result.get("next_rebalancing_date")
    if rebalancing_date is None or rebalancing_date == "":
        result["next_rebalancing_date"] = None
    else:
        try:
            result["next_rebalancing_date"] = date.fromisoformat(str(rebalancing_date)).isoformat()
        except ValueError as error:
            raise DocumentValidationError(
                "NEXT_REBALANCING_DATE_INVALID",
                "Next rebalancing date must be a valid calendar date.",
                "next_rebalancing_date",
                "Choose a valid date before saving.",
            ) from error
    source = str(result.get("next_rebalancing_date_source") or "SNAPSHOT").upper()
    if source not in REBALANCING_DATE_SOURCES:
        raise DocumentValidationError(
            "NEXT_REBALANCING_DATE_SOURCE_INVALID",
            "Next rebalancing date source is invalid.",
            "next_rebalancing_date_source",
            "Use the calculated snapshot date or save a manual date in the editor.",
        )
    result["next_rebalancing_date_source"] = source
    blocks = review.get("blocks")
    has_block_schema = blocks is not None
    if blocks is None:
        blocks = []
    if not isinstance(blocks, list) or len(blocks) > 40:
        raise ValueError("Review blocks must be a list with at most 40 items")
    ids: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(blocks):
        if not isinstance(raw, dict):
            raise ValueError(f"Review block {index} must be an object")
        block_id = str(raw.get("block_id", "")).strip()
        block_type = str(raw.get("type", "")).strip()
        if not block_id or block_id in ids:
            raise ValueError(f"Review block {index} requires a unique block_id")
        if block_type not in REVIEW_BLOCK_TYPES:
            raise ValueError(f"Review block {block_id} has an unsupported type")
        ids.add(block_id)
        try:
            x, y, width, height = (int(raw[key]) for key in ("x", "y", "w", "h"))
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"Review block {block_id} requires integer x/y/w/h") from error
        if x < 0 or y < 0 or width < 1 or width > 12 or height < 2 or height > 40 or x + width > 12:
            raise ValueError(f"Review block {block_id} is outside the 12-column layout bounds")
        content_html = str(raw.get("content", ""))
        if len(content_html) > 50_000:
            raise ValueError(f"Review block {block_id} content is too long")
        block_title = str(raw.get("title", "")).strip()
        text_align = str(raw.get("text_align", "left")).strip().lower()
        if text_align not in REVIEW_TEXT_ALIGNMENTS:
            raise ValueError(f"Review block {block_id} has an unsupported text alignment")
        if not block_title or len(block_title) > 200:
            raise DocumentValidationError(
                "REVIEW_BLOCK_TITLE_INVALID",
                f"Review block {block_id} requires a title of 1 to 200 characters.",
                f"sections.month_in_review.blocks.{index}.title",
                "Enter a non-empty block title of 200 characters or fewer.",
                block_id,
            )
        normalized.append({
            **raw,
            "block_id": block_id,
            "type": block_type,
            "title": block_title,
            "content": sanitize_review_html(content_html),
            "text_align": text_align,
            "x": x, "y": y, "w": width, "h": height,
        })
    for index, left in enumerate(normalized):
        for right in normalized[index + 1:]:
            horizontal = left["x"] < right["x"] + right["w"] and right["x"] < left["x"] + left["w"]
            vertical = left["y"] < right["y"] + right["h"] and right["y"] < left["y"] + left["h"]
            if horizontal and vertical:
                raise ValueError(f"Review blocks {left['block_id']} and {right['block_id']} overlap")
    ordered = sorted(normalized, key=lambda block: (block["y"], block["x"], block["block_id"]))
    if has_block_schema:
        review["layout_schema_version"] = 2
        review["blocks"] = ordered
        title_block = next((block for block in ordered if block["block_id"] == "summary"), None)
        if title_block:
            review["title"] = title_block["title"]
            review["display_title"] = title_block["title"]
        substantive = [block for block in ordered if _has_substantive_review_text(block)]
        summary = (
            next((block for block in substantive if block["block_id"] == "summary"), None)
            or next((block for block in substantive if block["type"] == "rich_text"), None)
            or next(iter(substantive), None)
        )
        outlook = (
            next((block for block in substantive if block["block_id"] == "outlook"), None)
            or next((block for block in substantive if block["type"] == "outlook"), None)
        )
        # Blocks are canonical once present. Keep legacy fields synchronized so older status
        # checks and renderers cannot retain a placeholder after the editor has saved content.
        review["summary"] = review_plain_text(summary["content"]) if summary else ""
        review["outlook"] = review_plain_text(outlook["content"]) if outlook else ""
    if page_one_presentation.supports(result):
        result = page_one_presentation.canonicalize_document(result)
    return result


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def checksum(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def render_content_manifest(content: dict[str, Any]) -> dict[str, Any]:
    sections = content.get("sections", {})
    facts = {
        "historical_performance": sections.get("historical_performance", {}),
        "company_news": [
            {
                "news_item_id": item.get("news_item_id"),
                "provider": item.get("provider"),
                "external_id": item.get("external_id"),
                "title": item.get("title"),
                "summary": item.get("summary"),
                "source_url": item.get("source_url"),
                "published_at": item.get("published_at"),
                "fetched_at": item.get("fetched_at"),
                "sentiment": item.get("sentiment"),
                "importance_score": item.get("importance_score"),
            }
            for item in sections.get("company_news", [])
        ],
        "constituents": sections.get("constituents", []),
        "analytics": sections.get("analytics", {}),
        "footnotes": sections.get("footnotes", {}),
        "next_rebalancing_date": content.get("next_rebalancing_date"),
    }
    manifest = {
        "document_checksum": checksum(content),
        "language_mode": content.get("language_mode", "EN"),
        "module_bindings": content.get("module_bindings", {}),
        "section_checksums": {key: checksum(value) for key, value in facts.items()},
        "module_order": [
            "month_in_review", "historical_performance", "company_news",
            "constituents", "analytics", "footnotes",
        ],
    }
    return {**manifest, "checksum": checksum(manifest)}


def content_manifests_match(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Compare canonical render content across manifest schema revisions.

    Manifests created before language variants were introduced do not have a
    ``language_mode`` field. Those artifacts are necessarily English, so normalize
    that one legacy omission before comparing the canonical manifest payload. The
    stored checksum itself is excluded because it changes whenever the manifest
    envelope gains a field; every content-bearing field remains part of the
    comparison, including any fields added in future revisions.
    """

    def comparable(manifest: dict[str, Any]) -> dict[str, Any]:
        payload = {key: value for key, value in manifest.items() if key != "checksum"}
        payload.setdefault("language_mode", "EN")
        return payload

    return comparable(left) == comparable(right)


def initial_document(
    report_id: str,
    report_date: date,
    template_version: str,
    design_token_version: str,
    product_ticker: str,
    benchmark_name: str,
    language_mode: str = "EN",
) -> dict[str, Any]:
    month = month_name(report_date, language_mode)
    review_title = (
        f"{month}月度回顧"
        if is_zh_hant(language_mode)
        else f"{month}月度回顾"
        if is_zh_hans(language_mode)
        else f"{month} in Review"
    )
    document = {
        "report_id": report_id,
        "template_version": template_version,
        "design_token_version": design_token_version,
        "lane": "PRODUCTION",
        "language_mode": language_mode,
        "report_date": report_date.isoformat(),
        "month_name": month,
        "product_ticker": product_ticker,
        "benchmark_name": benchmark_name,
        "terminology_overrides": {
            "product_name": "",
            "benchmark_name": "",
            "securities": {},
            "industries": {},
        },
        "next_rebalancing_date": None,
        "next_rebalancing_date_source": "SNAPSHOT",
        "sections": {
            "month_in_review": {
                "title": review_title,
                "display_title": review_title,
                "summary": "" if is_chinese(language_mode) else "Add monthly market review.",
                "drivers": [],
                "monitor": [],
                "outlook": "" if is_chinese(language_mode) else "Add outlook.",
            },
            "historical_performance": {"rows": []},
            "company_news": [],
            "constituents": [],
            "analytics": {"top10": [], "sectors": [], "top": [], "bottom": [], "portfolio": []},
            "footnotes": {},
        },
    }
    return (
        page_one_presentation.adapt_document(document)
        if template_version in {"3033-v3", "3033-v4"}
        else document
    )


def bind_snapshot(
    content: dict[str, Any],
    snapshot_payload: dict[str, Any],
    *,
    lane: str,
    include_testing_editorial: bool = False,
) -> dict[str, Any]:
    result = deepcopy(content)
    # The lane travels with the facts it describes. Stamped here rather than left to the caller so
    # a document can never carry a snapshot's numbers without carrying its lane.
    result["lane"] = lane
    result["sections"]["constituents"] = snapshot_payload.get("constituents", [])
    result["sections"]["historical_performance"] = snapshot_payload.get("historical_performance", {"rows": []})
    if include_testing_editorial and lane != "TESTING":
        raise ValueError("Transcribed editorial may only be bound on the TESTING lane")
    if include_testing_editorial:
        result["sections"]["company_news"] = snapshot_payload.get("company_news", [])
    if include_testing_editorial and snapshot_payload.get("month_in_review"):
        existing_review = result["sections"].get("month_in_review", {})
        incoming_review = deepcopy(snapshot_payload["month_in_review"])
        preserve_blocks = has_substantive_review_blocks(existing_review)
        preserved_fields = ["title", "display_title"]
        if preserve_blocks:
            preserved_fields.extend(["blocks", "layout_schema_version"])
        for field in preserved_fields:
            if field in existing_review:
                incoming_review[field] = deepcopy(existing_review[field])
        incoming_review["provenance"] = {
            "source": "TESTING_FIXTURE",
            "file": "editorial.json",
            "note": "Transcribed from the approved reference report. Not generated, not derived.",
        }
        result["sections"]["month_in_review"] = incoming_review
        if result.get("template_version") in {"3033-v3", "3033-v4"} and not preserve_blocks:
            result = page_one_presentation.adapt_document(result)
    result["sections"]["analytics"] = snapshot_payload.get("analytics", result["sections"]["analytics"])
    result["sections"]["footnotes"] = snapshot_payload.get("footnotes", {})
    result = page_one_presentation.retarget_footnote_styles(result)
    if result.get("next_rebalancing_date_source") != "MANUAL":
        result["next_rebalancing_date"] = snapshot_payload.get("next_rebalancing_date")
        result["next_rebalancing_date_source"] = "SNAPSHOT"
    return result
