from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import event, func, select

from app.core.config import get_settings
from app.domain.auth import hash_password
from app.models import (
    AuditLog,
    Mention,
    Organization,
    Project,
    ProjectMember,
    Ticket,
    TicketDeletionBatch,
    TicketHistory,
    TicketRelation,
    User,
)
from app.repositories import tickets as ticket_repository
from app.schemas.contracts import TicketEvent
from app.schemas.tickets import TicketCreate, TicketTransition, TicketUpdate
from app.services import dashboard as dashboard_service
from app.services import tickets as service
from app.services.auth import current_identity

PASSWORD = "Ticket-test-password-123!"
ORIGIN = {"Origin": "http://testserver"}


def token(client):
    return client.get("/api/auth/csrf").json()["csrf_token"]


def post(client, path, payload):
    return client.post(path, json=payload, headers=ORIGIN | {"X-CSRF-Token": token(client)})


def patch(client, path, payload):
    return client.patch(path, json=payload, headers=ORIGIN | {"X-CSRF-Token": token(client)})


def login(client, login_id):
    client.cookies.clear()
    assert (
        post(client, "/api/auth/login", {"login_id": login_id, "password": PASSWORD}).status_code
        == 200
    )


@pytest.fixture
def ticket_people(client, db_session):
    organization = Organization(key="ticket-test", name="티켓 테스트 조직")
    db_session.add(organization)
    db_session.flush()
    password_hash = hash_password(PASSWORD)
    people = {}
    for name in ["sysadmin", "manager", "member", "guest", "outsider"]:
        user = User(
            login_id=name,
            display_name=f"{name} 표시명",
            organization_id=organization.id,
            password_hash=password_hash,
            must_change_password=False,
            system_role="SYSTEM_ADMIN" if name == "sysadmin" else "USER",
        )
        db_session.add(user)
        people[name] = user
    db_session.flush()
    project = Project(key="DEV", name="티켓 프로젝트", created_by_id=people["sysadmin"].id)
    db_session.add(project)
    db_session.flush()
    db_session.add_all(
        [
            ProjectMember(
                project_id=project.id,
                user_id=people["manager"].id,
                role="PROJECT_ADMIN",
            ),
            ProjectMember(project_id=project.id, user_id=people["member"].id),
            ProjectMember(
                project_id=project.id,
                user_id=people["guest"].id,
                role="PROJECT_GUEST",
            ),
        ]
    )
    db_session.commit()
    login(client, "member")
    return people, project


def create_ticket(client, **overrides):
    payload = {
        "type": "TASK",
        "title": "실제 티켓 생성",
        "description": "DB에 저장되는 설명",
        "priority": "MAJOR",
    } | overrides
    return post(client, "/api/projects/DEV/tickets", payload)


def update_ticket(client, ticket_key, expected_version, **overrides):
    payload = {
        "title": "수정된 티켓",
        "description": "수정된 설명",
        "priority": "MAJOR",
        "parent_key": None,
        "assignee_id": None,
        "due_date": None,
        "expected_version": expected_version,
    } | overrides
    return patch(client, f"/api/projects/DEV/tickets/{ticket_key}", payload)


def transition_ticket(client, ticket_key, target_status, expected_version, **overrides):
    return post(
        client,
        f"/api/projects/DEV/tickets/{ticket_key}/transitions",
        {
            "target_status": target_status,
            "expected_version": expected_version,
        }
        | overrides,
    )


def test_create_list_detail_and_history(client, ticket_people, db_session):
    people, project = ticket_people
    response = create_ticket(
        client,
        assignee_id=people["manager"].id,
        due_date="2026-10-01",
        priority="CRITICAL",
    )
    assert response.status_code == 201
    ticket = response.json()
    assert ticket["key"] == "DEV-1"
    assert ticket["creator"]["login_id"] == "member"
    assert ticket["assignee"]["login_id"] == "manager"
    assert ticket["status"] == "TODO" and ticket["priority"] == "CRITICAL"

    page = client.get("/api/projects/DEV/tickets?q=실제").json()
    assert page["total"] == 1 and page["tickets"][0]["key"] == "DEV-1"
    assert client.get("/api/projects/DEV/tickets/DEV-1").json() == ticket
    assert "실제 티켓 생성" in client.get("/projects/DEV/tickets?selected=DEV-1").text
    assert "DB에 저장되는 설명" in client.get("/projects/DEV/tickets/DEV-1").text

    history = db_session.scalar(select(TicketHistory))
    event = TicketEvent.model_validate(
        {
            "event_key": history.event_key,
            "operation_id": history.operation_id,
            "ticket_key": ticket["key"],
            "project_id": project.id,
            "ticket_version": history.ticket_version,
            "event_type": history.event_type,
            "actor_id": history.actor_id,
            "occurred_at": history.occurred_at,
            "before_state": history.before_state,
            "after_state": history.after_state,
            "changes": history.changes,
        }
    )
    assert event.event_type == "CREATED" and event.after_state.assignee_id == people["manager"].id
    audit = db_session.scalar(select(AuditLog).where(AuditLog.action == "ticket.created"))
    assert audit.target_id == "DEV-1" and audit.details["project_id"] == project.id
    db_session.refresh(project)
    assert project.next_ticket_number == 2


