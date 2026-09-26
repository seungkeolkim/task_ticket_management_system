"""Tiptap body schema v2 validation and deterministic rendering utilities."""

from __future__ import annotations

import hashlib
import html
import json
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit

import bleach
from bleach.css_sanitizer import CSSSanitizer

BODY_SCHEMA_VERSION = 2
EMPTY_BODY_DOCUMENT_JSON = '{"content":[{"type":"paragraph"}],"type":"doc"}'
MAX_DOCUMENT_BYTES = 256_000
MAX_DOCUMENT_DEPTH = 20
MAX_DOCUMENT_NODES = 2_000
MAX_DOCUMENT_TEXT_LENGTH = 100_000

ALLOWED_COLORS = frozenset(
    {
        "#111827",
        "#374151",
        "#6b7280",
        "#b91c1c",
        "#c2410c",
        "#a16207",
        "#15803d",
        "#0369a1",
        "#1d4ed8",
        "#6d28d9",
    }
)
ALLOWED_FONT_SIZES = frozenset({"12px", "14px", "16px", "18px", "24px", "32px"})

BLOCK_NODE_TYPES = frozenset(
    {
        "paragraph",
        "heading",
        "bulletList",
        "orderedList",
        "taskList",
        "blockquote",
        "codeBlock",
        "table",
        "image",
    }
)
INLINE_NODE_TYPES = frozenset({"text", "hardBreak"})
MARK_ORDER = {
    "bold": 0,
    "italic": 1,
    "underline": 2,
    "strike": 3,
    "code": 4,
    "textStyle": 5,
    "link": 6,
}

_SANITIZER_TAGS = frozenset(
    {
        "p",
        "h1",
        "h2",
        "h3",
        "strong",
        "em",
        "u",
        "s",
        "code",
        "pre",
        "br",
        "span",
        "a",
        "ul",
        "ol",
        "li",
        "blockquote",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "input",
        "img",
    }
)
_SANITIZER_ATTRIBUTES = {
    "a": ["href", "target", "rel"],
    "span": ["style"],
    "ol": ["start"],
    "li": ["data-checked"],
    "input": ["type", "checked", "disabled"],
    "th": ["colspan", "rowspan"],
    "td": ["colspan", "rowspan"],
    "img": ["src", "alt", "title", "data-attachment-id"],
}
_CSS_SANITIZER = CSSSanitizer(allowed_css_properties=["color", "font-size"])


def empty_body_document() -> dict[str, Any]:
    """새 본문에 사용하는 canonical 빈 Tiptap document를 반환한다."""
    return {"type": "doc", "content": [{"type": "paragraph"}]}


