import json

import pytest

from app.domain.rich_text import (
    MAX_DOCUMENT_BYTES,
    MAX_DOCUMENT_DEPTH,
    MAX_DOCUMENT_NODES,
    MAX_DOCUMENT_TEXT_LENGTH,
    body_document_digest,
    canonical_body_document_json,
    empty_body_document,
    extract_body_document_text,
    iter_attachment_ids,
    render_body_document_html,
    validate_body_document,
)


def korean_example_document() -> dict[str, object]:
    """허용 기능을 포함한 한국어 본문 fixture를 반환한다."""
    return {
        "type": "doc",
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 2},
                "content": [{"type": "text", "text": "배포 준비"}],
            },
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "중요한 안내",
                        "marks": [
                            {"type": "bold"},
                            {
                                "type": "textStyle",
                                "attrs": {"color": "#b91c1c", "fontSize": "18px"},
                            },
                        ],
                    },
                    {"type": "hardBreak"},
                    {
                        "type": "text",
                        "text": "내부 문서",
                        "marks": [{"type": "link", "attrs": {"href": "/docs/guide"}}],
                    },
                ],
            },
            {
                "type": "taskList",
                "content": [
                    {
                        "type": "taskItem",
                        "attrs": {"checked": True},
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "검증 완료"}],
                            }
                        ],
                    }
                ],
            },
            {
                "type": "table",
                "content": [
                    {
                        "type": "tableRow",
                        "content": [
                            {
                                "type": "tableHeader",
                                "attrs": {"colspan": 1, "rowspan": 1, "colwidth": None},
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [{"type": "text", "text": "항목"}],
                                    }
                                ],
                            },
                            {
                                "type": "tableCell",
                                "attrs": {"colspan": 1, "rowspan": 1, "colwidth": None},
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [{"type": "text", "text": "결과"}],
                                    }
                                ],
                            },
                        ],
                    }
                ],
            },
            {
                "type": "image",
                "attrs": {"attachmentId": 42, "alt": "구성도", "title": "배포 구성도"},
            },
        ],
    }


def document_with_serialized_size(serialized_size: int) -> dict[str, object]:
    """직렬화 결과가 지정한 UTF-8 byte 크기인 document를 생성한다."""
    text_node: dict[str, object] = {"type": "text", "text": ""}
    document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [text_node],
            }
        ],
    }
    empty_document_size = len(
        json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    text_byte_size = serialized_size - empty_document_size
    if text_byte_size <= 0:
        raise ValueError("document 최소 크기보다 큰 serialized_size가 필요합니다.")
    three_byte_character_count, one_byte_character_count = divmod(text_byte_size, 3)
    text_node["text"] = (
        "가" * three_byte_character_count + "a" * one_byte_character_count
    )
    assert (
        len(json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        == serialized_size
    )
    return document


def nested_blockquote_document(blockquote_count: int) -> dict[str, object]:
    """지정한 수의 blockquote로 paragraph를 감싼 document를 생성한다."""
    nested_node: dict[str, object] = {"type": "paragraph"}
    for _ in range(blockquote_count):
        nested_node = {"type": "blockquote", "content": [nested_node]}
    return {"type": "doc", "content": [nested_node]}


def test_document_validation_canonicalization_and_digest_are_deterministic() -> None:
    """동일한 document가 정렬된 JSON과 같은 digest로 정규화되는지 검증한다."""
    document = korean_example_document()
    reordered_document = {"content": document["content"], "type": "doc"}

    assert validate_body_document({"type": "doc", "content": []}) == empty_body_document()
    assert canonical_body_document_json(document) == canonical_body_document_json(
        reordered_document
    )
    assert body_document_digest(document) == body_document_digest(reordered_document)
    assert list(iter_attachment_ids(document)) == [42]


def test_document_renderer_and_plain_text_preserve_supported_content() -> None:
    """지원 node가 안전한 HTML과 plain text로 결정적으로 변환되는지 검증한다."""
    document = korean_example_document()

    rendered_html = render_body_document_html(document)
    plain_text = extract_body_document_text(document)

    assert "<h2>배포 준비</h2>" in rendered_html
    assert "<strong>중요한 안내</strong>" in rendered_html
    assert 'href="/docs/guide"' in rendered_html
    assert 'data-attachment-id="42"' in rendered_html
    assert "javascript:" not in rendered_html
    assert "배포 준비" in plain_text
    assert "[x] 검증 완료" in plain_text
    assert "항목" in plain_text and "결과" in plain_text


@pytest.mark.parametrize(
    "mark",
    [
        {"type": "bold"},
        {"type": "italic"},
        {"type": "underline"},
        {"type": "strike"},
        {"type": "code"},
        {"type": "textStyle", "attrs": {"color": "#1d4ed8", "fontSize": "16px"}},
        {"type": "link", "attrs": {"href": "https://example.com/docs"}},
    ],
)
def test_document_validation_accepts_each_allowed_mark(mark: dict[str, object]) -> None:
    """schema v2의 허용 mark를 각각 검증하고 보존하는지 확인한다."""
    document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "허용 서식", "marks": [mark]}],
            }
        ],
    }

    normalized_document = validate_body_document(document)

    assert normalized_document["content"][0]["content"][0]["marks"] == [mark]


