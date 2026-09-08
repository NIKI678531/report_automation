import pytest

from app.rendering.artifacts import renderer_version_for
from app.rendering.html import _review_flow_layout


def block(block_id: str, x: int, y: int, width: int, height: int) -> dict:
    return {
        "block_id": block_id,
        "type": "rich_text",
        "title": block_id,
        "content": f"<p>{block_id}</p>",
        "x": x,
        "y": y,
        "w": width,
        "h": height,
    }


def leaf_ids(node: dict) -> list[str]:
    if node["kind"] == "block":
        return [node["block"]["block_id"]]
    return [block_id for child in node["children"] for block_id in leaf_ids(child)]


def test_review_flow_keeps_staggered_columns_as_independent_stacks():
    layout = _review_flow_layout([
        block("summary", 0, 0, 12, 4),
        block("drivers", 0, 4, 6, 7),
        block("monitor", 6, 4, 6, 5),
        block("outlook", 6, 9, 6, 4),
    ])

    assert layout["kind"] == "stack"
    assert layout["children"][0]["block"]["block_id"] == "summary"
    columns = layout["children"][1]
    assert columns["kind"] == "columns"
    assert [child["w"] for child in columns["children"]] == [6, 6]
    assert leaf_ids(columns["children"][0]) == ["drivers"]
    assert leaf_ids(columns["children"][1]) == ["monitor", "outlook"]


@pytest.mark.parametrize("widths", [(12,), (6, 6), (4, 8), (8, 4), (4, 4, 4)])
def test_review_flow_preserves_supported_column_widths(widths):
    x = 0
    blocks = []
    for index, width in enumerate(widths):
        blocks.append(block(f"block-{index}", x, 0, width, 4))
        x += width

    layout = _review_flow_layout(blocks)

    if len(widths) == 1:
        assert layout["kind"] == "block"
        assert layout["w"] == widths[0]
    else:
        assert layout["kind"] == "columns"
        assert [child["w"] for child in layout["children"]] == list(widths)


def test_review_flow_uses_stable_rows_for_a_non_slicing_layout():
    layout = _review_flow_layout([
        block("top", 0, 0, 8, 2),
        block("right", 8, 0, 4, 8),
        block("center", 4, 2, 4, 6),
        block("left", 0, 4, 4, 8),
        block("bottom", 4, 8, 8, 4),
    ])

    assert layout["kind"] == "fallback"
    assert leaf_ids(layout) == ["top", "right", "center", "left", "bottom"]


def test_compact_html_and_pdf_have_new_renderer_identities():
    assert renderer_version_for("html") == "html-continuous-i18n-v3"
    assert renderer_version_for("pdf").endswith("-paged-i18n-v3")
    assert renderer_version_for("docx") == "docx-paged-i18n-v3"
