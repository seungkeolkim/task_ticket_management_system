"""사용자별 공용 규칙·날짜 재해석·목록/count·칸반·저장과 권한을 검증한다."""

import json
from datetime import UTC, date, datetime

import pytest
from filter_helpers import filter_condition, filter_definition
from sqlalchemy import delete
from test_tickets import board_filter_cards, create_ticket, login, post
from test_tickets import ticket_people as ticket_people

from app.models import SavedFilter, Ticket
from app.services import ticket_filter_resolution


def dynamic_condition(field, operator, rule):
    """일반 조건 트리에 조합할 동적 규칙 하나를 만든다."""
    return filter_condition(field, operator) | {"rule": rule}


@pytest.fixture(autouse=True)
def cleanup_temporary_dynamic_filters(db_session):
    """임시 DB teardown의 구 계약 downgrade 전에 테스트 저장 필터를 명시적으로 정리한다."""
    yield
    db_session.execute(delete(SavedFilter))
    db_session.commit()


def test_shared_mine_resolves_each_user_guest_and_override(client, ticket_people):
    """동일 규칙이 적용자마다 달라지고 후보에 없는 actor도 정상 조회한다."""
    people, _ = ticket_people
    mine = create_ticket(client, title="내가 생성한 미지정").json()
    create_ticket(client, title="다른 사람 담당", assignee_id=people["manager"].id)
    login(client, "manager")
    theirs = create_ticket(client, title="관리자 생성 미지정").json()
    definition = filter_definition(
        dynamic_condition("assignee", "in", {"kind": "current_user"}),
        filter_definition(
            filter_condition("assignee", "is_empty"),
            dynamic_condition("creator", "in", {"kind": "current_user"}),
        )["expression"],
        logical_operator="OR",
    )
    saved = post(
        client,
        "/api/projects/DEV/shared-filters",
        {"name": "공용 내 이슈", "definition": definition},
    ).json()
    for login_name, expected_total in [
        ("member", 1),
        ("manager", 2),
        ("guest", 0),
        ("sysadmin", 0),
    ]:
        login(client, login_name)
        loaded = client.get(f"/api/projects/DEV/shared-filters/{saved['id']}")
        assert loaded.status_code == 200
        parameters = {"filter": json.dumps(loaded.json()["definition"])}
        result = client.get("/api/projects/DEV/tickets", params=parameters)
        assert result.status_code == 200
        payload = result.json()
        assert payload["total"] == expected_total
        assert payload["filter_resolution"]["user_id"] == people[login_name].id
        board = client.get("/api/projects/DEV/tickets/board", params=parameters).json()
        assert len(board_filter_cards(board)) == expected_total
        assert client.get("/projects/DEV/board", params=parameters).status_code == 200
        if login_name == "member":
            assert payload["tickets"][0]["key"] == mine["key"]
        if login_name == "manager":
            assert theirs["key"] in {ticket["key"] for ticket in payload["tickets"]}
    login(client, "outsider")
    assert client.get("/api/projects/DEV/tickets", params=parameters).status_code == 404


def test_saved_date_rule_reapplies_at_korea_midnight_once_per_request(
    client, db_session, ticket_people, monkeypatch
):
    """같은 요청은 하나의 기준을 사용하고 자정 이후 같은 URL도 새 날짜로 해석한다."""
    first = create_ticket(client, title="일요일 마감").json()
    second = create_ticket(client, title="월요일 마감").json()
    db_session.get(Ticket, first["id"]).due_date = date(2026, 10, 11)
    db_session.get(Ticket, second["id"]).due_date = date(2026, 10, 12)
    db_session.commit()
    definition = filter_definition(dynamic_condition("due_date", "on", {"kind": "today"}))
    saved = post(
        client,
        "/api/projects/DEV/personal-filters",
        {"name": "오늘 마감", "definition": definition},
    ).json()
    parameters = {"filter": json.dumps(definition)}
    calls = []
    current_time = datetime(2026, 10, 11, 14, 59, 59, tzinfo=UTC)

    def request_clock():
        """자정 경계 검증용 기준 시각을 반환하고 호출 횟수를 기록한다."""
        calls.append(current_time)
        return current_time

    monkeypatch.setattr(ticket_filter_resolution, "utc_now", request_clock)
    before = client.get("/api/projects/DEV/tickets", params=parameters).json()
    assert len(calls) == 1
    assert before["total"] == 1 and before["tickets"][0]["key"] == first["key"]
    current_time = datetime(2026, 10, 11, 15, 0, 0, tzinfo=UTC)
    after = client.get("/api/projects/DEV/tickets", params=parameters).json()
    assert len(calls) == 2
    assert after["total"] == 1 and after["tickets"][0]["key"] == second["key"]
    assert after["filter_resolution"]["reference_date"] == "2026-10-12"
    stored = db_session.get(SavedFilter, saved["id"]).definition
    assert stored["expression"]["children"][0]["rule"] == {"kind": "today"}
    assert stored["expression"]["children"][0]["values"] == []