def test_document_renderer_escapes_html_and_attribute_xss_payloads() -> None:
    """본문 text와 image 속성의 HTML·XSS payload를 markup으로 해석하지 않는지 검증한다."""
    document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": '<script>alert(1)</script><img src=x onerror="alert(2)">',
                    }
                ],
            },
            {
                "type": "image",
                "attrs": {
                    "attachmentId": 7,
                    "alt": '"><svg onload="alert(3)">',
                    "title": '</title><iframe src="https://evil.example">',
                },
            },
        ],
    }

    rendered_html = render_body_document_html(document)

    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered_html
    assert "&lt;img src=x onerror=" in rendered_html
    assert "<script" not in rendered_html
    assert "<svg" not in rendered_html
    assert "<iframe" not in rendered_html
    assert rendered_html.count("<img ") == 1
    assert 'src="/attachments/7"' in rendered_html


def test_code_block_accepts_tiptap_default_null_language_attribute() -> None:
    """Tiptap codeBlock이 생성하는 null language 기본값을 canonical 문서에서 제거한다."""
    document = {
        "type": "doc",
        "content": [
            {
                "type": "codeBlock",
                "attrs": {"language": None},
                "content": [{"type": "text", "text": "# epic\ntest"}],
            }
        ],
    }

    normalized_document = validate_body_document(document)

    assert normalized_document == {
        "type": "doc",
        "content": [
            {
                "type": "codeBlock",
                "content": [{"type": "text", "text": "# epic\ntest"}],
            }
        ],
    }
    assert "# epic" in extract_body_document_text(normalized_document)


