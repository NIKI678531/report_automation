import hashlib
import json
from copy import deepcopy
from datetime import date
from html import escape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse


REVIEW_BLOCK_TYPES = {"rich_text", "heading", "bullet_list", "key_drivers", "areas_to_monitor", "outlook", "metric_callout", "image", "data_table", "page_break"}


class DocumentValidationError(ValueError):
    def __init__(self, error_code: str, message: str, field: str, fix_hint: str, entity_id: str | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.field = field
        self.entity_id = entity_id
        self.fix_hint = fix_hint


class ReviewHtmlSanitizer(HTMLParser):
    allowed_tags = {"p", "strong", "em", "ul", "ol", "li", "a", "br", "h2", "h3", "blockquote"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in self.allowed_tags:
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
    sanitizer = ReviewHtmlSanitizer()
    sanitizer.feed(value)
    sanitizer.close()
    return "".join(sanitizer.parts)


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
    blocks = review.get("blocks")
    if blocks is None:
        return result
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
            "x": x, "y": y, "w": width, "h": height,
        })
    for index, left in enumerate(normalized):
        for right in normalized[index + 1:]:
            horizontal = left["x"] < right["x"] + right["w"] and right["x"] < left["x"] + left["w"]
            vertical = left["y"] < right["y"] + right["h"] and right["y"] < left["y"] + left["h"]
            if horizontal and vertical:
                raise ValueError(f"Review blocks {left['block_id']} and {right['block_id']} overlap")
    review["layout_schema_version"] = 2
    review["blocks"] = sorted(normalized, key=lambda block: (block["y"], block["x"], block["block_id"]))
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
                "title": item.get("title"),
                "summary": item.get("summary"),
                "source_url": item.get("source_url"),
                "published_at": item.get("published_at"),
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
        "module_bindings": content.get("module_bindings", {}),
        "section_checksums": {key: checksum(value) for key, value in facts.items()},
        "module_order": [
            "month_in_review", "historical_performance", "company_news",
            "constituents", "analytics", "footnotes",
        ],
    }
    return {**manifest, "checksum": checksum(manifest)}


def initial_document(
    report_id: str,
    report_date: date,
    template_version: str,
    design_token_version: str,
    product_ticker: str,
    benchmark_name: str,
) -> dict[str, Any]:
    month = report_date.strftime("%B")
    return {
        "report_id": report_id,
        "template_version": template_version,
        "design_token_version": design_token_version,
        "language_mode": "EN",
        "report_date": report_date.isoformat(),
        "month_name": month,
        "product_ticker": product_ticker,
        "benchmark_name": benchmark_name,
        "next_rebalancing_date": None,
        "sections": {
            "month_in_review": {
                "title": f"{month} in Review",
                "display_title": f"{month} in Review",
                "summary": "Add monthly market review.",
                "drivers": [],
                "monitor": [],
                "outlook": "Add outlook.",
            },
            "historical_performance": {"rows": []},
            "company_news": [],
            "constituents": [],
            "analytics": {"top10": [], "sectors": [], "top": [], "bottom": [], "portfolio": []},
            "footnotes": {},
        },
    }


def bind_snapshot(content: dict[str, Any], snapshot_payload: dict[str, Any], include_editorial: bool = False) -> dict[str, Any]:
    result = deepcopy(content)
    result["sections"]["constituents"] = snapshot_payload.get("constituents", [])
    result["sections"]["historical_performance"] = snapshot_payload.get("historical_performance", {"rows": []})
    if include_editorial:
        result["sections"]["company_news"] = snapshot_payload.get("company_news", [])
    if include_editorial and snapshot_payload.get("month_in_review"):
        existing_review = result["sections"].get("month_in_review", {})
        incoming_review = deepcopy(snapshot_payload["month_in_review"])
        for field in ("title", "display_title", "blocks", "layout_schema_version"):
            if field in existing_review:
                incoming_review[field] = deepcopy(existing_review[field])
        result["sections"]["month_in_review"] = incoming_review
    result["sections"]["analytics"] = snapshot_payload.get("analytics", result["sections"]["analytics"])
    result["sections"]["footnotes"] = snapshot_payload.get("footnotes", {})
    result["next_rebalancing_date"] = snapshot_payload.get("next_rebalancing_date")
    return result
