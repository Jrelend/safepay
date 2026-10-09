"""The owner-only admin grant/revoke CLI against real PostgreSQL."""

import subprocess
import sys
import uuid

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tests.integration.conftest import make_user


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    # A fresh process, exactly as an operator runs it (MIGRATION_DATABASE_URL is
    # the migrator URL that the integration fixtures export).
    return subprocess.run(  # noqa: S603 - fixed argv, test-controlled values
        [sys.executable, "-m", "app.cli", *args], capture_output=True, text=True, check=False
    )


def _user(engine: Engine, *, verified: bool = True) -> tuple[uuid.UUID, str]:
    with Session(engine) as s:
        user = make_user(s, verified=verified)
        out = (user.id, user.email)
        s.commit()
    return out


def _is_admin(engine: Engine, user_id: uuid.UUID) -> bool:
    with engine.connect() as conn:
        return bool(
            conn.execute(
                text("SELECT count(*) FROM admins WHERE user_id = :u"), {"u": user_id}
            ).scalar_one()
        )


def test_grant_and_revoke_are_audited(engine: Engine) -> None:
    user_id, email = _user(engine)
    granted = _cli("grant-admin", email, "--note", "beta operator")
    assert granted.returncode == 0, granted.stderr
    assert _is_admin(engine, user_id)
    revoked = _cli("revoke-admin", email)
    assert revoked.returncode == 0, revoked.stderr
    assert not _is_admin(engine, user_id)
    with engine.connect() as conn:
        actions = conn.execute(
            text("SELECT action FROM audit_events WHERE entity_id = :u ORDER BY occurred_at"),
            {"u": user_id},
        ).scalars()
        assert list(actions)[-2:] == ["admin.granted", "admin.revoked"]


def test_unverified_or_unknown_users_cannot_be_granted(engine: Engine) -> None:
    user_id, email = _user(engine, verified=False)
    assert _cli("grant-admin", email).returncode != 0
    assert not _is_admin(engine, user_id)
    assert _cli("grant-admin", "nobody-here@example.com").returncode != 0