def test_hierarchy_rules_and_cross_project_parent_are_enforced(
    client, ticket_people, db_session
):
    people, _ = ticket_people
    epic = create_ticket(client, type="EPIC", title="상위 Epic").json()
    task = create_ticket(client, title="Epic 아래 Task", parent_key=epic["key"]).json()
    subtask = create_ticket(
        client, type="SUBTASK", title="Task 아래 Subtask", parent_key=task["key"]
    )
    assert subtask.status_code == 201 and subtask.json()["parent"]["key"] == task["key"]
    assert create_ticket(client, type="EPIC", parent_key=task["key"]).status_code == 422
    assert create_ticket(client, type="SUBTASK", parent_key=None).status_code == 422
    assert create_ticket(client, title="잘못된 부모", parent_key=task["key"]).status_code == 400

    other = Project(key="OPS", name="다른 프로젝트", created_by_id=people["sysadmin"].id)
    db_session.add(other)
    db_session.flush()
    foreign = Ticket(
        project_id=other.id,
        number=1,
        key="OPS-1",
        title="다른 프로젝트 Epic",
        type="EPIC",
        creator_id=people["sysadmin"].id,
    )
    db_session.add(foreign)
    db_session.commit()
    assert create_ticket(client, parent_key="OPS-1").status_code == 400
    assert client.get("/api/projects/DEV/tickets/OPS-1").status_code == 404
    assert client.get("/api/projects/DEV/tickets").json()["total"] == 3


def test_permissions_assignee_csrf_and_inactive_project(
    client, ticket_people, db_session
):
    people, project = ticket_people
    path = "/api/projects/DEV/tickets"
    assert client.post(path, json={"title": "CSRF 없음"}, headers=ORIGIN).status_code == 403
    assert create_ticket(client, assignee_id=people["outsider"].id).status_code == 400
    people["manager"].is_active = False
    db_session.commit()
    assert create_ticket(client, assignee_id=people["manager"].id).status_code == 400
    people["manager"].is_active = True
    project.is_active = False
    db_session.commit()
    assert create_ticket(client).status_code == 409
    project.is_active = True
    db_session.commit()
    login(client, "outsider")
    assert client.get(path).status_code == 404
    assert client.get(path + "/DEV-1").status_code == 404
    assert client.get(path + "/board").status_code == 404
    assert create_ticket(client).status_code == 404
    assert client.get("/projects/DEV/tickets").status_code == 404
    assert client.get("/projects/DEV/board").status_code == 404


def test_guest_is_read_only_and_excluded_from_assignees(client, ticket_people):
    people, _ = ticket_people
    ticket = create_ticket(client, title="게스트 조회 티켓").json()
    login(client, "guest")

    listing = client.get("/api/projects/DEV/tickets")
    assert listing.status_code == 200 and listing.json()["total"] == 1
    assert client.get(f"/api/projects/DEV/tickets/{ticket['key']}").status_code == 200
    assert client.get("/api/projects/DEV/tickets/board").status_code == 200
    html = client.get("/projects/DEV/tickets")
    assert html.status_code == 200 and "새 티켓" not in html.text
    assert client.get("/projects/DEV/tickets/new").status_code == 403

    denied = create_ticket(client, title="게스트 생성 거부")
    assert denied.status_code == 403 and denied.json()["code"] == "project_write_required"
    denied = update_ticket(client, ticket["key"], 1, title="게스트 수정 거부")
    assert denied.status_code == 403 and denied.json()["code"] == "project_write_required"
    denied = transition_ticket(client, ticket["key"], "IN_PROGRESS", 1)
    assert denied.status_code == 403 and denied.json()["code"] == "project_write_required"

    login(client, "member")
    options = client.get("/api/projects/DEV/tickets/creation-options").json()
    assert people["guest"].id not in {item["id"] for item in options["assignees"]}
    assert create_ticket(client, assignee_id=people["guest"].id).status_code == 400


