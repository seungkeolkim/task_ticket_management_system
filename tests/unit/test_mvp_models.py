from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from app.models import (
    Attachment,
    Comment,
    Mention,
    Organization,
    Project,
    ProjectMember,
    ReportAttempt,
    ReportRun,
    ReportRunProject,
    ReportSkill,
    ReportSkillVersion,
    SavedFilter,
    Ticket,
    TicketDeletionBatch,
    TicketHistory,
    TicketRelation,
    User,
)
from app.schemas.contracts import ReportInput, ReportOutput, TicketFilter

NOW = datetime(2026, 9, 17, 0, 0, tzinfo=UTC)


@pytest.fixture
def work(db_session: Session) -> tuple[User, Project, Ticket, Ticket, Project, Ticket]:
    org = Organization(key="root", name="조직")
    db_session.add(org)
    db_session.flush()
    user = User(
        login_id="user", display_name="사용자", password_hash="hash", organization_id=org.id
    )
    db_session.add(user)
    db_session.flush()
    first = Project(key="DEV", name="개발", created_by_id=user.id)
    second = Project(key="OPS", name="운영", created_by_id=user.id)
    db_session.add_all([first, second])
    db_session.flush()
    a = Ticket(project_id=first.id, number=1, key="DEV-1", title="첫 업무", creator_id=user.id)
    b = Ticket(project_id=first.id, number=2, key="DEV-2", title="둘째 업무", creator_id=user.id)
    c = Ticket(project_id=second.id, number=1, key="OPS-1", title="다른 업무", creator_id=user.id)
    db_session.add_all([a, b, c])
    db_session.flush()
    return user, first, a, b, second, c


@pytest.mark.parametrize(
    "invalid",
    [
        {"type": "SUBTASK"},
        {"status": "UNKNOWN"},
        {"priority": "URGENT"},
        {"progress_percent": 101},
        {"progress_percent": -1},
        {"version": 0},
        {"number": 0},
        {"body_schema_version": 0},
        {"planned_start_date": date(2026, 9, 18), "planned_end_date": date(2026, 9, 17)},
        {"deleted_at": NOW},
    ],
)
def test_ticket_constraints(db_session: Session, work: tuple, invalid: dict) -> None:
    _, project, ticket, *_ = work
    # SQL UPDATE exercises the DB without the ORM version generator repairing input.
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.execute(
            Ticket.__table__.update().where(Ticket.id == ticket.id).values(**invalid)
        )


def test_membership_and_ticket_number_uniqueness(db_session: Session, work: tuple) -> None:
    user, project, ticket, *_ = work
    db_session.add(ProjectMember(project_id=project.id, user_id=user.id))
    db_session.flush()
    for duplicate in (
        ProjectMember(project_id=project.id, user_id=user.id),
        Ticket(
            project_id=project.id,
            number=ticket.number,
            key="DEV-999",
            title="중복",
            creator_id=user.id,
        ),
    ):
        with pytest.raises(IntegrityError), db_session.begin_nested():
            db_session.add(duplicate)
            db_session.flush()


def test_cross_project_parent_relation_and_deletion_batch_rejected(
    db_session: Session,
    work: tuple,
) -> None:
    user, project, a, _, other, foreign = work
    batch = TicketDeletionBatch(
        project_id=other.id,
        root_ticket_key=foreign.key,
        deleted_by_id=user.id,
        deleted_at=NOW,
        purge_after=NOW + timedelta(days=30),
    )
    db_session.add(batch)
    db_session.flush()
    for values in (
        {"parent_id": foreign.id},
        {"parent_id": a.id},
        {"deletion_batch_id": batch.id, "deleted_at": NOW},
    ):
        with pytest.raises(IntegrityError), db_session.begin_nested():
            db_session.execute(Ticket.__table__.update().where(Ticket.id == a.id).values(**values))
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(
            TicketRelation(
                project_id=project.id,
                source_ticket_id=a.id,
                target_ticket_id=foreign.id,
                relation_type="DEPENDS_ON",
                dependency_kind="FS",
                created_by_id=user.id,
            )
        )
        db_session.flush()


