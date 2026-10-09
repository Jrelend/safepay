"""Audit timestamps come from the database; client-supplied values are ignored."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db.transactions import atomic
from app.domain.deal_states import Actor, DealAction
from app.models import AuditEvent, DealParticipant
from tests.integration.conftest import make_deal, make_user
from tests.integration.scenario import act, new_deal

FORGED = datetime(2000, 1, 1, tzinfo=UTC)


def test_client_supplied_audit_timestamp_is_overwritten(app_engine: Engine) -> None:
    with Session(app_engine) as s, atomic(s):
        user = make_user(s)
        deal = make_deal(s, user)
        event = AuditEvent(
            occurred_at=FORGED,
            actor_type=Actor.BUYER,
            actor_user_id=user.id,
            action="deal.viewed",
            entity_type="deal",
            entity_id=deal.id,
            deal_id=deal.id,
        )
        s.add(event)
        s.flush()
        event_id = event.id
    with Session(app_engine) as s:
        stored = s.get_one(AuditEvent, event_id).occurred_at
    assert abs(stored - datetime.now(UTC)) < timedelta(minutes=5)


def test_raw_sql_audit_timestamp_is_overwritten(app_engine: Engine) -> None:
    sc = new_deal(app_engine)
    with app_engine.begin() as conn:
        stored = conn.execute(
            text(
                "INSERT INTO audit_events "
                "(occurred_at, actor_type, action, entity_type, entity_id) "
                "VALUES ('1999-12-31', 'SYSTEM', 'test.forged_time', 'deal', :id) "
                "RETURNING occurred_at"
            ),
            {"id": sc.deal_id},
        ).scalar_one()
    assert stored.year == datetime.now(UTC).year


def test_participant_acceptance_is_recorded_by_the_database(app_engine: Engine) -> None:
    sc = new_deal(app_engine)
    # The app role can no longer mark acceptance directly...
    with Session(app_engine) as s, pytest.raises(DBAPIError, match="permission denied"):
        s.execute(
            update(DealParticipant)
            .where(DealParticipant.deal_id == sc.deal_id)
            .values(accepted_at=FORGED)
        )
    # ...it is set (to server time) only by SUBMIT / ACCEPT.
    act(app_engine, sc, DealAction.SUBMIT, Actor.SELLER)
    with Session(app_engine) as s:
        accepted = s.scalars(
            select(DealParticipant.accepted_at).where(
                DealParticipant.deal_id == sc.deal_id, DealParticipant.user_id == sc.seller_id
            )
        ).one()
    assert accepted is not None
    assert abs(accepted - datetime.now(UTC)) < timedelta(minutes=5)
