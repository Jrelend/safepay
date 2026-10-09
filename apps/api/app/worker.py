"""Background worker: SYSTEM transitions and housekeeping.

Connects as ``safepay_system`` (SYSTEM_DATABASE_URL), which may execute only
``safepay_system_transition_deal``. The database re-checks eligibility (expiry
age, inspection window), so even this role cannot release funds early.

    python -m app.worker          # loop forever
    python -m app.worker --once   # one pass (cron / tests)
"""

import argparse
import logging
import time
import uuid
from dataclasses import dataclass, field

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.transactions import atomic
from app.domain.deal_states import DealAction
from app.domain.deal_terms import EXPIRY_DAYS
from app.services.deal_transitions import (
    DealTransitionError,
    NotYetEligibleError,
    system_transition,
)

log = logging.getLogger("safepay.worker")

_EXPIRY_CANDIDATES = text(
    "SELECT id FROM deals WHERE status IN ('PENDING_ACCEPTANCE', 'AWAITING_PAYMENT') "
    "AND status_changed_at <= now() - make_interval(days => :days) LIMIT 200"
)
_RELEASE_CANDIDATES = text(
    "SELECT id FROM deals WHERE status = 'DELIVERED' "
    "AND status_changed_at <= now() - make_interval(days => inspection_days) LIMIT 200"
)


@dataclass
class PassResult:
    expired: list[uuid.UUID] = field(default_factory=list)
    released: list[uuid.UUID] = field(default_factory=list)
    skipped: int = 0


def system_engine() -> Engine:
    settings = get_settings()
    url = settings.system_database_url
    if url is None:
        raise RuntimeError("SYSTEM_DATABASE_URL is not set")
    return create_engine(str(url), pool_pre_ping=True)


def run_once(engine: Engine) -> PassResult:
    result = PassResult()
    with engine.connect() as conn:
        expiring = list(conn.execute(_EXPIRY_CANDIDATES, {"days": EXPIRY_DAYS}).scalars())
        releasing = list(conn.execute(_RELEASE_CANDIDATES).scalars())
    for action, ids, bucket in (
        (DealAction.EXPIRE, expiring, result.expired),
        (DealAction.AUTO_RELEASE, releasing, result.released),
    ):
        for deal_id in ids:
            try:
                with Session(engine) as db, atomic(db):
                    system_transition(db, deal_id=deal_id, action=action, request_id="worker")
                bucket.append(deal_id)
            except (NotYetEligibleError, DealTransitionError) as exc:
                # Raced with a user action or not eligible any more: nothing happened.
                log.info("skip %s %s: %s", action, deal_id, exc)
                result.skipped += 1
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM rate_limits WHERE window_start < now() - interval '1 day'"))
        conn.execute(text("DELETE FROM email_outbox WHERE created_at < now() - interval '3 days'"))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="SafePay background worker")
    parser.add_argument("--once", action="store_true", help="run a single pass and exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    engine = system_engine()
    interval = get_settings().worker_interval_seconds
    while True:
        outcome = run_once(engine)
        log.info(
            "pass: expired=%d auto_released=%d skipped=%d",
            len(outcome.expired),
            len(outcome.released),
            outcome.skipped,
        )
        if args.once:
            return
        time.sleep(interval)


if __name__ == "__main__":
    main()