def test_relation_direction_uniqueness_and_schedule(db_session: Session, work: tuple) -> None:
    user, project, a, b, *_ = work
    relation = dict(
        project_id=project.id,
        source_ticket_id=a.id,
        target_ticket_id=b.id,
        relation_type="RELATED",
        created_by_id=user.id,
    )
    db_session.add(TicketRelation(**relation))
    db_session.flush()
    for overrides in (
        {},
        {"source_ticket_id": b.id, "target_ticket_id": a.id},
        {"target_ticket_id": a.id},
        {"lag_days": 1},
        {"relation_type": "DEPENDS_ON"},
        {"relation_type": "DEPENDS_ON", "dependency_kind": "BAD"},
    ):
        with pytest.raises(IntegrityError), db_session.begin_nested():
            db_session.add(TicketRelation(**(relation | overrides)))
            db_session.flush()
    db_session.add(
        TicketRelation(
            **(
                relation
                | {
                    "relation_type": "DEPENDS_ON",
                    "dependency_kind": "FS",
                    "lag_days": 2,
                }
            )
        )
    )
    db_session.flush()


def test_comment_attachment_mention_scope_and_deduplication(
    db_session: Session, work: tuple
) -> None:
    user, project, a, b, other, foreign = work
    comment = Comment(project_id=project.id, ticket_id=a.id, author_id=user.id, body="**진행**")
    db_session.add(comment)
    db_session.flush()
    for ticket in (b, foreign):
        for entity in (
            Mention(
                project_id=ticket.project_id,
                ticket_id=ticket.id,
                comment_id=comment.id,
                target_user_id=user.id,
                mentioned_by_id=user.id,
            ),
            Attachment(
                project_id=ticket.project_id,
                ticket_id=ticket.id,
                comment_id=comment.id,
                uploaded_by_id=user.id,
                original_filename="문서.txt",
                media_type="text/plain",
                size_bytes=1,
                storage_key=str(uuid4()),
            ),
        ):
            with pytest.raises(IntegrityError), db_session.begin_nested():
                db_session.add(entity)
                db_session.flush()
    for comment_id in (None, comment.id):
        values = dict(
            project_id=project.id,
            ticket_id=a.id,
            comment_id=comment_id,
            target_user_id=user.id,
            mentioned_by_id=user.id,
        )
        db_session.add(Mention(**values))
        db_session.flush()
        with pytest.raises(IntegrityError), db_session.begin_nested():
            db_session.add(Mention(**values))
            db_session.flush()


def test_round_trip_schedule_body_filter_history_and_report(
    db_session: Session, work: tuple
) -> None:
    user, project, ticket, *_ = work
    ticket.planned_start_date = date(2026, 9, 14)
    ticket.planned_end_date = date(2026, 9, 18)
    ticket.sort_order = Decimal("12.250001")
    ticket.description = "# 목표\n한글 Markdown"
    ticket.actual_started_at = NOW
    db_session.flush()
    history = TicketHistory(
        project_id=project.id,
        ticket_id=ticket.id,
        event_key=str(uuid4()),
        operation_id=str(uuid4()),
        ticket_version=ticket.version,
        event_type="UPDATED",
        actor_id=user.id,
        before_state={"status": "TODO"},
        after_state={"status": "IN_PROGRESS"},
        changes=[{"field": "status", "before": "TODO", "after": "IN_PROGRESS"}],
    )
    saved = SavedFilter(
        project_id=project.id,
        owner_id=user.id,
        name="내 업무",
        definition=TicketFilter(assignee_ids=[user.id]).model_dump(mode="json"),
    )
    skill = ReportSkill(key="weekly-report", name="주간보고", created_by_id=user.id)
    db_session.add_all([history, saved, skill])
    db_session.flush()
    version = ReportSkillVersion(
        skill_id=skill.id,
        version=1,
        instructions_markdown="근거에 기반해 보고서를 작성한다.",
        input_json_schema=ReportInput.model_json_schema(),
        output_json_schema=ReportOutput.model_json_schema(),
        content_sha256="a" * 64,
        created_by_id=user.id,
    )
    db_session.add(version)
    db_session.flush()
    run = ReportRun(
        key=str(uuid4()),
        requested_by_id=user.id,
        skill_version_id=version.id,
        title="주간보고",
        period_start=NOW - timedelta(days=7),
        period_end=NOW,
        selection={},
        input_payload={"tickets": [{"key": ticket.key}]},
        input_sha256="b" * 64,
        captured_at=NOW,
    )
    db_session.add(run)
    db_session.flush()
    db_session.add(ReportRunProject(run_id=run.id, project_id=project.id))
    attempt = ReportAttempt(
        run_id=run.id,
        attempt_number=1,
        runtime_profile="local-default",
        provider="local",
        model_name="example-model",
        generation_parameters={"temperature": 0},
        request_payload={"messages": [{"role": "user", "content": "주간보고"}]},
        response_text="# 주간보고\n개발 진행",
        output_markdown="# 주간보고\n개발 진행",
        output_payload={"markdown": "# 주간보고\n개발 진행"},
        status="SUCCEEDED",
        started_at=NOW,
        finished_at=NOW + timedelta(seconds=1),
    )
    db_session.add(attempt)
    db_session.flush()
    db_session.expire_all()
    assert ticket.sort_order == Decimal("12.250001")
    assert ticket.actual_started_at == NOW
    assert "한글" in ticket.description
    assert history.after_state["status"] == "IN_PROGRESS"
    assert saved.definition["assignee_ids"] == [user.id]
    assert attempt.request_payload["messages"][0]["content"] == "주간보고"
    assert attempt.output_markdown.startswith("# 주간보고")
    # Ticket purge removes its live history, but preserves the report's frozen evidence.
    db_session.execute(delete(Ticket).where(Ticket.id == ticket.id))
    db_session.flush()
    assert db_session.scalar(select(TicketHistory.id)) is None
    assert run.input_payload["tickets"][0]["key"] == "DEV-1"


