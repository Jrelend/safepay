import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.domain.deal_states import Actor
from app.models import AuditEvent, Deal, DealParticipant, ParticipantRole
from tests.integration.conftest import make_deal, make_user


@pytest.mark.parametrize("amount", [0, -1])
def test_deal_amount_must_be_positive(session: Session, amount: int) -> None:
    user = make_user(session)
    with pytest.raises(IntegrityError, match="amount_positive"):
        make_deal(session, user, amount_mnt=amount)


def test_deal_currency_is_mnt_only(session: Session) -> None:
    user = make_user(session)
    deal = Deal(
        reference="SP-USD00001", title="x", amount_mnt=1, currency="USD", created_by_id=user.id
    )
    session.add(deal)
    with pytest.raises(IntegrityError, match="currency_mnt"):
        session.flush()


def test_deal_currency_cannot_be_changed(session: Session) -> None:
    user = make_user(session)
    deal = make_deal(session, user)
    session.commit()
    with pytest.raises(DBAPIError, match="identity columns are immutable"):
        session.execute(
            text("UPDATE deals SET currency = 'USD', version = version + 1 WHERE id = :id"),
            {"id": deal.id},
        )


def test_deal_status_must_be_known(session: Session) -> None:
    user = make_user(session)
    deal = make_deal(session, user)
    session.commit()
    # Even the schema owner cannot jump to an unknown/illegal state.
    with pytest.raises(DBAPIError, match="illegal deal transition DRAFT -> PAID"):
        session.execute(
            text("UPDATE deals SET status = 'PAID', version = version + 1 WHERE id = :id"),
            {"id": deal.id},
        )


def test_one_buyer_and_one_seller_per_deal(session: Session) -> None:
    buyer, seller, other = make_user(session), make_user(session), make_user(session)
    deal = make_deal(session, buyer)
    session.add_all(
        [
            DealParticipant(deal_id=deal.id, user_id=buyer.id, role=ParticipantRole.BUYER),
            DealParticipant(deal_id=deal.id, user_id=seller.id, role=ParticipantRole.SELLER),
        ]
    )
    session.flush()
    session.add(DealParticipant(deal_id=deal.id, user_id=other.id, role=ParticipantRole.BUYER))
    with pytest.raises(IntegrityError, match="uq_deal_participants_deal_id_role"):
        session.flush()


def test_user_cannot_be_both_buyer_and_seller(session: Session) -> None:
    user = make_user(session)
    deal = make_deal(session, user)
    session.add(DealParticipant(deal_id=deal.id, user_id=user.id, role=ParticipantRole.BUYER))
    session.flush()
    session.add(DealParticipant(deal_id=deal.id, user_id=user.id, role=ParticipantRole.SELLER))
    with pytest.raises(IntegrityError, match="uq_deal_participants_deal_id_user_id"):
        session.flush()


def test_optimistic_locking_bumps_version(session: Session) -> None:
    user = make_user(session)
    deal = make_deal(session, user)
    session.commit()
    assert deal.version == 1
    deal.title = "Шинэчилсэн"
    session.commit()
    assert deal.version == 2


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_events SET action = 'tampered'",
        "DELETE FROM audit_events",
        "TRUNCATE audit_events",
    ],
)
def test_audit_events_are_append_only(session: Session, engine: Engine, statement: str) -> None:
    user = make_user(session)
    deal = make_deal(session, user)
    session.add(
        AuditEvent(
            actor_type=Actor.BUYER,
            actor_user_id=user.id,
            action="deal.created",
            entity_type="deal",
            entity_id=deal.id,
            deal_id=deal.id,
            data={"amount_mnt": deal.amount_mnt},
        )
    )
    session.commit()
    with engine.connect() as conn, pytest.raises(DBAPIError, match="append-only"):
        conn.execute(text(statement))