def test_html_create_escapes_values_and_refreshes_from_database(client, ticket_people):
    people, _ = ticket_people
    page = client.get("/projects/DEV/tickets/new")
    assert page.status_code == 200 and "manager 표시명" in page.text
    response = client.post(
        "/projects/DEV/tickets",
        data={
            "csrf_token": token(client),
            "type": "TASK",
            "title": '<script>alert("ticket")</script>',
            "description": "실제 화면 저장",
            "priority": "MAJOR",
            "assignee_id": str(people["member"].id),
        },
        headers=ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code == 303
    detail = client.get(response.headers["location"])
    assert "실제 화면 저장" in detail.text
    assert "&lt;script&gt;" in detail.text and '<script>alert("ticket")</script>' not in detail.text


def test_search_and_stable_pagination(client, ticket_people, db_session):
    people, project = ticket_people
    for number in range(1, 24):
        db_session.add(
            Ticket(
                project_id=project.id,
                number=number,
                key=f"DEV-{number}",
                title=f"검색 티켓 {number:02}",
                creator_id=people["member"].id,
            )
        )
    project.next_ticket_number = 24
    db_session.commit()
    first = client.get("/api/projects/DEV/tickets?q=검색&page_size=10").json()
    second = client.get("/api/projects/DEV/tickets?q=검색&page_size=10&page=2").json()
    assert first["total"] == second["total"] == 23
    assert len(first["tickets"]) == len(second["tickets"]) == 10
    assert not ({row["id"] for row in first["tickets"]} & {row["id"] for row in second["tickets"]})
    assert client.get("/api/projects/DEV/tickets?q=%25").json()["total"] == 0
    assert client.get("/api/projects/DEV/tickets?page_size=100").status_code == 400
    assert client.get("/api/projects/DEV/tickets?page=0").status_code == 400


def test_concurrent_number_allocation_is_monotonic(
    client, ticket_people, db_session_factory
):
    _, project = ticket_people
    raw_token = client.cookies.get(get_settings().session.cookie_name)

    def attempt(index):
        with db_session_factory() as session:
            actor = current_identity(session, raw_token)
            return service.create_ticket(
                session, actor, "DEV", TicketCreate(title=f"동시 티켓 {index}")
            ).key

    with ThreadPoolExecutor(max_workers=4) as pool:
        keys = sorted(pool.map(attempt, range(4)))
    assert keys == ["DEV-1", "DEV-2", "DEV-3", "DEV-4"]
    with db_session_factory() as session:
        assert session.get(Project, project.id).next_ticket_number == 5
        assert session.scalar(select(func.count()).select_from(TicketHistory)) == 4


def test_audit_failure_rolls_back_ticket_history_and_counter(
    client, ticket_people, db_session_factory, monkeypatch
):
    _, project = ticket_people
    raw_token = client.cookies.get(get_settings().session.cookie_name)

    def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(service, "audit", fail)
    with db_session_factory() as session:
        actor = current_identity(session, raw_token)
        with pytest.raises(RuntimeError):
            service.create_ticket(session, actor, "DEV", TicketCreate(title="롤백 티켓"))
        assert session.scalar(select(func.count()).select_from(Ticket)) == 0
        assert session.scalar(select(func.count()).select_from(TicketHistory)) == 0
        assert session.get(Project, project.id).next_ticket_number == 1


def test_system_admin_override_is_audited(client, ticket_people, db_session):
    login(client, "sysadmin")
    response = create_ticket(client, title="관리자 override 생성")
    assert response.status_code == 201
    override_events = db_session.scalars(
        select(AuditLog).where(AuditLog.action == "project.override_access")
    ).all()
    assert override_events and override_events[-1].details["permission"] == "write"


def test_update_moves_hierarchy_preserves_subtasks_and_records_one_history_per_version(
    client, ticket_people, db_session
):
    people, project = ticket_people
    first_epic = create_ticket(client, type="EPIC", title="첫 Epic").json()
    second_epic = create_ticket(client, type="EPIC", title="둘째 Epic").json()
    task = create_ticket(client, title="이동할 Task", parent_key=first_epic["key"]).json()
    subtask = create_ticket(
        client, type="SUBTASK", title="유지할 Subtask", parent_key=task["key"]
    ).json()
    task_row = db_session.scalar(select(Ticket).where(Ticket.key == task["key"]))
    first_epic_row = db_session.scalar(
        select(Ticket).where(Ticket.key == first_epic["key"])
    )
    db_session.add(
        TicketRelation(
            project_id=project.id,
            source_ticket_id=task_row.id,
            target_ticket_id=first_epic_row.id,
            relation_type="DEPENDS_ON",
            dependency_kind="FS",
            created_by_id=people["member"].id,
        )
    )
    db_session.commit()

    response = update_ticket(
        client,
        task["key"],
        1,
        title="이동 완료 Task",
        description="변경된 원문",
        priority="CRITICAL",
        parent_key=second_epic["key"],
        assignee_id=people["manager"].id,
        due_date="2026-10-10",
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated["version"] == 2
    assert updated["parent"]["key"] == second_epic["key"]
    assert updated["assignee"]["id"] == people["manager"].id
    saved_subtask = db_session.scalar(select(Ticket).where(Ticket.key == subtask["key"]))
    db_session.refresh(saved_subtask)
    assert saved_subtask.parent_id == task_row.id
    assert saved_subtask.status == "TODO"
    assert saved_subtask.assignee_id is None
    assert str(saved_subtask.sort_order) == "0.000000"

    histories = db_session.scalars(
        select(TicketHistory)
        .where(TicketHistory.ticket_id == task_row.id)
        .order_by(TicketHistory.ticket_version)
    ).all()
    assert [history.ticket_version for history in histories] == [1, 2]
    assert histories[-1].event_type == "UPDATED"
    assert {change["field"] for change in histories[-1].changes} == {
        "title",
        "description",
        "priority",
        "parent_key",
        "assignee_id",
        "due_date",
    }
    assert histories[-1].before_state["relations"] == histories[-1].after_state["relations"]
    assert histories[-1].before_state["relations"][0]["relation_type"] == "DEPENDS_ON"

    audit_count = db_session.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.action == "ticket.updated")
    )
    noop = update_ticket(
        client,
        task["key"],
        2,
        title="이동 완료 Task",
        description="변경된 원문",
        priority="CRITICAL",
        parent_key=second_epic["key"],
        assignee_id=people["manager"].id,
        due_date="2026-10-10",
    )
    assert noop.status_code == 200 and noop.json()["version"] == 2
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(TicketHistory)
            .where(TicketHistory.ticket_id == task_row.id)
        )
        == 2
    )
    assert (
        db_session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "ticket.updated")
        )
        == audit_count
    )
    stale_noop = update_ticket(
        client,
        task["key"],
        1,
        title="이동 완료 Task",
        description="변경된 원문",
        priority="CRITICAL",
        parent_key=second_epic["key"],
        assignee_id=people["manager"].id,
        due_date="2026-10-10",
    )
    assert stale_noop.status_code == 409
    assert stale_noop.json()["code"] == "ticket_version_conflict"
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(TicketHistory)
            .where(TicketHistory.ticket_id == task_row.id)
        )
        == 2
    )
    assert (
        db_session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "ticket.updated")
        )
        == audit_count
    )


