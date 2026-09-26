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


def test_document_validation_rejects_excessive_depth() -> None:
    """최대 중첩 깊이를 넘은 document를 거부하는지 검증한다."""
    nested_node: dict[str, object] = {"type": "paragraph"}
    for _ in range(MAX_DOCUMENT_DEPTH + 1):
        nested_node = {"type": "blockquote", "content": [nested_node]}
    document = {"type": "doc", "content": [nested_node]}

    with pytest.raises(ValueError, match="중첩 깊이"):
        validate_body_document(document)


def test_document_validation_rejects_size_node_and_text_limits() -> None:
    """본문 전체 크기·node 수·text 길이 제한을 각각 검증한다."""
    oversized_document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "가" * MAX_DOCUMENT_BYTES}],
            }
        ],
    }
    too_many_nodes_document = {
        "type": "doc",
        "content": [{"type": "paragraph"} for _ in range(MAX_DOCUMENT_NODES)],
    }
    excessive_text_document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "a" * MAX_DOCUMENT_TEXT_LENGTH},
                    {"type": "text", "text": "b"},
                ],
            }
        ],
    }

    with pytest.raises(ValueError, match="JSON 크기"):
        validate_body_document(oversized_document)
    with pytest.raises(ValueError, match="node 수"):
        validate_body_document(too_many_nodes_document)
    with pytest.raises(ValueError, match="text 길이"):
        validate_body_document(excessive_text_document)
