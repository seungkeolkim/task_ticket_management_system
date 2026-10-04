"""DB schedule을 crontab으로 복원하고 cron trigger를 작업에 연결한다."""

import argparse
import hashlib
import logging
import os
import re
import shlex
import signal
import socket
import subprocess
import sys
from dataclasses import dataclass

from sqlalchemy import select, update

from app.core.config import ensure_data_directories, get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.db.types import utc_now
from app.models.scheduler import ScheduledJob, ScheduledJobRun
from app.scheduler_jobs import JOB_HANDLERS
from app.scheduler_trigger import SOCKET_PATH

logger = logging.getLogger(__name__)
SCHEDULER_TIMEZONE = "Asia/Seoul"
CRON_EXPRESSION_PATTERN = re.compile(r"^[0-9*,/\-]+(?: [0-9*,/\-]+){4}$")
JOB_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
SCHEDULE_TOKEN_PATTERN = re.compile(r"^[0-9a-f]{16}$")


@dataclass(frozen=True)
class ScheduleDefinition:
    """Crontab에 필요한 활성 작업 설정."""

    job_key: str
    cron_expression: str
    timezone_name: str


def schedule_token(schedule: ScheduleDefinition) -> str:
    """이전 crontab 항목을 식별할 안정적인 일정 지문을 만든다."""
    definition = "\0".join(
        (schedule.job_key, schedule.cron_expression, schedule.timezone_name)
    )
    return hashlib.sha256(definition.encode("utf-8")).hexdigest()[:16]


def load_enabled_schedules() -> list[ScheduleDefinition]:
    """DB를 유일한 설정 원본으로 사용해 활성 작업을 읽는다."""
    with SessionLocal() as session:
        scheduled_jobs = session.scalars(
            select(ScheduledJob)
            .where(ScheduledJob.is_enabled.is_(True))
            .order_by(ScheduledJob.job_key)
        ).all()
        return [
            ScheduleDefinition(
                scheduled_job.job_key,
                scheduled_job.cron_expression,
                scheduled_job.timezone_name,
            )
            for scheduled_job in scheduled_jobs
        ]


def render_crontab(
    schedules: list[ScheduleDefinition],
    *,
    python_executable: str,
    registered_job_keys: set[str],
) -> str:
    """검증된 schedule만 고정 명령을 사용하는 root crontab으로 변환한다."""
    crontab_lines = ["SHELL=/bin/sh", 'MAILTO=""', "PYTHONPATH=/app", ""]
    for schedule in schedules:
        if schedule.job_key not in registered_job_keys or not JOB_KEY_PATTERN.fullmatch(
            schedule.job_key
        ):
            raise ValueError(f"등록되지 않은 scheduler job: {schedule.job_key}")
        if schedule.timezone_name != SCHEDULER_TIMEZONE:
            raise ValueError(f"scheduler timezone 불일치: {schedule.job_key}")
        if not CRON_EXPRESSION_PATTERN.fullmatch(schedule.cron_expression):
            raise ValueError(f"잘못된 cron 표현식: {schedule.job_key}")
        command = (
            f"{shlex.quote(python_executable)} -m app.scheduler_trigger"
            f" {schedule.job_key} {schedule_token(schedule)}"
            " >> /proc/1/fd/1 2>&1"
        )
        crontab_lines.append(f"{schedule.cron_expression} {command}")
    return "\n".join(crontab_lines) + "\n"


def install_crontab(contents: str) -> None:
    """Cron 자체의 문법 검증을 거쳐 전체 crontab을 원자적으로 교체한다."""
    subprocess.run(
        ["crontab", "-"],
        input=contents,
        text=True,
        check=True,
        capture_output=True,
    )


def synchronize_crontab(current_contents: str | None) -> str:
    """DB 설정이 변경됐을 때만 cron 항목을 다시 설치한다."""
    schedules = load_enabled_schedules()
    contents = render_crontab(
        schedules,
        python_executable=sys.executable,
        registered_job_keys=set(JOB_HANDLERS),
    )
    if contents != current_contents:
        install_crontab(contents)
        logger.info("scheduler_crontab_installed job_count=%s", len(schedules))
    return contents