def test_fsm_timestamps_reopen_and_history_versions(client, ticket_people, db_session):
    ticket = create_ticket(client, title="FSM 티켓").json()
    invalid = transition_ticket(client, ticket["key"], "DONE", 1)
    assert invalid.status_code == 409
    assert invalid.json()["code"] == "invalid_status_transition"

    progress = transition_ticket(client, ticket["key"], "IN_PROGRESS", 1).json()
    first_started_at = progress["actual_started_at"]
    assert progress["version"] == 2 and first_started_at
    hold = transition_ticket(client, ticket["key"], "ON_HOLD", 2).json()
    resumed = transition_ticket(client, ticket["key"], "IN_PROGRESS", 3).json()
    assert hold["actual_started_at"] == resumed["actual_started_at"] == first_started_at
    done = transition_ticket(client, ticket["key"], "DONE", 4).json()
    assert done["completed_at"] and done["cancelled_at"] is None
    reopened = transition_ticket(client, ticket["key"], "IN_PROGRESS", 5).json()
    assert reopened["completed_at"] is None
    assert reopened["actual_started_at"] == first_started_at
    cancelled = transition_ticket(client, ticket["key"], "CANCELLED", 6).json()
    assert cancelled["cancelled_at"]
    todo = transition_ticket(client, ticket["key"], "TODO", 7).json()
    assert todo["version"] == 8 and todo["cancelled_at"] is None

    ticket_id = db_session.scalar(select(Ticket.id).where(Ticket.key == ticket["key"]))
    histories = db_session.scalars(
        select(TicketHistory)
        .where(TicketHistory.ticket_id == ticket_id)
        .order_by(TicketHistory.ticket_version)
    ).all()
    assert [history.ticket_version for history in histories] == list(range(1, 9))
    assert all(history.event_type == "STATUS_CHANGED" for history in histories[1:])
    assert histories[5].before_state["completed_at"] is not None
    assert histories[5].after_state["completed_at"] is None
    assert histories[7].before_state["cancelled_at"] is not None
    assert histories[7].after_state["cancelled_at"] is None


def test_subtask_move_parent_validation_and_cross_project_rejection(
    client, ticket_people, db_session
):
    people, _ = ticket_people
    first_task = create_ticket(client, title="첫 Task").json()
    second_task = create_ticket(client, title="둘째 Task").json()
    subtask = create_ticket(
        client, type="SUBTASK", title="이동 Subtask", parent_key=first_task["key"]
    ).json()
    moved = update_ticket(
        client,
        subtask["key"],
        1,
        title="이동 Subtask",
        description="DB에 저장되는 설명",
        parent_key=second_task["key"],
    )
    assert moved.status_code == 200
    assert moved.json()["parent"]["key"] == second_task["key"]
    detached = update_ticket(
        client,
        subtask["key"],
        2,
        title="이동 Subtask",
        description="DB에 저장되는 설명",
        parent_key=None,
    )
    assert detached.status_code == 400 and detached.json()["code"] == "invalid_parent"

    other = Project(key="OPS", name="다른 프로젝트", created_by_id=people["sysadmin"].id)
    db_session.add(other)
    db_session.flush()
    foreign_epic = Ticket(
        project_id=other.id,
        number=1,
        key="OPS-1",
        type="EPIC",
        title="다른 프로젝트 Epic",
        creator_id=people["sysadmin"].id,
    )
    db_session.add(foreign_epic)
    db_session.commit()
    cross_project = update_ticket(
        client,
        first_task["key"],
        1,
        title="첫 Task",
        description="DB에 저장되는 설명",
        parent_key="OPS-1",
    )
    assert cross_project.status_code == 400
    assert cross_project.json()["code"] == "invalid_parent"


def test_parent_cycle_detector_rejects_a_descendant_as_parent(
    ticket_people, db_session
):
    people, project = ticket_people
    first = Ticket(
        project_id=project.id,
        number=1,
        key="DEV-1",
        type="TASK",
        title="첫 노드",
        creator_id=people["member"].id,
    )
    db_session.add(first)
    db_session.flush()
    second = Ticket(
        project_id=project.id,
        number=2,
        key="DEV-2",
        type="TASK",
        title="하위 노드",
        parent_id=first.id,
        creator_id=people["member"].id,
    )
    db_session.add(second)
    db_session.commit()

    assert ticket_repository.parent_would_cycle(
        db_session, project.id, first.id, second.id
    )


