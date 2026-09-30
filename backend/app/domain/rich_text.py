"""Safe rich-text normalization shared by the editor and presentation model.

The document JSON stores semantic HTML, never arbitrary CSS.  The small data-attribute
vocabulary below is deliberately renderer-neutral so HTML and DOCX adapters can consume the
same values without parsing user-provided style declarations.
"""

from __future__ import annotations

from html import escape
from html.parser import HTMLParser
import re
from typing import Callable
from urllib.parse import urlparse


FONT_SIZE_MIN_PT = 5.0
FONT_SIZE_MAX_PT = 36.0
LINE_HEIGHT_MIN = 0.8
LINE_HEIGHT_MAX = 3.0
SPACING_MIN_PT = 0.0
SPACING_MAX_PT = 72.0
INDENT_LEVEL_MIN = 0
INDENT_LEVEL_MAX = 6
PARAGRAPH_INDENT_STEP_EM = 2.0
TEXT_ALIGNMENTS = frozenset({"left", "center", "right", "justify"})

_FONT_FAMILY_RE = re.compile(r"^[\w .,'()&+\-/]{1,100}$", re.UNICODE)
_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


class RichTextValidationError(ValueError):
    """An invalid semantic formatting attribute."""


def normalize_number(
    value: object,
    *,
    minimum: float,
    maximum: float,
    field: str,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RichTextValidationError(f"{field} must be a number.")
    normalized = round(float(value), 4)
    if not minimum <= normalized <= maximum:
        raise RichTextValidationError(
            f"{field} must be between {minimum:g} and {maximum:g}."
        )
    return normalized


def normalize_font_family(value: object, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not _FONT_FAMILY_RE.fullmatch(normalized):
        raise RichTextValidationError(
            f"{field} must be a font-family name of 1 to 100 safe characters."
        )
    return normalized


def normalize_color(value: object, *, field: str) -> str:
    normalized = str(value or "")
    if not _COLOR_RE.fullmatch(normalized):
        raise RichTextValidationError(f"{field} must be a #RRGGBB colour.")
    return normalized.upper()


def normalize_indent_level(value: object, *, field: str) -> int:
    normalized = str(value or "")
    if not re.fullmatch(r"\d+", normalized):
        raise RichTextValidationError(f"{field} must be a whole number.")
    level = int(normalized)
    if not INDENT_LEVEL_MIN <= level <= INDENT_LEVEL_MAX:
        raise RichTextValidationError(
            f"{field} must be between {INDENT_LEVEL_MIN} and {INDENT_LEVEL_MAX}."
        )
    return level


def _format_number(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".")


class SafeRichTextSanitizer(HTMLParser):
    allowed_tags = {
        "p", "strong", "em", "u", "span", "ul", "ol", "li", "a", "br", "h2", "h3",
        "blockquote",
    }
    paragraph_attributes = frozenset({
        "data-line-height",
        "data-space-before-pt",
        "data-space-after-pt",
        "data-text-align",
        "data-indent-level",
        # Kept for v3 documents during their compatibility window.
        "data-font-size-role",
        "data-line-height-role",
    })
    span_attributes = frozenset({
        "data-font-family", "data-font-size-pt", "data-color", "data-underline",
    })

    def __init__(
        self,
        *,
        error_factory: Callable[[str], Exception] | None = None,
        legacy_font_roles: frozenset[str] = frozenset(),
        legacy_line_roles: frozenset[str] = frozenset(),
    ) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.error_factory = error_factory or RichTextValidationError
        self.legacy_font_roles = legacy_font_roles
        self.legacy_line_roles = legacy_line_roles

    def _error(self, message: str) -> None:
        raise self.error_factory(message)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag == "font" or any(
            key.casefold() == "style" or key.casefold().startswith("on") for key, _ in attrs
        ):
            self._error("Rich text cannot contain inline CSS, event handlers, or font tags.")
        if tag not in self.allowed_tags:
            return
        if tag in {"p", "li", "h2", "h3", "blockquote"}:
            normalized = self._normalize_attributes(tag, attrs, self.paragraph_attributes)
            self.parts.append(f"<{tag}{normalized}>")
            return
        if tag == "span":
            normalized = self._normalize_attributes(tag, attrs, self.span_attributes)
            self.parts.append(f"<span{normalized}>")
            return
        if tag == "a":
            unsupported = [key for key, _ in attrs if key.casefold() != "href"]
            if unsupported:
                self._error(f"Rich-text link contains unsupported attribute {unsupported[0]!r}.")
            href = next((value for key, value in attrs if key.casefold() == "href"), None)
            parsed = urlparse(href or "")
            if parsed.scheme in {"http", "https", "mailto"}:
                self.parts.append(f'<a href="{escape(href or "", quote=True)}">')
            else:
                self.parts.append("<a>")
            return
        if attrs:
            self._error(f"Rich-text {tag} does not accept attributes.")
        self.parts.append(f"<{tag}>")

    def _normalize_attributes(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
        allowed: frozenset[str],
    ) -> str:
        normalized: list[tuple[str, str]] = []
        seen: set[str] = set()
        for raw_key, raw_value in attrs:
            key = raw_key.casefold()
            if key in seen or key not in allowed:
                self._error(f"Rich-text {tag} contains unsupported formatting attribute {key!r}.")
            seen.add(key)
            value = str(raw_value or "")
            try:
                if key == "data-font-family":
                    value = normalize_font_family(value, field=key)
                elif key == "data-font-size-pt":
                    value = _format_number(normalize_number(
                        float(value), minimum=FONT_SIZE_MIN_PT, maximum=FONT_SIZE_MAX_PT, field=key
                    ))
                elif key == "data-color":
                    value = normalize_color(value, field=key)
                elif key == "data-underline":
                    if value not in {"true", "false"}:
                        raise RichTextValidationError(f"{key} must be true or false.")
                elif key == "data-line-height":
                    value = _format_number(normalize_number(
                        float(value), minimum=LINE_HEIGHT_MIN, maximum=LINE_HEIGHT_MAX, field=key
                    ))
                elif key in {"data-space-before-pt", "data-space-after-pt"}:
                    value = _format_number(normalize_number(
                        float(value), minimum=SPACING_MIN_PT, maximum=SPACING_MAX_PT, field=key
                    ))
                elif key == "data-text-align":
                    value = value.casefold()
                    if value not in TEXT_ALIGNMENTS:
                        raise RichTextValidationError(f"Unsupported alignment {value!r}.")
                elif key == "data-indent-level":
                    value = str(normalize_indent_level(value, field=key))
                elif key == "data-font-size-role" and value not in self.legacy_font_roles:
                    raise RichTextValidationError(
                        f"Rich text contains unsupported value {value!r} for {key}."
                    )
                elif key == "data-line-height-role" and value not in self.legacy_line_roles:
                    raise RichTextValidationError(
                        f"Rich text contains unsupported value {value!r} for {key}."
                    )
            except (ValueError, RichTextValidationError) as error:
                self._error(str(error))
            normalized.append((key, value))
        return "".join(
            f' {key}="{escape(value, quote=True)}"' for key, value in sorted(normalized)
        )

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in self.allowed_tags and tag != "br":
            self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self.parts.append(escape(data))


def sanitize_rich_text(
    value: str,
    *,
    error_factory: Callable[[str], Exception] | None = None,
    legacy_font_roles: frozenset[str] = frozenset(),
    legacy_line_roles: frozenset[str] = frozenset(),
) -> str:
    sanitizer = SafeRichTextSanitizer(
        error_factory=error_factory,
        legacy_font_roles=legacy_font_roles,
        legacy_line_roles=legacy_line_roles,
    )
    sanitizer.feed(value)
    sanitizer.close()
    return "".join(sanitizer.parts)


class RichTextPlainExtractor(HTMLParser):
    block_tags = {"p", "li", "h2", "h3", "blockquote"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[str] = []
        self.current: list[str] = []

    def handle_data(self, data: str) -> None:
        self.current.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() == "br":
            self.current.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in self.block_tags:
            self._flush()

    def close(self) -> None:
        super().close()
        self._flush()

    def _flush(self) -> None:
        value = "".join(self.current).strip()
        if value:
            self.paragraphs.append(value)
        self.current = []


def rich_text_plain_text(value: str, *, preserve_paragraphs: bool = False) -> str:
    extractor = RichTextPlainExtractor()
    extractor.feed(value)
    extractor.close()
    separator = "\n\n" if preserve_paragraphs else " "
    return separator.join(extractor.paragraphs)


def plain_text_to_rich_text(value: object) -> str:
    text = str(value or "").replace("\r\n", "\n")
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if not paragraphs:
        return "<p></p>"
    return "".join(
        f"<p>{escape(paragraph).replace(chr(10), '<br>')}</p>" for paragraph in paragraphs
    )


class RendererRichTextAdapter(HTMLParser):
    """Translate validated semantic attributes to renderer-safe inline declarations."""

    void_tags = {"br"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        attr_map = {key: str(value or "") for key, value in attrs}
        declarations: list[str] = []
        generated_attributes: list[tuple[str, str]] = []
        if "data-font-family" in attr_map:
            requested_font = attr_map["data-font-family"]
            bundled_fonts = {
                "carlito", "calibri", "noto sans cjk sc", "noto sans cjk tc",
                "noto sans cjk hk", "noto serif cjk sc", "noto serif cjk tc",
                "noto serif cjk hk",
            }
            rendered_font = "Carlito" if requested_font.casefold() == "calibri" else (
                requested_font if requested_font.casefold() in bundled_fonts else "Carlito"
            )
            declarations.append(f"font-family:{rendered_font}")
            generated_attributes.append(("data-requested-font", requested_font))
        if "data-font-size-pt" in attr_map:
            declarations.append(f"font-size:{attr_map['data-font-size-pt']}pt")
        if "data-color" in attr_map:
            declarations.append(f"color:{attr_map['data-color']}")
        if attr_map.get("data-underline") == "true":
            declarations.append("text-decoration:underline")
        if "data-line-height" in attr_map:
            declarations.append(f"line-height:{attr_map['data-line-height']}")
        if "data-space-before-pt" in attr_map:
            declarations.append(f"margin-top:{attr_map['data-space-before-pt']}pt")
        if "data-space-after-pt" in attr_map:
            declarations.append(f"margin-bottom:{attr_map['data-space-after-pt']}pt")
        if "data-text-align" in attr_map:
            declarations.append(f"text-align:{attr_map['data-text-align']}")
        if "data-indent-level" in attr_map:
            indent_level = normalize_indent_level(
                attr_map["data-indent-level"], field="data-indent-level"
            )
            if indent_level:
                declarations.append(
                    f"margin-left:{_format_number(indent_level * PARAGRAPH_INDENT_STEP_EM)}em"
                )
        # v3 role attributes remain data attributes so the established stylesheet keeps working.
        preserved = generated_attributes + [
            (key, value) for key, value in attrs
            if key in {
                "href", "data-font-size-role", "data-line-height-role", "data-indent-level",
            }
        ]
        serialized = "".join(
            f' {key}="{escape(str(value or ""), quote=True)}"' for key, value in preserved
        )
        if declarations:
            serialized += f' style="{escape(";".join(declarations), quote=True)}"'
        self.parts.append(f"<{tag}{serialized}>")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() not in self.void_tags:
            self.parts.append(f"</{tag.casefold()}>")

    def handle_data(self, data: str) -> None:
        self.parts.append(escape(data))


def render_safe_rich_text(value: str) -> str:
    adapter = RendererRichTextAdapter()
    adapter.feed(value)
    adapter.close()
    return "".join(adapter.parts)