def test_report_success_requires_output_and_skill_version_unique(
    db_session: Session, work: tuple
) -> None:
    user, *_ = work
    skill = ReportSkill(key="weekly", name="주간", created_by_id=user.id)
    db_session.add(skill)
    db_session.flush()
    values = dict(
        skill_id=skill.id,
        version=1,
        instructions_markdown="지침",
        input_json_schema={},
        output_json_schema={},
        content_sha256="a" * 64,
        created_by_id=user.id,
    )
    version = ReportSkillVersion(**values)
    db_session.add(version)
    db_session.flush()
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(ReportSkillVersion(**values))
        db_session.flush()
    run = ReportRun(
        key=str(uuid4()),
        requested_by_id=user.id,
        skill_version_id=version.id,
        title="보고서",
        period_start=NOW - timedelta(days=7),
        period_end=NOW,
        selection={},
    )
    db_session.add(run)
    db_session.flush()
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(
            ReportAttempt(
                run_id=run.id,
                attempt_number=1,
                runtime_profile="local",
                provider="local",
                model_name="test",
                generation_parameters={},
                request_payload={},
                status="SUCCEEDED",
            )
        )
        db_session.flush()


def test_optimistic_locking_rejects_stale_ticket(
    db_session: Session,
    db_session_factory: sessionmaker[Session],
    work: tuple,
) -> None:
    _, _, ticket, *_ = work
    db_session.commit()
    with db_session_factory() as second:
        stale = second.get(Ticket, ticket.id)
        assert stale is not None
        ticket.title = "변경된 제목"
        db_session.commit()
        stale.title = "오래된 수정"
        with pytest.raises(StaleDataError):
            second.flush()


def test_root_and_sibling_organization_names_are_unique(db_session: Session) -> None:
    root = Organization(key="a", name="본부")
    db_session.add(root)
    db_session.flush()
    child = Organization(key="b", name="팀", parent_id=root.id)
    db_session.add(child)
    db_session.flush()
    for values in ({"name": "본부"}, {"name": "팀", "parent_id": root.id}):
        with pytest.raises(IntegrityError), db_session.begin_nested():
            db_session.add(Organization(key=str(uuid4()), **values))
            db_session.flush()


def test_history_coverage_and_purge_marker_round_trip(db_session: Session, work: tuple) -> None:
    user, project, ticket, *_ = work
    assert project.history_complete_from is None  # Unknown until history recording is initialized.
    project.history_complete_from = NOW
    batch = TicketDeletionBatch(
        project_id=project.id,
        root_ticket_key=ticket.key,
        deleted_by_id=user.id,
        deleted_at=NOW,
        purge_after=NOW + timedelta(days=30),
        purged_at=NOW + timedelta(days=30),
    )
    db_session.add(batch)
    db_session.flush()
    db_session.expire_all()
    assert project.history_complete_from == NOW
    assert batch.purged_at == NOW + timedelta(days=30)
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.execute(
            TicketDeletionBatch.__table__.update()
            .where(TicketDeletionBatch.id == batch.id)
            .values(restored_at=NOW + timedelta(days=1))
        )