def canonical_body_document_json(document: object) -> str:
    """검증된 document를 안정적인 key 순서의 JSON 문자열로 직렬화한다."""
    normalized_document = validate_body_document(document)
    return json.dumps(
        normalized_document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def body_document_digest(document: object) -> str:
    """canonical document의 SHA-256 digest를 반환한다."""
    canonical_json = canonical_body_document_json(document)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def validate_body_document(document: object) -> dict[str, Any]:
    """Tiptap JSON document를 schema v2 allowlist에 따라 검증하고 정규화한다."""
    try:
        serialized = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise ValueError("본문은 JSON으로 직렬화할 수 있어야 합니다.") from error
    if len(serialized.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise ValueError("본문 JSON 크기가 허용 범위를 초과했습니다.")
    if not isinstance(document, dict) or document.get("type") != "doc":
        raise ValueError("본문 최상위 node는 doc이어야 합니다.")
    if set(document) - {"type", "content"}:
        raise ValueError("본문 최상위에 허용되지 않은 속성이 있습니다.")

    content = document.get("content", [])
    if not isinstance(content, list):
        raise ValueError("본문 content는 배열이어야 합니다.")
    if not content:
        content = [{"type": "paragraph"}]

    counters = {"nodes": 1, "text_length": 0}
    normalized_content = [
        _normalize_node(node, parent_type="doc", depth=2, counters=counters)
        for node in content
    ]
    return {"type": "doc", "content": normalized_content}


def render_body_document_html(document: object) -> str:
    """검증된 Tiptap document를 allowlist sanitizer를 거친 HTML로 변환한다."""
    normalized_document = validate_body_document(document)
    rendered = "".join(_render_node(node) for node in normalized_document["content"])
    return bleach.clean(
        rendered,
        tags=_SANITIZER_TAGS,
        attributes=_SANITIZER_ATTRIBUTES,
        protocols={"http", "https"},
        css_sanitizer=_CSS_SANITIZER,
        strip=True,
        strip_comments=True,
    )


def extract_body_document_text(document: object) -> str:
    """검증된 Tiptap document에서 검색·목록용 plain text를 추출한다."""
    normalized_document = validate_body_document(document)
    blocks = [_extract_node_text(node).strip() for node in normalized_document["content"]]
    return "\n".join(block for block in blocks if block).strip()


def iter_attachment_ids(document: object) -> Iterable[int]:
    """document의 내부 image node가 참조하는 attachment ID를 반환한다."""
    normalized_document = validate_body_document(document)
    yield from _iter_attachment_ids(normalized_document)


def _normalize_node(
    node: object, *, parent_type: str, depth: int, counters: dict[str, int]
) -> dict[str, Any]:
    """단일 node와 하위 node를 검증하고 canonical mapping으로 변환한다."""
    if depth > MAX_DOCUMENT_DEPTH:
        raise ValueError("본문 node 중첩 깊이가 허용 범위를 초과했습니다.")
    counters["nodes"] += 1
    if counters["nodes"] > MAX_DOCUMENT_NODES:
        raise ValueError("본문 node 수가 허용 범위를 초과했습니다.")
    if not isinstance(node, dict):
        raise ValueError("본문 node는 객체여야 합니다.")
    node_type = node.get("type")
    if not isinstance(node_type, str):
        raise ValueError("본문 node type이 필요합니다.")
    if set(node) - {"type", "attrs", "content", "marks", "text"}:
        raise ValueError(f"{node_type} node에 허용되지 않은 속성이 있습니다.")
    _validate_child_type(parent_type, node_type)

    if node_type == "text":
        return _normalize_text_node(node, parent_type, counters)
    if "text" in node or "marks" in node:
        raise ValueError(f"{node_type} node에는 text 또는 marks를 직접 지정할 수 없습니다.")

    normalized_node: dict[str, Any] = {"type": node_type}
    normalized_attributes = _normalize_node_attributes(node_type, node.get("attrs"))
    if normalized_attributes:
        normalized_node["attrs"] = normalized_attributes

    content = node.get("content", [])
    if not isinstance(content, list):
        raise ValueError(f"{node_type} node의 content는 배열이어야 합니다.")
    if node_type in {"hardBreak", "image"} and content:
        raise ValueError(f"{node_type} node는 하위 content를 가질 수 없습니다.")
    nodes_requiring_content = {
        "bulletList",
        "orderedList",
        "taskList",
        "listItem",
        "taskItem",
        "table",
        "tableRow",
        "tableHeader",
        "tableCell",
    }
    if node_type in nodes_requiring_content and not content:
        raise ValueError(f"{node_type} node에는 하위 content가 필요합니다.")
    if content:
        normalized_node["content"] = [
            _normalize_node(child, parent_type=node_type, depth=depth + 1, counters=counters)
            for child in content
        ]
    return normalized_node


def _validate_child_type(parent_type: str, child_type: str) -> None:
    """부모 node가 허용하는 자식 node type인지 검증한다."""
    allowed_children = {
        "doc": BLOCK_NODE_TYPES,
        "paragraph": INLINE_NODE_TYPES,
        "heading": INLINE_NODE_TYPES,
        "blockquote": BLOCK_NODE_TYPES,
        "codeBlock": {"text"},
        "bulletList": {"listItem"},
        "orderedList": {"listItem"},
        "taskList": {"taskItem"},
        "listItem": BLOCK_NODE_TYPES - {"table"},
        "taskItem": BLOCK_NODE_TYPES - {"table"},
        "table": {"tableRow"},
        "tableRow": {"tableHeader", "tableCell"},
        "tableHeader": BLOCK_NODE_TYPES - {"table"},
        "tableCell": BLOCK_NODE_TYPES - {"table"},
    }
    if child_type not in allowed_children.get(parent_type, set()):
        raise ValueError(f"{parent_type} node 안에 {child_type} node를 사용할 수 없습니다.")


def _normalize_text_node(
    node: dict[str, Any], parent_type: str, counters: dict[str, int]
) -> dict[str, Any]:
    """text node와 mark 목록을 검증하고 정규화한다."""
    if "attrs" in node or "content" in node:
        raise ValueError("text node에는 attrs 또는 content를 지정할 수 없습니다.")
    text_value = node.get("text")
    if not isinstance(text_value, str) or not text_value:
        raise ValueError("text node에는 비어 있지 않은 문자열이 필요합니다.")
    counters["text_length"] += len(text_value)
    if counters["text_length"] > MAX_DOCUMENT_TEXT_LENGTH:
        raise ValueError("본문 전체 text 길이가 허용 범위를 초과했습니다.")

    normalized_node: dict[str, Any] = {"type": "text", "text": text_value}
    marks = node.get("marks", [])
    if not isinstance(marks, list):
        raise ValueError("text node의 marks는 배열이어야 합니다.")
    if parent_type == "codeBlock" and marks:
        raise ValueError("codeBlock의 text node에는 mark를 지정할 수 없습니다.")
    normalized_marks = [_normalize_mark(mark) for mark in marks]
    mark_types = [mark["type"] for mark in normalized_marks]
    if len(mark_types) != len(set(mark_types)):
        raise ValueError("같은 mark를 한 text node에 중복 지정할 수 없습니다.")
    if "code" in mark_types and len(mark_types) > 1:
        raise ValueError("inline code에는 다른 mark를 함께 사용할 수 없습니다.")
    if normalized_marks:
        normalized_node["marks"] = sorted(
            normalized_marks, key=lambda mark: MARK_ORDER[mark["type"]]
        )
    return normalized_node


def _normalize_mark(mark: object) -> dict[str, Any]:
    """단일 text mark를 allowlist에 따라 정규화한다."""
    if not isinstance(mark, dict) or not isinstance(mark.get("type"), str):
        raise ValueError("mark는 type을 가진 객체여야 합니다.")
    mark_type = mark["type"]
    if mark_type not in MARK_ORDER:
        raise ValueError(f"허용되지 않은 mark입니다: {mark_type}")
    if set(mark) - {"type", "attrs"}:
        raise ValueError(f"{mark_type} mark에 허용되지 않은 속성이 있습니다.")
    raw_attributes = mark.get("attrs")
    if mark_type in {"bold", "italic", "underline", "strike", "code"}:
        if raw_attributes not in (None, {}):
            raise ValueError(f"{mark_type} mark에는 attrs를 지정할 수 없습니다.")
        return {"type": mark_type}
    if not isinstance(raw_attributes, dict):
        raise ValueError(f"{mark_type} mark에는 attrs가 필요합니다.")
    if mark_type == "link":
        return {"type": "link", "attrs": _normalize_link_attributes(raw_attributes)}
    return {"type": "textStyle", "attrs": _normalize_text_style_attributes(raw_attributes)}


def _normalize_link_attributes(attributes: dict[str, Any]) -> dict[str, Any]:
    """link mark의 URL과 제한된 속성을 검증한다."""
    if set(attributes) - {"href", "target", "rel", "class"}:
        raise ValueError("link mark에 허용되지 않은 속성이 있습니다.")
    href = attributes.get("href")
    if not isinstance(href, str) or not _is_allowed_link(href):
        raise ValueError("허용되지 않은 link URL입니다.")
    target = attributes.get("target")
    if target not in (None, "_blank"):
        raise ValueError("link target은 _blank만 허용합니다.")
    if attributes.get("class") not in (None, ""):
        raise ValueError("link class는 지정할 수 없습니다.")
    rel = attributes.get("rel")
    if rel not in (None, "noopener noreferrer nofollow"):
        raise ValueError("link rel 값이 허용 범위를 벗어났습니다.")
    normalized = {"href": href}
    if target == "_blank":
        normalized.update({"target": "_blank", "rel": "noopener noreferrer nofollow"})
    return normalized


def _normalize_text_style_attributes(attributes: dict[str, Any]) -> dict[str, Any]:
    """textStyle mark의 color와 fontSize를 allowlist로 제한한다."""
    if set(attributes) - {"color", "fontSize"}:
        raise ValueError("textStyle mark에 허용되지 않은 속성이 있습니다.")
    normalized: dict[str, Any] = {}
    color = attributes.get("color")
    font_size = attributes.get("fontSize")
    if color is not None:
        if color not in ALLOWED_COLORS:
            raise ValueError("허용되지 않은 글자 색상입니다.")
        normalized["color"] = color
    if font_size is not None:
        if font_size not in ALLOWED_FONT_SIZES:
            raise ValueError("허용되지 않은 글자 크기입니다.")
        normalized["fontSize"] = font_size
    if not normalized:
        raise ValueError("textStyle mark에는 color 또는 fontSize가 필요합니다.")
    return normalized


def _normalize_node_attributes(node_type: str, attributes: object) -> dict[str, Any]:
    """node type별 attrs를 검증하고 기본값을 포함한 mapping으로 정규화한다."""
    if attributes is None:
        attributes = {}
    if not isinstance(attributes, dict):
        raise ValueError(f"{node_type} node의 attrs는 객체여야 합니다.")
    if node_type == "heading":
        if set(attributes) != {"level"} or attributes["level"] not in {1, 2, 3}:
            raise ValueError("heading level은 1, 2, 3만 허용합니다.")
        return {"level": attributes["level"]}
    if node_type == "orderedList":
        if set(attributes) - {"start", "type"}:
            raise ValueError("orderedList에 허용되지 않은 속성이 있습니다.")
        start = attributes.get("start", 1)
        if not isinstance(start, int) or isinstance(start, bool) or not 1 <= start <= 1_000_000:
            raise ValueError("orderedList start 값이 허용 범위를 벗어났습니다.")
        if attributes.get("type") not in (None, "1"):
            raise ValueError("orderedList type은 변경할 수 없습니다.")
        return {"start": start}
    if node_type == "taskItem":
        if set(attributes) != {"checked"} or not isinstance(attributes["checked"], bool):
            raise ValueError("taskItem에는 checked Boolean 속성이 필요합니다.")
        return {"checked": attributes["checked"]}
    if node_type in {"tableHeader", "tableCell"}:
        if set(attributes) - {"colspan", "rowspan", "colwidth"}:
            raise ValueError(f"{node_type}에 허용되지 않은 속성이 있습니다.")
        colspan = attributes.get("colspan", 1)
        rowspan = attributes.get("rowspan", 1)
        colwidth = attributes.get("colwidth")
        if not isinstance(colspan, int) or isinstance(colspan, bool) or not 1 <= colspan <= 20:
            raise ValueError("table colspan 값이 허용 범위를 벗어났습니다.")
        if not isinstance(rowspan, int) or isinstance(rowspan, bool) or not 1 <= rowspan <= 20:
            raise ValueError("table rowspan 값이 허용 범위를 벗어났습니다.")
        if colwidth is not None:
            if not isinstance(colwidth, list) or len(colwidth) != colspan:
                raise ValueError("table colwidth 형식이 올바르지 않습니다.")
            if any(
                not isinstance(width, int)
                or isinstance(width, bool)
                or not 20 <= width <= 2_000
                for width in colwidth
            ):
                raise ValueError("table colwidth 값이 허용 범위를 벗어났습니다.")
        return {"colspan": colspan, "rowspan": rowspan, "colwidth": colwidth}
    if node_type == "image":
        if set(attributes) - {"attachmentId", "alt", "title"}:
            raise ValueError("image node에 허용되지 않은 속성이 있습니다.")
        attachment_id = attributes.get("attachmentId")
        if (
            not isinstance(attachment_id, int)
            or isinstance(attachment_id, bool)
            or attachment_id <= 0
        ):
            raise ValueError("image node에는 유효한 attachmentId가 필요합니다.")
        normalized = {"attachmentId": attachment_id}
        for name in ("alt", "title"):
            value = attributes.get(name)
            if value is not None:
                if not isinstance(value, str) or len(value) > 500:
                    raise ValueError(f"image {name} 값이 허용 범위를 벗어났습니다.")
                normalized[name] = value
        return normalized
    if attributes:
        raise ValueError(f"{node_type} node에는 attrs를 지정할 수 없습니다.")
    return {}


def _is_allowed_link(href: str) -> bool:
    """외부 http(s) 또는 안전한 내부 경로인지 확인한다."""
    if (
        not href
        or len(href) > 2_048
        or any(
            character.isspace() or ord(character) < 32 or ord(character) == 127
            for character in href
        )
    ):
        return False
    if href.startswith("//"):
        return False
    if href.startswith(("/", "#")):
        return True
    try:
        parsed = urlsplit(href)
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.netloc)
        and parsed.username is None
        and parsed.password is None
    )


