from collections.abc import Callable, Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session


@contextmanager
def request_transaction(session: Session) -> Iterator[None]:
    """요청 단위 최상위 transaction을 한 번만 commit 또는 rollback한다."""
    try:
        yield
        session.commit()
    except Exception:
        session.rollback()
        raise


@contextmanager
def transaction_scope(session_factory: Callable[[], Session]) -> Iterator[Session]:
    """Own a session and commit or roll back exactly one service transaction."""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