def test_completion_dependency_and_epic_confirmation_guards(
    client, ticket_people, db_session
):
    people, project = ticket_people
    target = create_ticket(client, title="선행 티켓").json()
    source = create_ticket(client, title="후행 티켓").json()
    source_progress = transition_ticket(
        client, source["key"], "IN_PROGRESS", 1
    ).json()
    source_row = db_session.scalar(select(Ticket).where(Ticket.key == source["key"]))
    target_row = db_session.scalar(select(Ticket).where(Ticket.key == target["key"]))
    db_session.add(
        TicketRelation(
            project_id=project.id,
            source_ticket_id=source_row.id,
            target_ticket_id=target_row.id,
            relation_type="DEPENDS_ON",
            dependency_kind="FS",
            created_by_id=people["member"].id,
        )
    )
    db_session.commit()

    blocked = transition_ticket(
        client, source["key"], "DONE", source_progress["version"]
    )
    assert blocked.status_code == 409 and blocked.json()["code"] == "incomplete_dependency"
    target_progress = transition_ticket(client, target["key"], "IN_PROGRESS", 1).json()
    transition_ticket(client, target["key"], "DONE", target_progress["version"])
    assert transition_ticket(client, source["key"], "DONE", 2).status_code == 200

    epic = create_ticket(client, type="EPIC", title="확인 Epic").json()
    create_ticket(client, title="미완료 하위 Task", parent_key=epic["key"])
    epic_progress = transition_ticket(client, epic["key"], "IN_PROGRESS", 1).json()
    confirmation = transition_ticket(
        client, epic["key"], "DONE", epic_progress["version"]
    )
    assert confirmation.status_code == 409
    assert confirmation.json()["code"] == "incomplete_child_confirmation_required"
    confirmed = transition_ticket(
        client,
        epic["key"],
        "DONE",
        epic_progress["version"],
        confirm_incomplete_children=True,
    )
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "DONE"


def test_project_user_write_admin_override_terminal_and_inactive_project(
    client, ticket_people, db_session
):
    people, project = ticket_people
    ticket = create_ticket(
        client, title="권한 티켓", assignee_id=people["manager"].id
    ).json()
    login(client, "manager")
    manager_update = update_ticket(client, ticket["key"], 1, title="관리자 수정")
    assert manager_update.status_code == 200

    db_session.add(
        ProjectMember(
            project_id=project.id,
            user_id=people["outsider"].id,
            role="PROJECT_USER",
        )
    )
    db_session.commit()
    login(client, "outsider")
    unrelated_update = update_ticket(
        client, ticket["key"], 2, title="프로젝트 사용자의 전체 티켓 수정"
    )
    assert unrelated_update.status_code == 200

    login(client, "manager")
    assigned = create_ticket(
        client, title="일반 담당자 티켓", assignee_id=people["outsider"].id
    ).json()
    login(client, "outsider")
    assignee_update = update_ticket(
        client, assigned["key"], 1, title="담당자 직접 수정"
    )
    assert assignee_update.status_code == 200

    login(client, "sysadmin")
    override = update_ticket(client, ticket["key"], 3, title="시스템 관리자 수정")
    assert override.status_code == 200
    manage_override = db_session.scalars(
        select(AuditLog)
        .where(AuditLog.action == "project.override_access")
        .order_by(AuditLog.id.desc())
    ).first()
    assert manage_override.details["permission"] == "write"

    login(client, "member")
    cancelled = transition_ticket(client, ticket["key"], "CANCELLED", 4).json()
    locked = update_ticket(client, ticket["key"], cancelled["version"])
    assert locked.status_code == 409 and locked.json()["code"] == "terminal_ticket_locked"
    reopened = transition_ticket(
        client, ticket["key"], "TODO", cancelled["version"]
    ).json()
    project.is_active = False
    db_session.commit()
    assert client.get(f"/api/projects/DEV/tickets/{ticket['key']}").status_code == 200
    assert client.get("/api/projects/DEV/tickets").status_code == 200
    assert client.get("/api/projects/DEV/tickets/board").status_code == 200
    inactive = update_ticket(client, ticket["key"], reopened["version"])
    assert inactive.status_code == 409 and inactive.json()["code"] == "project_inactive"
    transition = transition_ticket(
        client, ticket["key"], "IN_PROGRESS", reopened["version"]
    )
    assert transition.status_code == 409 and transition.json()["code"] == "project_inactive"


def test_expected_version_required_and_stale_write_rolls_back(
    client, ticket_people, db_session
):
    ticket = create_ticket(client, title="충돌 티켓").json()
    first = update_ticket(client, ticket["key"], 1, title="먼저 저장").json()
    stale = update_ticket(client, ticket["key"], 1, title="늦은 저장")
    assert stale.status_code == 409 and stale.json()["code"] == "ticket_version_conflict"
    missing = patch(
        client,
        f"/api/projects/DEV/tickets/{ticket['key']}",
        {
            "title": "버전 없음",
            "description": "",
            "priority": "MAJOR",
            "parent_key": None,
            "assignee_id": None,
            "due_date": None,
        },
    )
    assert missing.status_code == 422 and missing.json()["code"] == "invalid_request"
    saved = db_session.scalar(select(Ticket).where(Ticket.key == ticket["key"]))
    db_session.refresh(saved)
    assert saved.title == "먼저 저장" and saved.version == first["version"] == 2
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(TicketHistory)
            .where(TicketHistory.ticket_id == saved.id)
        )
        == 2
    )