def _render_node(node: dict[str, Any]) -> str:
    """검증된 단일 node를 HTML 조각으로 렌더링한다."""
    node_type = node["type"]
    content = "".join(_render_node(child) for child in node.get("content", []))
    if node_type == "text":
        return _render_text_node(node)
    if node_type == "paragraph":
        return f"<p>{content}</p>"
    if node_type == "heading":
        level = node["attrs"]["level"]
        return f"<h{level}>{content}</h{level}>"
    if node_type == "hardBreak":
        return "<br>"
    if node_type == "bulletList":
        return f"<ul>{content}</ul>"
    if node_type == "orderedList":
        start = node["attrs"]["start"]
        start_attribute = "" if start == 1 else f' start="{start}"'
        return f"<ol{start_attribute}>{content}</ol>"
    if node_type == "listItem":
        return f"<li>{content}</li>"
    if node_type == "taskList":
        return f"<ul>{content}</ul>"
    if node_type == "taskItem":
        checked = node["attrs"]["checked"]
        checked_attribute = " checked" if checked else ""
        return (
            f'<li data-checked="{str(checked).lower()}">'
            f'<input type="checkbox" disabled{checked_attribute}>{content}</li>'
        )
    if node_type == "blockquote":
        return f"<blockquote>{content}</blockquote>"
    if node_type == "codeBlock":
        return f"<pre><code>{content}</code></pre>"
    if node_type == "table":
        return f"<table><tbody>{content}</tbody></table>"
    if node_type == "tableRow":
        return f"<tr>{content}</tr>"
    if node_type in {"tableHeader", "tableCell"}:
        tag = "th" if node_type == "tableHeader" else "td"
        attributes = node["attrs"]
        span_attributes = (
            f' colspan="{attributes["colspan"]}" rowspan="{attributes["rowspan"]}"'
        )
        return f"<{tag}{span_attributes}>{content}</{tag}>"
    if node_type == "image":
        attributes = node["attrs"]
        attachment_id = attributes["attachmentId"]
        alt = html.escape(attributes.get("alt", ""), quote=True)
        title = attributes.get("title")
        title_attribute = f' title="{html.escape(title, quote=True)}"' if title else ""
        return (
            f'<img src="/attachments/{attachment_id}" data-attachment-id="{attachment_id}" '
            f'alt="{alt}"{title_attribute}>'
        )
    raise ValueError(f"렌더링할 수 없는 node입니다: {node_type}")


