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


def test_editor_persists_automatically_detected_links_as_tiptap_marks():
    """editor가 입력 중 감지한 URL을 명시적인 link mark로 저장하도록 설정했는지 검증한다."""
    editor_source = (repository_root() / "frontend" / "tiptap-editor.js").read_text(
        encoding="utf-8"
    )

    assert "autolink: true" in editor_source
    assert "autolink: false" not in editor_source


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


def test_comment_forms_require_confirmation_before_submission():
    """댓글 작성·수정·삭제 form이 제출 전 확인 처리를 사용하는지 검증한다."""
    root = repository_root()
    confirmation_source = (
        root / "app" / "web" / "static" / "form-confirmation.js"
    ).read_text(encoding="utf-8")
    detail_template = (root / "app" / "web" / "templates" / "ticket_detail.html").read_text(
        encoding="utf-8"
    )

    assert "form[data-confirm-message]" in confirmation_source
    assert "window.confirm(formElement.dataset.confirmMessage)" in confirmation_source
    assert "event.preventDefault()" in confirmation_source
    for confirmation_message in (
        "댓글을 등록하시겠습니까?",
        "답글을 등록하시겠습니까?",
        "댓글 수정을 저장하시겠습니까?",
        "댓글을 삭제하시겠습니까?",
    ):
        assert f'data-confirm-message="{confirmation_message}"' in detail_template


def test_editor_uploads_image_attachment_and_inserts_internal_node():
    """editor가 보호된 upload API 결과를 외부 URL 없이 image node로 삽입하는지 검증한다."""
    root = repository_root()
    editor_source = (root / "frontend" / "tiptap-editor.js").read_text(encoding="utf-8")
    macro_template = (root / "app" / "web" / "templates" / "_macros.html").read_text(
        encoding="utf-8"
    )

    assert "data-rich-text-image-upload-url" in macro_template
    assert "rich_text_editor_button('uploadImage', '이미지 업로드', 'image')" in macro_template
    assert "uploadPayload.append('expected_version', expectedVersion)" in editor_source
    assert "'X-CSRF-Token': csrfToken" in editor_source
    assert "attachmentId: responsePayload.attachment.id" in editor_source
    assert "updateTicketVersion(uploadUrl, responsePayload.ticket_version)" in editor_source
    assert "window.confirm('이미지를 첨부파일로 등록하시겠습니까?')" in editor_source


def test_ticket_mutations_require_confirmation_before_submission():
    """티켓 생성·수정과 상세·칸반의 변경 동작이 실행 전 확인을 받는지 검증한다."""
    root = repository_root()
    template_directory = root / "app" / "web" / "templates"
    base_template = (template_directory / "base.html").read_text(encoding="utf-8")
    form_template = (template_directory / "ticket_form.html").read_text(encoding="utf-8")
    detail_template = (template_directory / "ticket_detail.html").read_text(
        encoding="utf-8"
    )
    trash_template = (template_directory / "trash.html").read_text(encoding="utf-8")
    board_template = (template_directory / "board.html").read_text(encoding="utf-8")
    board_source = (root / "app" / "web" / "static" / "board.js").read_text(
        encoding="utf-8"
    )

    assert "path='form-confirmation.js'" in base_template
    assert "티켓을 생성하시겠습니까?" in form_template
    assert "티켓 수정을 저장하시겠습니까?" in form_template
    for confirmation_message in (
        "티켓 계층을 휴지통으로 이동하시겠습니까?",
        "미완료 하위 Task가 있습니다. Epic을 완료하시겠습니까?",
        "티켓 관계를 삭제하시겠습니까?",
        "티켓 관계를 추가하시겠습니까?",
        "첨부파일을 등록하시겠습니까?",
        "티켓 상태를 '{{ label }}' 상태로 변경하시겠습니까?",
    ):
        assert confirmation_message in detail_template
    assert "티켓 계층을 복구하시겠습니까?" in trash_template
    assert 'data-status-label="{{ column.label }}"' in board_template
    assert "window.confirm(" in board_source
    assert "column.dataset.statusLabel" in board_source
