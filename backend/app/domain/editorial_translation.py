from __future__ import annotations

import re
from collections import Counter
from copy import deepcopy
from datetime import date
from html import escape
from html.parser import HTMLParser
from typing import Callable

from .document import checksum, review_plain_text, sanitize_review_html, validate_document_content
from .localization import month_name, simplified_to_traditional, traditional_to_simplified


PROMPT_VERSION = "review-translation-v1"
_TOKEN = re.compile(r"https?://[^\s<>]+|\b[A-Z][A-Z0-9._/-]*\b|[-+\u2212]?\d[\d,./:%\uFF05-]*(?:\s?(?:million|billion|万|萬|亿|億|%))?")
_MARKER = re.compile(r"\[\[KEEP_\d+\]\]")
_NUMBER = re.compile(r"\d")
_DEFAULTS = {
    "summary": {"EN": "Monthly Review", "ZH_HANS": "月度回顾", "ZH_HANT": "月度回顧"},
    "drivers": {"EN": "Key Drivers", "ZH_HANS": "主要驱动因素", "ZH_HANT": "主要驅動因素"},
    "monitor": {"EN": "Key Areas to Monitor", "ZH_HANS": "重点关注领域", "ZH_HANT": "重點關注領域"},
    "outlook": {"EN": "Outlook", "ZH_HANS": "展望", "ZH_HANT": "展望"},
}
_PLACEHOLDERS = {"", "Add monthly market review.", "Add outlook.", "No content yet.", "Start writing..."}


def default_review_titles(content: dict) -> dict[str, str]:
    period = date.fromisoformat(content["report_date"])
    return {language: f"{month_name(period, language)}{suffix}" for language, suffix in (("EN", " in Review"), ("ZH_HANS", "月度回顾"), ("ZH_HANT", "月度回顧"))}


def translated_review_text(content: dict) -> list[str]:
    review = content.get("sections", {}).get("month_in_review", {})
    fields = (content.get("translation_provenance") or {}).get("fields") or {}
    values = {f"sections.month_in_review.{field}": review.get(field, "") for field in ("title", "display_title", "summary", "outlook")}
    for block in review.get("blocks") or []:
        for field in ("title", "content"):
            values[f"sections.month_in_review.blocks.{block['block_id']}.{field}"] = block.get(field, "")
    for collection in ("drivers", "monitor"):
        for index, item in enumerate(review.get(collection) or []):
            for field in ("title", "body"):
                values[f"sections.month_in_review.{collection}.{index}.{field}"] = item.get(field, "")
    return [review_plain_text(str(value)) for path, value in values.items() if fields.get(path, {}).get("method") == "OPENAI_COMPATIBLE" and fields[path].get("state") == "GENERATED" and fields[path].get("target_checksum") == checksum(value)]


