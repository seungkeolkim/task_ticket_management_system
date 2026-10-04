"""멘션 node의 구조 검증과 안전한 renderer 계약."""

import pytest

from app.domain.rich_text import (
    convert_body_v2_to_v3,
    document_schema_version,
    empty_body_document,
    extract_body_document_text,
    render_body_document_html,
    validate_body_document,
)


def mention_document(label="사용자"):
    """paragraph에 단일 멘션을 가진 입력을 만든다."""
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "mention", "attrs": {"userId": 1, "label": label}},
                ],
            }
        ],
    }


def test_mention_rendering_and_legacy_conversion():
    """멘션 HTML을 escape하고 v2 본문을 변경 없이 변환한다."""
    document = mention_document('<img src=x onerror="alert(1)">')
    assert document_schema_version(document) == 3
    assert "<img" not in render_body_document_html(document)
    assert "@<img" in extract_body_document_text(document)
    assert 'data-mention-user-id="1"' in render_body_document_html(document)
    legacy = empty_body_document()
    assert convert_body_v2_to_v3(legacy) == legacy
    assert document_schema_version(legacy) == 2
    with pytest.raises(ValueError):
        convert_body_v2_to_v3(document)


@pytest.mark.parametrize("mutation", ["children", "marks", "attribute", "block", "code"])
def test_mention_rejects_invalid_structure(mutation):
    """atom content·mark·알 수 없는 속성과 허용되지 않은 부모를 차단한다."""
    document = mention_document()
    paragraph = document["content"][0]
    mention = paragraph["content"][0]
    if mutation == "children":
        mention["content"] = [{"type": "text", "text": "숨긴 입력"}]
    elif mutation == "marks":
        mention["marks"] = [{"type": "bold"}]
    elif mutation == "attribute":
        mention["attrs"]["onclick"] = "alert(1)"
    elif mutation == "block":
        document["content"] = [mention]
    elif mutation == "code":
        paragraph["type"] = "codeBlock"
    with pytest.raises(ValueError):
        validate_body_document(document)


def test_mention_labels_count_toward_text_limit():
    """반복된 멘션 표시 문자열도 전체 본문 text 길이에 포함한다."""
    document = mention_document("a" * 200)
    mention = document["content"][0]["content"][0]
    document["content"][0]["content"] = [mention] * 501
    with pytest.raises(ValueError, match="text 길이"):
        validate_body_document(document)
