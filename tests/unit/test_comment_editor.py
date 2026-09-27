from pathlib import Path


def repository_root() -> Path:
    """frontend source와 template을 찾을 저장소 root를 반환한다."""
    return Path(__file__).resolve().parents[2]


def test_common_editor_uses_configurable_accessible_label_and_placeholder():
    """공용 editor가 화면별 label·placeholder와 안전한 기본 label을 사용하는지 검증한다."""
    editor_source = (repository_root() / "frontend" / "tiptap-editor.js").read_text(
        encoding="utf-8"
    )
    assert "editorElement.dataset.richTextLabel || '구조화 본문 편집기'" in editor_source
    assert "editorElement.dataset.richTextPlaceholder || ''" in editor_source
    assert "editorAttributes['aria-placeholder'] = placeholder" in editor_source


def test_multiple_editors_resolve_their_nearest_form_and_field_payload():
    """한 화면의 여러 editor가 가장 가까운 form과 field payload만 찾는지 검증한다."""
    editor_source = (repository_root() / "frontend" / "tiptap-editor.js").read_text(
        encoding="utf-8"
    )
    assert "editorElement.closest('form')" in editor_source
    assert "editorElement.closest('.rich-text-field')" in editor_source
    assert "fieldElement?.querySelector('[data-rich-text-payload]')" in editor_source
    assert "document.querySelectorAll('[data-rich-text-editor]')" in editor_source


def test_ticket_and_comment_templates_set_context_specific_editor_labels():
    """설명·댓글 작성·댓글 수정 editor가 서로 다른 접근성 label을 지정하는지 검증한다."""
    template_directory = repository_root() / "app" / "web" / "templates"
    ticket_form_template = (template_directory / "ticket_form.html").read_text(
        encoding="utf-8"
    )
    ticket_detail_template = (template_directory / "ticket_detail.html").read_text(
        encoding="utf-8"
    )
    assert "'티켓 설명 편집기'" in ticket_form_template
    assert "'댓글 작성 편집기'" in ticket_detail_template
    assert "'댓글 수정 편집기'" in ticket_detail_template
