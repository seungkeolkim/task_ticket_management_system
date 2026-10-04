"""DB 기반 cron 설정 복원과 crontab 생성 검증."""

import pytest
from alembic import command
from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session, sessionmaker

from app import scheduler
from app.db.engine import create_database_engine
from app.models import ScheduledJob, ScheduledJobRun


def test_scheduler_tables_start_empty_and_survive_migration_roundtrip(
    alembic_config, migrated_database_url: str
) -> None:
    """기존 migration 위에 빈 설정·이력 테이블을 추가하고 되돌릴 수 있다."""
    engine = create_database_engine(migrated_database_url)
    try:
        with engine.connect() as connection:
            assert {"scheduled_jobs", "scheduled_job_runs"} <= set(
                inspect(connection).get_table_names()
            )
            assert connection.scalar(select(func.count()).select_from(ScheduledJob)) == 0
            assert connection.scalar(select(func.count()).select_from(ScheduledJobRun)) == 0
        command.downgrade(alembic_config, "20261004_0008")
        with engine.connect() as connection:
            assert "scheduled_jobs" not in inspect(connection).get_table_names()
            assert "tickets" in inspect(connection).get_table_names()
        command.upgrade(alembic_config, "head")
        command.check(alembic_config)
    finally:
        engine.dispose()


def test_scheduler_reinstalls_crontab_only_when_db_schedule_changes(
    db_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """기동 시 복원하고 활성·시각 변경을 DB 내용대로 다시 반영한다."""
    installed_crontabs: list[str] = []
    monkeypatch.setattr(scheduler, "SessionLocal", db_session_factory)
    monkeypatch.setattr(scheduler, "install_crontab", installed_crontabs.append)
    monkeypatch.setitem(scheduler.JOB_HANDLERS, "example_job", lambda: None)
    try:
        with db_session_factory.begin() as session:
            session.add(
                ScheduledJob(
                    job_key="example_job",
                    cron_expression="0 * * * *",
                    timezone_name="Asia/Seoul",
                    is_enabled=True,
                )
            )
        first_contents = scheduler.synchronize_crontab(None)
        assert "0 * * * *" in first_contents
        assert "app.scheduler_trigger example_job" in first_contents
        assert scheduler.synchronize_crontab(first_contents) == first_contents
        assert len(installed_crontabs) == 1

        with db_session_factory.begin() as session:
            job = session.scalar(select(ScheduledJob))
            assert job is not None
            job.cron_expression = "15 2 * * *"
        changed_contents = scheduler.synchronize_crontab(first_contents)
        assert "15 2 * * *" in changed_contents
        assert len(installed_crontabs) == 2

        with db_session_factory.begin() as session:
            job = session.scalar(select(ScheduledJob))
            assert job is not None
            job.is_enabled = False
        empty_contents = scheduler.synchronize_crontab(changed_contents)
        assert "app.scheduler_trigger example_job" not in empty_contents
        assert len(installed_crontabs) == 3
        assert scheduler.synchronize_crontab(None) == empty_contents
        assert len(installed_crontabs) == 4
    finally:
        scheduler.JOB_HANDLERS.pop("example_job", None)


def test_scheduler_restart_marks_unfinished_run_interrupted(
    db_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """재기동 후 이전 프로세스의 RUNNING 결과가 성공으로 남지 않는다."""
    with db_session_factory.begin() as session:
        job = ScheduledJob(
            job_key="example_job",
            cron_expression="0 * * * *",
            timezone_name="Asia/Seoul",
            is_enabled=False,
        )
        session.add(job)
        session.flush()
        session.add(
            ScheduledJobRun(
                scheduled_job_id=job.id,
                trigger_source="CRON",
                status="RUNNING",
            )
        )
        session.add(
            ScheduledJobRun(
                scheduled_job_id=job.id,
                trigger_source="MANUAL",
                status="RUNNING",
            )
        )
    monkeypatch.setattr(scheduler, "SessionLocal", db_session_factory)
    scheduler.mark_interrupted_runs()
    with db_session_factory() as session:
        job_runs = session.scalars(select(ScheduledJobRun).order_by(ScheduledJobRun.id)).all()
        assert job_runs[0].status == "FAILED"
        assert job_runs[0].result_code == "interrupted"
        assert job_runs[0].finished_at is not None
        assert job_runs[1].status == "RUNNING"


def test_schedule_token_changes_with_db_cron_definition() -> None:
    """변경 전 crontab의 trigger가 새 일정과 구별되는지 검증한다."""
    previous_schedule = scheduler.ScheduleDefinition("example_job", "0 * * * *", "Asia/Seoul")
    updated_schedule = scheduler.ScheduleDefinition("example_job", "5 * * * *", "Asia/Seoul")
    assert scheduler.schedule_token(previous_schedule) != scheduler.schedule_token(updated_schedule)


@pytest.mark.parametrize(
    "job_key,cron_expression,timezone_name",
    [
        ("missing_job", "0 * * * *", "Asia/Seoul"),
        ("example_job", "* * * * *\n* * * * *", "Asia/Seoul"),
        ("example_job", "0 * * * *", "UTC"),
    ],
)
def test_crontab_rejects_unknown_job_injection_and_timezone_mismatch(
    job_key: str, cron_expression: str, timezone_name: str
) -> None:
    """DB 설정이 임의 명령이나 다른 timezone으로 cron을 바꾸지 못한다."""
    with pytest.raises(ValueError):
        scheduler.render_crontab(
            [scheduler.ScheduleDefinition(job_key, cron_expression, timezone_name)],
            python_executable="/usr/local/bin/python",
            registered_job_keys={"example_job"},
        )
