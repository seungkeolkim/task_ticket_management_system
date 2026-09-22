from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.domain.auth import hash_password
from app.models import (
    AuditLog,
    Organization,
    Project,
    ProjectMember,
    Ticket,
    TicketHistory,
    User,
)
from app.schemas.contracts import TicketEvent
from app.schemas.tickets import TicketCreate
from app.services import tickets as service
from app.services.auth import current_identity

PASSWORD = "Ticket-test-password-123!"
ORIGIN = {"Origin": "http://testserver"}


def token(client):
    return client.get("/api/auth/csrf").json()["csrf_token"]


def post(client, path, payload):
    return client.post(path, json=payload, headers=ORIGIN | {"X-CSRF-Token": token(client)})


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
    for name in ["sysadmin", "manager", "member", "outsider"]:
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
    assert create_ticket(client).status_code == 404
    assert client.get("/projects/DEV/tickets").status_code == 404


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
    assert override_events and override_events[-1].details["permission"] == "read"