def mark_interrupted_runs() -> None:
    """단일 scheduler가 재기동하며 남은 RUNNING 이력을 중단으로 마감한다."""
    with SessionLocal.begin() as session:
        update_result = session.execute(
            update(ScheduledJobRun)
            .where(
                ScheduledJobRun.status == "RUNNING",
                ScheduledJobRun.trigger_source == "CRON",
            )
            .values(status="FAILED", finished_at=utc_now(), result_code="interrupted")
        )
    if update_result.rowcount:
        logger.warning("scheduler_interrupted_runs count=%s", update_result.rowcount)


def _record_run_start(scheduled_job_id: int, trigger_source: str) -> int:
    """작업 실행 이력을 트리거 시각 계산과 별개로 기록한다."""
    with SessionLocal.begin() as session:
        job_run = ScheduledJobRun(
            scheduled_job_id=scheduled_job_id,
            trigger_source=trigger_source,
            status="RUNNING",
            started_at=utc_now(),
        )
        session.add(job_run)
        session.flush()
        return job_run.id


def _record_run_completion(job_run_id: int, *, success: bool) -> None:
    """실행 결과와 완료 시각을 저장한다."""
    with SessionLocal.begin() as session:
        job_run = session.get(ScheduledJobRun, job_run_id)
        if job_run is None:
            raise RuntimeError("scheduler 실행 이력을 찾을 수 없습니다.")
        job_run.status = "SUCCEEDED" if success else "FAILED"
        job_run.finished_at = utc_now()
        job_run.result_code = None if success else "job_failed"