def test_update_audit_failure_rolls_back_ticket_and_history(
    client, ticket_people, db_session_factory, monkeypatch
):
    ticket = create_ticket(client, title="수정 롤백 티켓").json()
    raw_token = client.cookies.get(get_settings().session.cookie_name)

    def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(service, "audit", fail)
    with db_session_factory() as session:
        actor = current_identity(session, raw_token)
        with pytest.raises(RuntimeError):
            service.update_ticket(
                session,
                actor,
                "DEV",
                ticket["key"],
                TicketUpdate(
                    title="반영되면 안 됨",
                    description="",
                    priority="MAJOR",
                    expected_version=1,
                ),
            )
        with pytest.raises(RuntimeError):
            service.transition_ticket(
                session,
                actor,
                "DEV",
                ticket["key"],
                TicketTransition(target_status="IN_PROGRESS", expected_version=1),
            )
    with db_session_factory() as session:
        saved = session.scalar(select(Ticket).where(Ticket.key == ticket["key"]))
        assert saved.title == "수정 롤백 티켓" and saved.version == 1
        assert saved.status == "TODO" and saved.actual_started_at is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(TicketHistory)
                .where(TicketHistory.ticket_id == saved.id)
            )
            == 1
        )


def test_html_edit_csrf_stale_guidance_and_transition_controls(
    client, ticket_people
):
    ticket = create_ticket(client, title="HTML 편집 티켓").json()
    edit_page = client.get(f"/projects/DEV/tickets/{ticket['key']}/edit")
    assert edit_page.status_code == 200
    assert 'name="expected_version" value="1"' in edit_page.text
    assert (
        client.post(
            f"/projects/DEV/tickets/{ticket['key']}",
            data={
                "title": "CSRF 없는 수정",
                "priority": "MAJOR",
                "expected_version": "1",
            },
            headers=ORIGIN,
        ).status_code
        == 403
    )
    assert update_ticket(client, ticket["key"], 1, title="API 선행 수정").status_code == 200
    stale = client.post(
        f"/projects/DEV/tickets/{ticket['key']}",
        data={
            "csrf_token": token(client),
            "title": "HTML 늦은 수정",
            "description": "",
            "priority": "MAJOR",
            "parent_key": "",
            "assignee_id": "",
            "due_date": "",
            "expected_version": "1",
        },
        headers=ORIGIN,
    )
    assert stale.status_code == 409
    assert "최신 내용 다시 불러오기" in stale.text and "disabled" in stale.text
    detail = client.get(f"/projects/DEV/tickets/{ticket['key']}")
    assert detail.status_code == 200
    assert f"/projects/DEV/tickets/{ticket['key']}/transition" in detail.text


def test_html_epic_completion_requires_confirmation(client, ticket_people):
    epic = create_ticket(client, type="EPIC", title="HTML 확인 Epic").json()
    create_ticket(client, title="HTML 미완료 Task", parent_key=epic["key"])
    progress = transition_ticket(client, epic["key"], "IN_PROGRESS", 1).json()
    confirmation = client.post(
        f"/projects/DEV/tickets/{epic['key']}/transition",
        data={
            "csrf_token": token(client),
            "target_status": "DONE",
            "expected_version": str(progress["version"]),
        },
        headers=ORIGIN,
    )
    assert confirmation.status_code == 409
    assert "미완료 Task를 확인했으며 Epic 완료" in confirmation.text
    confirmed = client.post(
        f"/projects/DEV/tickets/{epic['key']}/transition",
        data={
            "csrf_token": token(client),
            "target_status": "DONE",
            "expected_version": str(progress["version"]),
            "confirm_incomplete_children": "true",
        },
        headers=ORIGIN,
        follow_redirects=False,
    )
    assert confirmed.status_code == 303


def test_service_transition_contract_rejects_missing_expected_version():
    with pytest.raises(ValueError):
        TicketTransition(target_status="IN_PROGRESS")