@pytest.mark.parametrize(
    "document, message",
    [
        ({"type": "doc", "content": [{"type": "script"}]}, "사용할 수 없습니다"),
        (
            {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": "알 수 없는 mark",
                                "marks": [{"type": "highlight"}],
                            }
                        ],
                    }
                ],
            },
            "허용되지 않은 mark",
        ),
        (
            {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": "위험",
                                "marks": [
                                    {
                                        "type": "link",
                                        "attrs": {"href": "javascript:alert(1)"},
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
            "허용되지 않은 link URL",
        ),
        (
            {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "attrs": {"onclick": "alert(1)"},
                    }
                ],
            },
            "attrs를 지정할 수 없습니다",
        ),
        (
            {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "attrs": {"data-unsafe": "payload"},
                    }
                ],
            },
            "attrs를 지정할 수 없습니다",
        ),
        (
            {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": "임의 CSS",
                                "marks": [
                                    {
                                        "type": "textStyle",
                                        "attrs": {"style": "position:fixed"},
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
            "textStyle mark에 허용되지 않은 속성",
        ),
        (
            {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": "임의 link 속성",
                                "marks": [
                                    {
                                        "type": "link",
                                        "attrs": {
                                            "href": "https://example.com",
                                            "data-track": "secret",
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
            "link mark에 허용되지 않은 속성",
        ),
        (
            {
                "type": "doc",
                "content": [
                    {
                        "type": "image",
                        "attrs": {"attachmentId": 1, "src": "https://example.com/a.png"},
                    }
                ],
            },
            "허용되지 않은 속성",
        ),
        (
            {
                "type": "doc",
                "content": [
                    {
                        "type": "codeBlock",
                        "content": [
                            {
                                "type": "text",
                                "text": "print('안전')",
                                "marks": [{"type": "bold"}],
                            }
                        ],
                    }
                ],
            },
            "codeBlock의 text node에는 mark",
        ),
        (
            {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": "제어 문자 URL",
                                "marks": [
                                    {
                                        "type": "link",
                                        "attrs": {"href": "https://example.com/\u0000path"},
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
            "허용되지 않은 link URL",
        ),
    ],
)
def test_document_validation_rejects_unsafe_nodes_marks_and_attributes(
    document: dict[str, object], message: str
) -> None:
    """임의 HTML·위험 URL·외부 image 속성을 거부하는지 검증한다."""
    with pytest.raises(ValueError, match=message):
        validate_body_document(document)


@pytest.mark.parametrize(
    "href",
    [
        "data:text/html,<script>alert(1)</script>",
        "vbscript:msgbox(1)",
        "//evil.example/path",
        "/\\evil.example/path",
        "https://user@example.com/path",
        "https://user:password@example.com/path",
    ],
)
def test_document_validation_rejects_dangerous_link_variants(href: str) -> None:
    """scheme 우회·외부 전환·credential 포함 link를 거부하는지 검증한다."""
    document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "위험 링크",
                        "marks": [{"type": "link", "attrs": {"href": href}}],
                    }
                ],
            }
        ],
    }

    with pytest.raises(ValueError, match="허용되지 않은 link URL"):
        validate_body_document(document)


def test_document_validation_accepts_exact_resource_limits() -> None:
    """크기·깊이·node 수·text 길이의 정확한 최댓값을 허용하는지 검증한다."""
    maximum_depth_document = nested_blockquote_document(MAX_DOCUMENT_DEPTH - 2)
    maximum_node_count_document = {
        "type": "doc",
        "content": [{"type": "paragraph"} for _ in range(MAX_DOCUMENT_NODES - 1)],
    }
    maximum_text_length_document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "a" * MAX_DOCUMENT_TEXT_LENGTH}],
            }
        ],
    }
    maximum_size_document = document_with_serialized_size(MAX_DOCUMENT_BYTES)

    assert validate_body_document(maximum_depth_document) == maximum_depth_document
    assert validate_body_document(maximum_node_count_document) == maximum_node_count_document
    assert validate_body_document(maximum_text_length_document) == maximum_text_length_document
    assert validate_body_document(maximum_size_document) == maximum_size_document


def test_document_validation_rejects_first_value_above_resource_limits() -> None:
    """크기·깊이·node 수·text 길이의 최댓값을 하나라도 넘으면 거부하는지 검증한다."""
    excessive_depth_document = nested_blockquote_document(MAX_DOCUMENT_DEPTH - 1)
    excessive_node_count_document = {
        "type": "doc",
        "content": [{"type": "paragraph"} for _ in range(MAX_DOCUMENT_NODES)],
    }
    excessive_text_length_document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "a" * (MAX_DOCUMENT_TEXT_LENGTH + 1),
                    }
                ],
            }
        ],
    }
    excessive_size_document = document_with_serialized_size(MAX_DOCUMENT_BYTES + 1)

    with pytest.raises(ValueError, match="중첩 깊이"):
        validate_body_document(excessive_depth_document)
    with pytest.raises(ValueError, match="node 수"):
        validate_body_document(excessive_node_count_document)
    with pytest.raises(ValueError, match="text 길이"):
        validate_body_document(excessive_text_length_document)
    with pytest.raises(ValueError, match="JSON 크기"):
        validate_body_document(excessive_size_document)