class TranslationError(Exception):
    def __init__(self, code: str, *, retryable: bool = False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class ProtectedText(HTMLParser):
    def __init__(self, value: str, *, html: bool):
        super().__init__(convert_charrefs=True)
        self.html = html
        self.parts: list[tuple[str, str]] = []
        self.texts: dict[str, str] = {}
        self.tokens: dict[str, list[str]] = {}
        if html:
            self.feed(sanitize_review_html(value))
            self.close()
        else:
            self.handle_data(value)

    def handle_starttag(self, tag, attrs):
        self.parts.append(("html", self.get_starttag_text()))

    def handle_endtag(self, tag):
        self.parts.append(("html", f"</{tag}>"))

    def handle_data(self, data):
        if _MARKER.search(data):
            raise TranslationError("TRANSLATION_RESERVED_TOKEN")
        key = str(len(self.texts))
        tokens: list[str] = []

        def protect(match):
            tokens.append(match.group(0))
            return f"[[KEEP_{len(tokens) - 1}]]"

        self.texts[key] = _TOKEN.sub(protect, data)
        self.tokens[key] = tokens
        self.parts.append(("text", key))

    def restore(self, translated: dict[str, str]) -> str:
        if set(translated) != set(self.texts):
            raise TranslationError("TRANSLATION_INVALID_RESPONSE")
        restored: dict[str, str] = {}
        for key, value in translated.items():
            if not isinstance(value, str) or (self.texts[key].strip() and not value.strip()):
                raise TranslationError("TRANSLATION_INVALID_RESPONSE")
            expected = _MARKER.findall(self.texts[key])
            if _MARKER.findall(value) != expected or _NUMBER.search(_MARKER.sub("", value)):
                raise TranslationError("TRANSLATION_FACT_CHANGED")
            if "<" in value or ">" in value:
                raise TranslationError("TRANSLATION_INVALID_RESPONSE")
            restored[key] = _MARKER.sub(lambda match: self.tokens[key][int(match.group(0)[7:-2])], value)
        return "".join(value if kind == "html" else escape(restored[value]) if self.html else restored[value] for kind, value in self.parts)


def translate_review(
    source_content: dict,
    target_content: dict,
    *,
    source_id: str,
    target_id: str,
    source_version: int,
    source_language: str,
    target_language: str,
    model: str,
    translate: Callable[[dict[str, str], str, str], dict[str, str]],
) -> tuple[dict, list[str]]:
    result = deepcopy(target_content)
    source_review = source_content["sections"]["month_in_review"]
    target_review = result["sections"]["month_in_review"]
    provenance = result.setdefault("translation_provenance", {})
    fields = provenance.setdefault("fields", {})
    source_fields = (source_content.get("translation_provenance") or {}).get("fields") or {}
    preserved: list[str] = []
    pending: list[tuple[str, dict, str, str, ProtectedText]] = []
    inputs: dict[str, str] = {}
    monthly_titles = default_review_titles(target_content)

    def merge(path: str, source: dict, target: dict, name: str, *, html=False, defaults=()):
        original = str(source.get(name) or "")
        current = str(target.get(name) or "")
        old = fields.get(path) or {}
        reverse = source_fields.get(path) or {}
        if reverse.get("source_report_id") == target_id and reverse.get("source_checksum") == checksum(current) and reverse.get("target_checksum") == checksum(original):
            return
        if old.get("source_report_id") == source_id and old.get("source_checksum") == checksum(original) and old.get("target_checksum") == checksum(current):
            return
        generated = old.get("target_checksum") == checksum(current) and old.get("state") != "MANUAL_PRESERVED"
        blank = review_plain_text(current) in _PLACEHOLDERS
        if not (blank or generated or current in defaults):
            if old.get("source_report_id") != source_id or old.get("source_checksum") != checksum(original):
                preserved.append(path)
                fields[path] = {**old, "state": "MANUAL_PRESERVED", "source_report_id": source_id, "source_checksum": checksum(original)}
            elif old.get("state") == "MANUAL_PRESERVED":
                preserved.append(path)
            return
        if review_plain_text(original) in _PLACEHOLDERS:
            return
        protected = ProtectedText(original, html=html)
        prefix = str(len(pending))
        inputs.update({f"{prefix}:{key}": value for key, value in protected.texts.items()})
        pending.append((path, target, name, original, protected))

    source_blocks = source_review.get("blocks")
    if not source_blocks and target_review.get("blocks"):
        source_blocks = []
        for block_id in ("summary", "drivers", "monitor", "outlook"):
            if block_id in {"drivers", "monitor"}:
                text = "<ul>" + "".join(f"<li><strong>{escape(str(item.get('title') or ''))}</strong><p>{escape(str(item.get('body') or ''))}</p></li>" for item in source_review.get(block_id) or []) + "</ul>"
            else:
                text = f"<p>{escape(str(source_review.get(block_id) or ''))}</p>"
            source_blocks.append({"block_id": block_id, "type": "rich_text", "title": source_review.get("display_title") or source_review.get("title") if block_id == "summary" else _DEFAULTS[block_id][source_language], "content": text})
    if isinstance(source_blocks, list) and source_blocks:
        targets = {block["block_id"]: block for block in target_review.get("blocks") or []}
        source_ids = {block["block_id"] for block in source_blocks}
        preserved.extend(f"blocks.{block_id}" for block_id in targets if block_id not in source_ids)
        for block in source_blocks:
            block_id = block["block_id"]
            target = targets.get(block_id)
            if target is None:
                preserved.append(f"blocks.{block_id}")
                continue
            defaults = _DEFAULTS.get(block_id, {})
            known_titles = tuple(defaults.values()) + (tuple(monthly_titles.values()) + ("Monthly summary",) if block_id == "summary" else ())
            path = f"sections.month_in_review.blocks.{block_id}"
            if block.get("title") in known_titles and target.get("title") in known_titles:
                target["title"] = monthly_titles[target_language] if block_id == "summary" else defaults[target_language]
            else:
                merge(f"{path}.title", block, target, "title", defaults=known_titles + ("Untitled section", "未命名区块", "未命名區塊"))
            if block.get("type", "rich_text") in {"rich_text", "key_drivers", "areas_to_monitor", "outlook", "heading", "bullet_list"}:
                merge(f"{path}.content", block, target, "content", html=True)
    else:
        for field in ("display_title", "title", "summary", "outlook"):
            defaults = tuple(monthly_titles.values()) if field in {"display_title", "title"} else ()
            if source_review.get(field) in defaults and target_review.get(field) in defaults:
                target_review[field] = monthly_titles[target_language]
            else:
                merge(f"sections.month_in_review.{field}", source_review, target_review, field, defaults=defaults)
        for collection in ("drivers", "monitor"):
            source_items = source_review.get(collection) or []
            target_items = target_review.setdefault(collection, [])
            while len(target_items) < len(source_items):
                target_items.append({})
            for index, item in enumerate(source_items):
                for field in ("title", "body"):
                    merge(f"sections.month_in_review.{collection}.{index}.{field}", item, target_items[index], field)

    outputs = translate(inputs, source_language, target_language) if inputs else {}
    if not isinstance(outputs, dict) or set(outputs) != set(inputs):
        raise TranslationError("TRANSLATION_INVALID_RESPONSE")
    if any(not isinstance(value, str) for value in outputs.values()):
        raise TranslationError("TRANSLATION_INVALID_RESPONSE")
    source_prose = _MARKER.sub("", " ".join(inputs.values()))
    target_prose = _MARKER.sub("", " ".join(outputs.values()))
    if target_language == "EN" and re.search(r"[\u3400-\u9fff]", target_prose):
        raise TranslationError("TRANSLATION_LANGUAGE_MISMATCH")
    if target_language != "EN" and re.search(r"[a-z]{2,}\s+[A-Za-z]", source_prose) and not re.search(r"[\u3400-\u9fff]", target_prose):
        raise TranslationError("TRANSLATION_LANGUAGE_MISMATCH")
    for index, (path, target, name, original, protected) in enumerate(pending):
        fragments = {key: outputs[f"{index}:{key}"] for key in protected.texts}
        if any(not isinstance(value, str) for value in fragments.values()):
            raise TranslationError("TRANSLATION_INVALID_RESPONSE")
        if target_language in {"ZH_HANS", "ZH_HANT"}:
            convert = traditional_to_simplified if target_language == "ZH_HANS" else simplified_to_traditional
            fragments = {key: re.sub(r"\S(?:.*\S)?", lambda match: convert(match.group(0)), value, flags=re.DOTALL) for key, value in fragments.items()}
        converted = protected.restore(fragments)
        if Counter(_TOKEN.findall(review_plain_text(original))) != Counter(_TOKEN.findall(review_plain_text(converted))):
            raise TranslationError("TRANSLATION_FACT_CHANGED")
        target[name] = converted
        fields[path] = {
            "method": "OPENAI_COMPATIBLE", "model": model, "prompt_version": PROMPT_VERSION,
            "source_report_id": source_id, "source_document_version": source_version,
            "source_checksum": checksum(original), "target_checksum": checksum(converted), "state": "GENERATED",
        }
    return validate_document_content(result), preserved