"""One-time operator commands. Passwords are never accepted as command arguments."""

import argparse
import getpass
import logging

from alembic import command
from alembic.config import Config

from app.core.config import ensure_data_directories, get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.domain.auth import AuthError
from app.repositories.auth import count_users
from app.services.bootstrap import bootstrap_admin, bootstrap_from_environment

logger = logging.getLogger(__name__)


def main() -> int:
    """명령행 진입점을 실행한다."""
    parser = argparse.ArgumentParser(description="Taskflow management commands")
    subcommands = parser.add_subparsers(dest="command", required=True)
    bootstrap = subcommands.add_parser("bootstrap-admin")
    bootstrap.add_argument("--login-id")
    bootstrap.add_argument("--display-name", default="시스템 관리자")
    bootstrap.add_argument("--from-env", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    ensure_data_directories(settings)
    configure_logging(
        settings.app.log_level,
        log_file=settings.log_file_path if settings.logging.file_enabled else None,
        max_bytes=settings.logging.max_size_mb * 1024 * 1024,
        backup_count=settings.logging.backup_count,
    )
    try:
        config = Config("alembic.ini")
        config.attributes["database_url"] = settings.database_url
        command.upgrade(config, "head")
        if args.from_env:
            bootstrap_from_environment(SessionLocal, settings)
            return 0
        with SessionLocal() as session:
            if count_users(session):
                print("사용자가 이미 존재하여 초기 관리자를 추가하지 않았습니다.")
                return 0
        login_id = args.login_id or input("로그인 ID: ")
        password = getpass.getpass("초기 비밀번호 (12~128자): ")
        confirmation = getpass.getpass("초기 비밀번호 확인: ")
        if password != confirmation:
            print("비밀번호 확인이 일치하지 않습니다.")
            return 1
        created = bootstrap_admin(SessionLocal, settings, login_id, password, args.display_name)
        print(
            "초기 관리자를 생성했습니다. 첫 로그인에서 비밀번호를 변경하세요."
            if created
            else "사용자가 이미 존재하여 초기 관리자를 추가하지 않았습니다."
        )
        return 0
    except (AuthError, ValueError) as exc:
        logger.warning("auth_bootstrap_rejected")
        print(str(exc))
        return 1
    except Exception:
        logger.exception("auth_bootstrap_failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
