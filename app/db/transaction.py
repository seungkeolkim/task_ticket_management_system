from collections.abc import Callable, Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session


@contextmanager
def request_transaction(session: Session) -> Iterator[None]:
    """A top-level application use case owns the injected request session transaction.

    Includes any preceding authentication reads. Do not nest this context or call it
    from repositories; one write use case commits once per request.
    """
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
