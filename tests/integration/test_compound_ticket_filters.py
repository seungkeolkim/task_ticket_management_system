"""복합 조건이 권한·목록/count·칸반·저장 경계를 함께 통과하는지 검증한다."""

import json
from datetime import UTC, datetime

import pytest
from filter_helpers import filter_condition, filter_definition, filter_url
from test_tickets import board_filter_cards, create_ticket, delete, login, post
from test_tickets import ticket_people as ticket_people

from app.models import Project, Ticket


def test_nested_or_and_not_same_fields_and_null(client, ticket_people):
    """서로 다른 필드의 OR와 그룹 NOT이 미지정 값도 정확히 판정한다."""
    people, _ = ticket_people
    assigned = create_ticket(client, title="담당 업무", assignee_id=people["manager"].id).json()
    unassigned = create_ticket(client, title="미지정 긴급", priority="BLOCKER").json()
    create_ticket(client, title="제외 업무")
    expression = filter_definition(
        filter_definition(
            filter_condition("assignee", "in", people["manager"].id),
            filter_condition("status", "in", "TODO"),
        )["expression"],
        filter_definition(
            filter_condition("assignee", "is_empty"),
            filter_condition("priority", "in", "BLOCKER"),
        )["expression"],
        logical_operator="OR",
    )
    parameters = {"filter": json.dumps(expression)}
    response = client.get("/api/projects/DEV/tickets", params=parameters)
    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert {ticket["id"] for ticket in response.json()["tickets"]} == {
        assigned["id"],
        unassigned["id"],
    }
    board = client.get("/api/projects/DEV/tickets/board", params=parameters).json()
    assert {card["key"] for card in board_filter_cards(board)} == {
        assigned["key"],
        unassigned["key"],
    }
    negated_query = filter_url(
        "/api/projects/DEV/tickets",
        filter_condition("assignee", "in", people["manager"].id),
        negated=True,
    )
    assert client.get(negated_query).json()["total"] == 2
    same_fields = filter_url(
        "/api/projects/DEV/tickets",
        filter_condition("assignee", "not_in", people["manager"].id),
        filter_condition("assignee", "is_not_empty"),
    )
    assert client.get(same_fields).json()["total"] == 0


def test_compound_saved_filters_restore_and_revalidate_negated_references(client, ticket_people):
    """개인·공유 저장에서도 중첩을 보존하고 NOT 안의 잘못된 참조를 거부한다."""
    people, _ = ticket_people
    definition = filter_definition(
        filter_condition("type", "in", "TASK", "SUBTASK"),
        filter_definition(
            filter_condition("assignee", "in", people["member"].id, people["manager"].id),
            filter_condition("assignee", "is_empty"),
            logical_operator="OR",
        )["expression"],
    )
    for scope in ["personal", "shared"]:
        if scope == "shared":
            login(client, "manager")
        endpoint = f"/api/projects/DEV/{scope}-filters"
        created = post(client, endpoint, {"name": "복합 필터", "definition": definition})
        assert created.status_code == 201
        identifier = created.json()["id"]
        loaded = client.get(f"{endpoint}/{identifier}").json()["definition"]
        assert loaded["expression"] == definition["expression"]
        applied = client.get(f"/projects/DEV/{scope}-filters/{identifier}/apply?view=board")
        assert applied.status_code == 200
        assert "data-filter-definition" in applied.text
        invalid = filter_definition(filter_condition("assignee", "not_in", people["outsider"].id))
        assert (
            post(client, endpoint, {"name": "잘못된 참조", "definition": invalid}).status_code
            == 400
        )