def _render_text_node(node: dict[str, Any]) -> str:
    """text node의 mark를 고정된 순서로 HTML에 적용한다."""
    rendered = html.escape(node["text"])
    for mark in node.get("marks", []):
        mark_type = mark["type"]
        if mark_type == "bold":
            rendered = f"<strong>{rendered}</strong>"
        elif mark_type == "italic":
            rendered = f"<em>{rendered}</em>"
        elif mark_type == "underline":
            rendered = f"<u>{rendered}</u>"
        elif mark_type == "strike":
            rendered = f"<s>{rendered}</s>"
        elif mark_type == "code":
            rendered = f"<code>{rendered}</code>"
        elif mark_type == "textStyle":
            styles = []
            attributes = mark["attrs"]
            if "color" in attributes:
                styles.append(f'color: {attributes["color"]}')
            if "fontSize" in attributes:
                styles.append(f'font-size: {attributes["fontSize"]}')
            rendered = f'<span style="{"; ".join(styles)}">{rendered}</span>'
        elif mark_type == "link":
            attributes = mark["attrs"]
            href = html.escape(attributes["href"], quote=True)
            target_attributes = ""
            if attributes.get("target") == "_blank":
                target_attributes = ' target="_blank" rel="noopener noreferrer nofollow"'
            rendered = f'<a href="{href}"{target_attributes}>{rendered}</a>'
    return rendered


def _extract_node_text(node: dict[str, Any]) -> str:
    """단일 node와 하위 node의 plain text 표현을 반환한다."""
    node_type = node["type"]
    if node_type == "text":
        return node["text"]
    if node_type == "hardBreak":
        return "\n"
    if node_type == "image":
        return node["attrs"].get("alt", "")
    child_texts = [_extract_node_text(child) for child in node.get("content", [])]
    text_block_types = BLOCK_NODE_TYPES | {
        "listItem",
        "taskItem",
        "tableRow",
        "tableCell",
        "tableHeader",
    }
    separator = "\n" if node_type in text_block_types else ""
    text_value = separator.join(text for text in child_texts if text)
    if node_type == "taskItem":
        marker = "[x] " if node["attrs"]["checked"] else "[ ] "
        return marker + text_value
    return text_value


def _iter_attachment_ids(node: dict[str, Any]) -> Iterable[int]:
    """검증된 node tree에서 attachment ID를 재귀적으로 순회한다."""
    if node["type"] == "image":
        yield node["attrs"]["attachmentId"]
    for child in node.get("content", []):
        yield from _iter_attachment_ids(child)