def run_job(
    job_key: str, *, trigger_source: str = "MANUAL", expected_schedule_token: str | None = None
) -> int:
    """현재 활성 설정을 재확인하고 겹침을 차단한 뒤 작업을 실행한다."""
    if job_key not in JOB_HANDLERS:
        logger.error("scheduler_job_unregistered job_key=%s", job_key)
        return 1
    settings = get_settings()
    lock_directory = os.path.join(settings.storage.data_root, "scheduler", "locks")
    os.makedirs(lock_directory, exist_ok=True)
    lock_path = os.path.join(lock_directory, f"{job_key}.lock")
    import fcntl  # Linux scheduler container에서만 실행한다.

    with open(lock_path, "a", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.warning("scheduler_job_already_running job_key=%s", job_key)
            return 0
        with SessionLocal() as session:
            scheduled_job = session.scalar(
                select(ScheduledJob).where(ScheduledJob.job_key == job_key)
            )
            if scheduled_job is None or not scheduled_job.is_enabled:
                logger.info("scheduler_job_disabled job_key=%s", job_key)
                return 0
            current_schedule = ScheduleDefinition(
                scheduled_job.job_key,
                scheduled_job.cron_expression,
                scheduled_job.timezone_name,
            )
            if expected_schedule_token is not None and schedule_token(current_schedule) != (
                expected_schedule_token
            ):
                logger.info("scheduler_stale_trigger_ignored job_key=%s", job_key)
                return 0
            scheduled_job_id = scheduled_job.id
        job_run_id = _record_run_start(scheduled_job_id, trigger_source)
        logger.info("scheduler_job_started job_key=%s run_id=%s", job_key, job_run_id)
        try:
            JOB_HANDLERS[job_key]()
        except Exception:
            logger.exception("scheduler_job_failed job_key=%s run_id=%s", job_key, job_run_id)
            _record_run_completion(job_run_id, success=False)
            return 1
        _record_run_completion(job_run_id, success=True)
        logger.info("scheduler_job_completed job_key=%s run_id=%s", job_key, job_run_id)
        return 0


def _receive_trigger(listener: socket.socket) -> tuple[str, str] | None:
    """Cron의 job key만 허용하고 응답을 전송한다."""
    try:
        connection, _ = listener.accept()
    except TimeoutError:
        return None
    with connection:
        connection.settimeout(5)
        try:
            trigger_bytes = bytearray()
            while not trigger_bytes.endswith(b"\n") and len(trigger_bytes) < 128:
                received_bytes = connection.recv(128 - len(trigger_bytes))
                if not received_bytes:
                    break
                trigger_bytes.extend(received_bytes)
            if trigger_bytes.endswith(b"\n"):
                trigger_message = trigger_bytes[:-1].decode("ascii")
            else:
                trigger_message = ""
        except (TimeoutError, UnicodeDecodeError):
            trigger_message = ""
        message_parts = trigger_message.split(" ")
        accepted = (
            len(message_parts) == 2
            and JOB_KEY_PATTERN.fullmatch(message_parts[0]) is not None
            and SCHEDULE_TOKEN_PATTERN.fullmatch(message_parts[1]) is not None
        )
        try:
            connection.sendall(b"accepted" if accepted else b"rejected")
        except (BrokenPipeError, ConnectionResetError):
            return None
        return (message_parts[0], message_parts[1]) if accepted else None


def serve() -> int:
    """기동 시 DB schedule을 복원하고 변경을 cron에 동기화한다."""
    settings = get_settings()
    if settings.app.timezone != SCHEDULER_TIMEZONE:
        raise ValueError("scheduler는 현재 Asia/Seoul timezone만 지원합니다.")
    ensure_data_directories(settings)
    configure_logging(settings.app.log_level, log_file=None)
    os.makedirs(os.path.dirname(SOCKET_PATH), exist_ok=True)
    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)
    stopped = False

    def request_stop(_signal_number: int, _frame: object) -> None:
        """Container 종료 신호를 주기 확인 loop에 전달한다."""
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    mark_interrupted_runs()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(SOCKET_PATH)
        listener.listen()
        listener.settimeout(settings.scheduler.sync_interval_seconds)
        current_contents = synchronize_crontab(None)
        cron_process = subprocess.Popen(["cron", "-f"])
        running_jobs: dict[str, subprocess.Popen[bytes]] = {}
        try:
            logger.info("scheduler_started")
            while not stopped:
                if cron_process.poll() is not None:
                    raise RuntimeError("cron daemon이 종료됐습니다.")
                current_contents = synchronize_crontab(current_contents)
                for job_key, process in list(running_jobs.items()):
                    exit_code = process.poll()
                    if exit_code is not None:
                        if exit_code != 0:
                            logger.error(
                                "scheduler_job_process_failed job_key=%s exit_code=%s",
                                job_key,
                                exit_code,
                            )
                        del running_jobs[job_key]
                trigger = _receive_trigger(listener)
                if trigger is None:
                    continue
                job_key, expected_schedule_token = trigger
                with SessionLocal() as session:
                    scheduled_job = session.scalar(
                        select(ScheduledJob).where(ScheduledJob.job_key == job_key)
                    )
                    enabled = scheduled_job is not None and scheduled_job.is_enabled
                    current_schedule = (
                        ScheduleDefinition(
                            scheduled_job.job_key,
                            scheduled_job.cron_expression,
                            scheduled_job.timezone_name,
                        )
                        if scheduled_job is not None
                        else None
                    )
                if (
                    not enabled
                    or job_key not in JOB_HANDLERS
                    or current_schedule is None
                    or schedule_token(current_schedule) != expected_schedule_token
                ):
                    logger.warning("scheduler_trigger_ignored job_key=%s", job_key)
                    continue
                previous_process = running_jobs.get(job_key)
                if previous_process is not None and previous_process.poll() is None:
                    logger.warning("scheduler_trigger_overlapped job_key=%s", job_key)
                    continue
                running_jobs[job_key] = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "app.scheduler",
                        "run-job",
                        job_key,
                        "--source",
                        "CRON",
                        "--schedule-token",
                        expected_schedule_token,
                    ]
                )
        finally:
            cron_process.terminate()
            cron_process.wait(timeout=10)
            os.unlink(SOCKET_PATH)
            logger.info("scheduler_stopped")
    return 0


def main() -> int:
    """Scheduler service와 cron job 진입점을 선택한다."""
    parser = argparse.ArgumentParser(description="Cron scheduler")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("serve")
    run_command = subcommands.add_parser("run-job")
    run_command.add_argument("job_key")
    run_command.add_argument("--source", choices=("CRON", "MANUAL"), default="MANUAL")
    run_command.add_argument("--schedule-token")
    arguments = parser.parse_args()
    if arguments.command == "serve":
        return serve()
    if arguments.source == "CRON" and arguments.schedule_token is None:
        parser.error("CRON 실행에는 --schedule-token이 필요합니다.")
    settings = get_settings()
    configure_logging(settings.app.log_level, log_file=None)
    return run_job(
        arguments.job_key,
        trigger_source=arguments.source,
        expected_schedule_token=arguments.schedule_token,
    )


if __name__ == "__main__":
    raise SystemExit(main())