def test_working_week_sql_timestamp_bounds_and_negated_null(
    client, db_session, ticket_people, monkeypatch
):
    """월요일 00시~토요일 00시 직전과 NULL 부정 의미를 실제 DB에서 검증한다."""
    rows = [create_ticket(client, title=f"날짜 경계 {index}").json() for index in range(3)]
    for row, timestamp in zip(
        rows,
        [
            datetime(2026, 10, 4, 15, tzinfo=UTC),
            datetime(2026, 10, 9, 14, 59, 59, tzinfo=UTC),
            datetime(2026, 10, 9, 15, tzinfo=UTC),
        ],
        strict=True,
    ):
        db_session.get(Ticket, row["id"]).updated_at = timestamp
    db_session.commit()
    monkeypatch.setattr(
        ticket_filter_resolution, "utc_now", lambda: datetime(2026, 10, 11, tzinfo=UTC)
    )
    definition = filter_definition(
        dynamic_condition("updated_date", "between", {"kind": "working_week", "week": "this"})
    )
    result = client.get(
        "/api/projects/DEV/tickets", params={"filter": json.dumps(definition)}
    ).json()
    assert {ticket["key"] for ticket in result["tickets"]} == {rows[0]["key"], rows[1]["key"]}
    definition = filter_definition(
        dynamic_condition("due_date", "on", {"kind": "today"}) | {"negated": True}
    )
    assert (
        client.get("/api/projects/DEV/tickets", params={"filter": json.dumps(definition)}).json()[
            "total"
        ]
        == 3
    )


def test_independent_last_week_boundaries_save_and_query_both_date_types(
    client, db_session, ticket_people, monkeypatch
):
    """월요일 보고용 지난주 월~금 전체와 Date·timestamp 경계 및 저장 규칙을 검증한다."""
    rows = [create_ticket(client, title=f"지난주 경계 {index}").json() for index in range(3)]
    timestamps = [
        datetime(2026, 10, 4, 15, tzinfo=UTC),
        datetime(2026, 10, 9, 14, 59, 59, tzinfo=UTC),
        datetime(2026, 10, 9, 15, tzinfo=UTC),
    ]
    dates = [date(2026, 10, 5), date(2026, 10, 9), date(2026, 10, 10)]
    for row, timestamp, due_date in zip(rows, timestamps, dates, strict=True):
        ticket = db_session.get(Ticket, row["id"])
        ticket.updated_at = timestamp
        ticket.due_date = due_date
    db_session.commit()
    monkeypatch.setattr(
        ticket_filter_resolution, "utc_now", lambda: datetime(2026, 10, 12, tzinfo=UTC)
    )
    rule = {
        "kind": "date_range",
        "start": {"kind": "week_day", "week": "last", "weekday": 0},
        "end": {"kind": "week_day", "week": "last", "weekday": 4},
    }
    expected_keys = {rows[0]["key"], rows[1]["key"]}
    for field in ["updated_date", "due_date"]:
        definition = filter_definition(dynamic_condition(field, "between", rule))
        result = client.get(
            "/api/projects/DEV/tickets", params={"filter": json.dumps(definition)}
        ).json()
        assert {ticket["key"] for ticket in result["tickets"]} == expected_keys
        assert result["total"] == 2
        assert result["filter_resolution"]["conditions"][0]["values"] == [
            "2026-10-05",
            "2026-10-09",
        ]
        board = client.get(
            "/api/projects/DEV/tickets/board", params={"filter": json.dumps(definition)}
        ).json()
        assert {card["key"] for card in board_filter_cards(board)} == expected_keys
    saved = post(
        client,
        "/api/projects/DEV/personal-filters",
        {"name": "지난주 보고용", "definition": definition},
    ).json()
    loaded = client.get(f"/api/projects/DEV/personal-filters/{saved['id']}").json()
    assert loaded["definition"]["expression"]["children"][0]["rule"] == rule
    assert loaded["definition"]["expression"]["children"][0]["values"] == []
    single = filter_definition(
        dynamic_condition("due_date", "on", {"kind": "week_day", "week": "last", "weekday": 4})
    )
    assert (
        client.get("/api/projects/DEV/tickets", params={"filter": json.dumps(single)}).json()[
            "tickets"
        ][0]["key"]
        == rows[1]["key"]
    )
    reverse = rule | {"start": rule["end"], "end": rule["start"]}
    invalid = filter_definition(dynamic_condition("due_date", "between", reverse))
    response = client.get("/api/projects/DEV/tickets", params={"filter": json.dumps(invalid)})
    assert response.status_code == 400
    assert "기간 시작은 종료보다 늦을 수 없습니다" in response.json()["message"]
