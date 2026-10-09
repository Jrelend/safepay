"""The one way to run a financial operation: a single, explicit DB transaction.

Usage::

    with atomic(session):
        deal = lock_for_update(session, Deal, deal_id)
        ...  # every write here commits together or not at all

``atomic`` commits when the block finishes and rolls back on *any* exception,
so a failure can never leave a partial financial operation behind. PostgreSQL
re-checks the ledger invariants (balanced, sealed, append-only) at COMMIT.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.base import Base


class NestedTransactionError(RuntimeError):
    """Raised when ``atomic`` is entered while a transaction is already open."""


@contextmanager
def atomic(session: Session) -> Iterator[Session]:
    if session.in_transaction():
        # Refuse to silently join an outer transaction: the caller must own the
        # boundary so that "committed" really means committed.
        raise NestedTransactionError("atomic() must not be nested; finish the outer transaction")
    with session.begin():
        yield session


def lock_for_update[M: Base](session: Session, model: type[M], row_id: uuid.UUID) -> M | None:
    """``SELECT … FOR UPDATE`` one row; other writers wait until we commit or roll back."""
    stmt = select(model).where(model.id == row_id).with_for_update()  # type: ignore[attr-defined]
    return session.scalars(stmt).one_or_none()
