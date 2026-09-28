from pathlib import Path


def repository_root() -> Path:
    """워크스페이스 typography 소스가 있는 저장소 root를 반환합니다."""
    return Path(__file__).resolve().parents[2]


def test_primary_work_surfaces_use_readable_typography_tokens():
    """티켓 목록과 칸반의 본문·보조 정보가 가독성 token을 사용하는지 검증합니다."""
    stylesheet = (repository_root() / "app" / "web" / "static" / "app.css").read_text(
        encoding="utf-8"
    )

    assert "--font-work-body: 14px;" in stylesheet
    assert "--font-work-secondary: 13px;" in stylesheet
    assert "--font-work-meta: 12px;" in stylesheet
    assert ".ticket-table-row," in stylesheet
    assert ".kanban-card h3 {" in stylesheet
    assert ".kanban-card footer," in stylesheet
    assert ".subtask-card {" in stylesheet
    assert "margin-left: 8px;" in stylesheet
    assert "background: var(--surface-tint);" in stylesheet
    assert stylesheet.rfind("/* Readable typography for primary work surfaces */") > (
        stylesheet.rfind("/* Interactive kanban state changes */")
    )


def test_rich_text_viewer_uses_work_surface_body_size():
    """티켓 설명 viewer가 업무 화면 본문 token을 사용하는지 검증합니다."""
    stylesheet = (repository_root() / "frontend" / "tiptap-editor.css").read_text(
        encoding="utf-8"
    )

    assert "font-size: var(--font-work-body, 14px);" in stylesheet


def test_rich_text_editor_task_checkbox_overrides_form_input_dimensions():
    """TaskItem checkbox가 공용 form input 크기 규칙을 상속하지 않는지 검증합니다."""
    stylesheet = (repository_root() / "frontend" / "tiptap-editor.css").read_text(
        encoding="utf-8"
    )

    checkbox_selector = (
        ".rich-text-field .tiptap-body li[data-checked] > label > input[type='checkbox']"
    )
    assert checkbox_selector in stylesheet
    assert "width: 16px;" in stylesheet
    assert "height: 16px;" in stylesheet
    assert "min-height: 0;" in stylesheet
    assert "flex: 0 0 16px;" in stylesheet
    assert ".tiptap-body li[data-checked] > div > p {" in stylesheet
    assert "margin: 0;" in stylesheet
