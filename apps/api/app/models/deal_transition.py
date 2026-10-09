"""The legal deal transitions, stored in the database.

The ``safepay_transition_deal`` function and the ``deals`` update trigger read
this table, so an illegal transition is rejected by PostgreSQL even if the
application code is wrong. The rows are seeded by migration 0002 and must equal
``app.domain.deal_states.TRANSITIONS`` (an integration test checks this).
The application role can only read it.
"""

from sqlalchemy import CheckConstraint, String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.deal_states import DealAction, DealStatus, LedgerEffect
from app.models.base import Base, str_enum


class DealTransitionRule(Base):
    __tablename__ = "deal_transitions"
    __table_args__ = (
        CheckConstraint("cardinality(actors) > 0", name="has_actors"),
        CheckConstraint(
            "actors <@ ARRAY['BUYER', 'SELLER', 'SYSTEM', 'ADMIN']::varchar[]",
            name="known_actors",
        ),
    )

    from_status: Mapped[DealStatus] = mapped_column(
        str_enum(DealStatus, "transition_from_status"), primary_key=True
    )
    action: Mapped[DealAction] = mapped_column(
        str_enum(DealAction, "transition_action"), primary_key=True
    )
    to_status: Mapped[DealStatus] = mapped_column(str_enum(DealStatus, "transition_to_status"))
    actors: Mapped[list[str]] = mapped_column(ARRAY(String(16)))
    ledger_effect: Mapped[LedgerEffect] = mapped_column(
        str_enum(LedgerEffect, "transition_ledger_effect")
    )
