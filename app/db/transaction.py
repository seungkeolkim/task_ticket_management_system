from collections.abc import Callable, Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session


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