def test_dashboard_and_global_filters_use_assignee_then_unassigned_creator_rule(
    client, ticket_people, db_session, monkeypatch
):
    people, project = ticket_people
    monkeypatch.setattr(dashboard_service, "local_today", lambda: date(2026, 9, 22))
    rows = [
        Ticket(
            project_id=project.id,
            number=1,
            key="DEV-1",
            title="담당자 없는 내가 만든 티켓",
            creator_id=people["member"].id,
            due_date=date(2026, 9, 21),
        ),
        Ticket(
            project_id=project.id,
            number=2,
            key="DEV-2",
            title="내가 담당한 티켓",
            creator_id=people["manager"].id,
            assignee_id=people["member"].id,
            due_date=date(2026, 9, 25),
        ),
        Ticket(
            project_id=project.id,
            number=3,
            key="DEV-3",
            title="내가 만들었지만 다른 담당자",
            creator_id=people["member"].id,
            assignee_id=people["manager"].id,
        ),
        Ticket(
            project_id=project.id,
            number=4,
            key="DEV-4",
            title="완료된 내 담당 티켓",
            creator_id=people["manager"].id,
            assignee_id=people["member"].id,
            status="DONE",
        ),
    ]
    db_session.add_all(rows)
    db_session.flush()
    now = datetime(2026, 9, 22, tzinfo=UTC)
    batch = TicketDeletionBatch(
        project_id=project.id,
        root_ticket_key="DEV-5",
        deleted_by_id=people["manager"].id,
        deleted_at=now,
        purge_after=now + timedelta(days=30),
    )
    db_session.add(batch)
    db_session.flush()
    db_session.add(
        Ticket(
            project_id=project.id,
            number=5,
            key="DEV-5",
            title="삭제된 내 티켓",
            creator_id=people["member"].id,
            deleted_at=now,
            deletion_batch_id=batch.id,
        )
    )
    hidden = Project(key="HID", name="숨은 프로젝트", created_by_id=people["sysadmin"].id)
    db_session.add(hidden)
    db_session.flush()
    db_session.add(
        Ticket(
            project_id=hidden.id,
            number=1,
            key="HID-1",
            title="접근 불가 담당 티켓",
            creator_id=people["sysadmin"].id,
            assignee_id=people["member"].id,
        )
    )
    db_session.add(
        Mention(
            project_id=project.id,
            ticket_id=rows[0].id,
            target_user_id=people["member"].id,
            mentioned_by_id=people["manager"].id,
        )
    )
    project.next_ticket_number = 6
    db_session.commit()

    dashboard = client.get("/api/dashboard").json()
    assert dashboard["counts"] == {"open_mine": 2, "overdue": 1, "due_this_week": 1}
    assert {item["key"] for item in dashboard["recent_tickets"]} == {
        "DEV-1",
        "DEV-2",
        "DEV-4",
    }
    assert [item["ticket_key"] for item in dashboard["mentions"]] == ["DEV-1"]

    mine = client.get("/api/tickets?scope=mine&status=all").json()
    created = client.get("/api/tickets?scope=created&status=all").json()
    assert {item["key"] for item in mine["tickets"]} == {"DEV-1", "DEV-2", "DEV-4"}
    assert {item["key"] for item in created["tickets"]} == {"DEV-1", "DEV-3"}
    html = client.get("/tickets?scope=created&status=all")
    assert html.status_code == 200 and "내가 만든 티켓" in html.text


def test_dashboard_does_not_apply_system_admin_override(client, ticket_people, db_session):
    people, project = ticket_people
    db_session.add(
        Ticket(
            project_id=project.id,
            number=1,
            key="DEV-1",
            title="관리자 비참여 프로젝트 티켓",
            creator_id=people["sysadmin"].id,
        )
    )
    db_session.commit()
    login(client, "sysadmin")

    response = client.get("/api/dashboard")

    assert response.status_code == 200
    assert response.json()["counts"]["open_mine"] == 0
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "project.override_access")
        )
        == 0
    )


def test_board_groups_same_and_different_status_subtasks_and_audits_override(
    client, ticket_people, db_session
):
    people, project = ticket_people
    epic = Ticket(
        project_id=project.id,
        number=1,
        key="DEV-1",
        type="EPIC",
        title="보드 Epic",
        creator_id=people["member"].id,
    )
    db_session.add(epic)
    db_session.flush()
    task = Ticket(
        project_id=project.id,
        number=2,
        key="DEV-2",
        type="TASK",
        title="Epic Task",
        parent_id=epic.id,
        status="IN_PROGRESS",
        creator_id=people["member"].id,
    )
    no_epic = Ticket(
        project_id=project.id,
        number=5,
        key="DEV-5",
        type="TASK",
        title="Epic 없는 Task",
        creator_id=people["member"].id,
    )
    db_session.add_all([task, no_epic])
    db_session.flush()
    db_session.add_all(
        [
            Ticket(
                project_id=project.id,
                number=3,
                key="DEV-3",
                type="SUBTASK",
                title="같은 상태 Subtask",
                parent_id=task.id,
                status="IN_PROGRESS",
                creator_id=people["member"].id,
            ),
            Ticket(
                project_id=project.id,
                number=4,
                key="DEV-4",
                type="SUBTASK",
                title="다른 상태 Subtask",
                parent_id=task.id,
                status="ON_HOLD",
                creator_id=people["member"].id,
            ),
        ]
    )
    now = datetime(2026, 9, 22, tzinfo=UTC)
    batch = TicketDeletionBatch(
        project_id=project.id,
        root_ticket_key="DEV-6",
        deleted_by_id=people["manager"].id,
        deleted_at=now,
        purge_after=now + timedelta(days=30),
    )
    db_session.add(batch)
    db_session.flush()
    db_session.add(
        Ticket(
            project_id=project.id,
            number=6,
            key="DEV-6",
            type="TASK",
            title="삭제된 보드 티켓",
            creator_id=people["member"].id,
            deleted_at=now,
            deletion_batch_id=batch.id,
        )
    )
    project.next_ticket_number = 7
    db_session.commit()

    payload = client.get("/api/projects/DEV/tickets/board").json()
    epic_group = next(group for group in payload["groups"] if group["key"] == "DEV-1")
    progress = next(column for column in epic_group["columns"] if column["status"] == "IN_PROGRESS")
    hold = next(column for column in epic_group["columns"] if column["status"] == "ON_HOLD")
    assert progress["tasks"][0]["card"]["key"] == "DEV-2"
    assert [item["key"] for item in progress["tasks"][0]["subtasks"]] == ["DEV-3"]
    assert hold["detached_groups"][0]["parent_key"] == "DEV-2"
    assert [item["key"] for item in hold["detached_groups"][0]["subtasks"]] == ["DEV-4"]
    assert progress["tasks"][0]["card"]["version"] == 1
    assert progress["tasks"][0]["card"]["can_transition"] is True
    assert progress["tasks"][0]["card"]["allowed_statuses"] == [
        "DONE",
        "ON_HOLD",
        "CANCELLED",
    ]
    no_epic_group = next(group for group in payload["groups"] if group["key"] is None)
    assert no_epic_group["columns"][0]["tasks"][0]["card"]["key"] == "DEV-5"
    assert "DEV-6" not in str(payload)
    board_html = client.get("/projects/DEV/board").text
    assert "상태 변경" in board_html
    assert 'draggable="true"' in board_html
    assert "/static/board.js" in board_html

    login(client, "sysadmin")
    assert client.get("/api/projects/DEV/tickets/board").status_code == 200
    event = db_session.scalars(
        select(AuditLog)
        .where(AuditLog.action == "project.override_access")
        .order_by(AuditLog.id.desc())
    ).first()
    assert event is not None and event.details["permission"] == "read"