def test_date_boundaries_and_negated_missing_due_date(client, ticket_people, db_session):
    """날짜 전체와 이후 경계, 마감일 NULL의 NOT을 검증한다."""
    first_ticket = create_ticket(client, due_date="2026-10-11").json()
    next_ticket = create_ticket(client).json()
    db_session.get(Ticket, first_ticket["id"]).updated_at = datetime(
        2026, 10, 11, 14, 59, 59, tzinfo=UTC
    )
    db_session.get(Ticket, next_ticket["id"]).updated_at = datetime(2026, 10, 11, 15, 0, tzinfo=UTC)
    db_session.commit()
    on_date = client.get(
        filter_url(
            "/api/projects/DEV/tickets", filter_condition("updated_date", "on", "2026-10-11")
        )
    ).json()
    after_date = client.get(
        filter_url(
            "/api/projects/DEV/tickets", filter_condition("updated_date", "after", "2026-10-11")
        )
    ).json()
    assert [ticket["id"] for ticket in on_date["tickets"]] == [first_ticket["id"]]
    assert [ticket["id"] for ticket in after_date["tickets"]] == [next_ticket["id"]]
    negated_due = client.get(
        filter_url(
            "/api/projects/DEV/tickets",
            filter_condition("due_date", "on", "2026-10-11", negated=True),
        )
    ).json()
    assert [ticket["id"] for ticket in negated_due["tickets"]] == [next_ticket["id"]]


@pytest.mark.parametrize(
    "payload",
    [
        "{",
        "null",
        "[]",
        json.dumps(
            filter_definition(
                {"kind": "condition", "field": "project_id", "operator": "in", "values": [1]}
            )
        ),
        json.dumps(filter_definition(filter_condition("type", "in", "INVALID"))),
        json.dumps(
            filter_definition(
                filter_condition("created_date", "between", "2026-10-11", "2026-10-10")
            )
        ),
    ],
)
def test_api_and_html_reject_invalid_compound_inputs(client, ticket_people, payload):
    """오류 입력을 무시해 전체 조회하지 않고 두 요청 경계에서 거부한다."""
    assert client.get("/api/projects/DEV/tickets", params={"filter": payload}).status_code == 400
    assert client.get("/projects/DEV/board", params={"filter": payload}).status_code == 400


def test_filter_rejects_old_parameters_duplicates_and_size(client, ticket_people):
    """v1 query와 중복 filter·입력 크기를 명시적으로 차단한다."""
    assert client.get("/api/projects/DEV/tickets?type=TASK").status_code == 400
    assert (
        client.get("/projects/DEV/board", params=[("filter", "{}"), ("filter", "{}")]).status_code
        == 400
    )
    assert client.get("/projects/DEV/board", params={"filter": " " * 4097}).status_code == 400


def test_or_and_not_cannot_expand_project_or_trash_scope(client, ticket_people, db_session):
    """항상 참인 OR와 NOT 조합에서도 타 프로젝트·휴지통 티켓은 노출하지 않는다."""
    people, _ = ticket_people
    visible_ticket = create_ticket(client, title="표시할 업무").json()
    deleted_ticket = create_ticket(client, title="삭제된 업무").json()
    assert (
        delete(
            client,
            f"/api/projects/DEV/tickets/{deleted_ticket['key']}",
            {"expected_version": deleted_ticket["version"]},
        ).status_code
        == 200
    )
    hidden_project = Project(key="SECRET", name="숨김", created_by_id=people["sysadmin"].id)
    db_session.add(hidden_project)
    db_session.flush()
    db_session.add(
        Ticket(
            project_id=hidden_project.id,
            creator_id=people["sysadmin"].id,
            number=1,
            key="SECRET-1",
            title="숨김 업무",
            type="TASK",
        )
    )
    db_session.commit()
    definition = filter_definition(
        filter_condition("search", "contains", "일치하지 않는 검색"),
        filter_condition("search", "not_contains", "일치하지 않는 검색"),
        logical_operator="OR",
    )
    parameters = {"filter": json.dumps(definition)}
    response = client.get("/api/projects/DEV/tickets", params=parameters).json()
    assert response["total"] == 1
    assert [ticket["id"] for ticket in response["tickets"]] == [visible_ticket["id"]]
    board = client.get("/api/projects/DEV/tickets/board", params=parameters).json()
    assert [card["key"] for card in board_filter_cards(board)] == [visible_ticket["key"]]