def test_dashboard_and_board_query_counts_do_not_grow_with_ticket_count(
    client, ticket_people, db_session, db_engine
):
    people, project = ticket_people

    def query_count(path):
        statements = []

        def capture(*args):
            statements.append(args[2])

        event.listen(db_engine, "before_cursor_execute", capture)
        try:
            response = client.get(path)
            assert response.status_code == 200
        finally:
            event.remove(db_engine, "before_cursor_execute", capture)
        return len(statements)

    empty_dashboard = query_count("/api/dashboard")
    empty_board = query_count("/api/projects/DEV/tickets/board")
    for number in range(1, 41):
        db_session.add(
            Ticket(
                project_id=project.id,
                number=number,
                key=f"DEV-{number}",
                title=f"대량 보드 티켓 {number}",
                creator_id=people["member"].id,
                assignee_id=people["member"].id if number % 2 else None,
            )
        )
    project.next_ticket_number = 41
    db_session.commit()

    assert query_count("/api/dashboard") == empty_dashboard
    assert query_count("/api/projects/DEV/tickets/board") == empty_board


def test_board_transition_metadata_dependency_permission_and_javascript(
    client, ticket_people, db_session
):
    people, project = ticket_people
    target = create_ticket(client, title="보드 선행 티켓").json()
    source = create_ticket(client, title="보드 후행 티켓").json()
    transition_ticket(client, source["key"], "IN_PROGRESS", 1)
    source_row = db_session.scalar(select(Ticket).where(Ticket.key == source["key"]))
    target_row = db_session.scalar(select(Ticket).where(Ticket.key == target["key"]))
    db_session.add_all(
        [
            TicketRelation(
                project_id=project.id,
                source_ticket_id=source_row.id,
                target_ticket_id=target_row.id,
                relation_type="DEPENDS_ON",
                dependency_kind="FS",
                created_by_id=people["member"].id,
            ),
            ProjectMember(
                project_id=project.id,
                user_id=people["outsider"].id,
                role="PROJECT_USER",
            ),
        ]
    )
    db_session.commit()

    def find_card(payload, key):
        for group in payload["groups"]:
            for column in group["columns"]:
                for task in column["tasks"]:
                    for card in [task["card"], *task["subtasks"]]:
                        if card["key"] == key:
                            return card
                for detached in column["detached_groups"]:
                    for card in detached["subtasks"]:
                        if card["key"] == key:
                            return card
        raise AssertionError(f"card not found: {key}")

    member_board = client.get("/api/projects/DEV/tickets/board").json()
    source_card = find_card(member_board, source["key"])
    assert source_card["version"] == 2
    assert source_card["can_transition"] is True
    assert "DONE" in source_card["allowed_statuses"]
    assert source_card["completion_blocked"] is True
    html = client.get("/projects/DEV/board").text
    assert "의존 대상이 완료될 때까지 완료로 이동할 수 없습니다." in html
    assert "완료 · 의존성 미완료" in html
    assert "data-board-status" in html

    login(client, "outsider")
    outsider_card = find_card(
        client.get("/api/projects/DEV/tickets/board").json(), source["key"]
    )
    assert outsider_card["can_transition"] is True
    assert outsider_card["allowed_statuses"]

    login(client, "guest")
    guest_card = find_card(
        client.get("/api/projects/DEV/tickets/board").json(), source["key"]
    )
    assert guest_card["can_transition"] is False
    assert guest_card["allowed_statuses"] == []

    login(client, "member")
    project.is_active = False
    db_session.commit()
    inactive_card = find_card(
        client.get("/api/projects/DEV/tickets/board").json(), source["key"]
    )
    assert inactive_card["can_transition"] is False

    script = client.get("/static/board.js")
    assert script.status_code == 200
    assert "expected_version" in script.text
    assert "X-CSRF-Token" in script.text
    assert "window.location.reload()" in script.text
