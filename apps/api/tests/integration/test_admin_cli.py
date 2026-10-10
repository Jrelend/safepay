"""The owner-only admin grant/revoke CLI against real PostgreSQL."""

import subprocess
import sys
import uuid

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tests.integration.conftest import make_user

ADMIN_PW = "Operator-Admin-Pass-2026"


def _cli(*args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
    # A fresh process, exactly as an operator runs it (MIGRATION_DATABASE_URL is
    # the migrator URL that the integration fixtures export).
    return subprocess.run(  # noqa: S603 - fixed argv, test-controlled values
        [sys.executable, "-m", "app.cli", *args],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
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
    granted = _cli(
        "grant-admin", email, "--note", "beta operator", "--password-stdin", stdin=ADMIN_PW + "\n"
    )
    assert granted.returncode == 0, granted.stderr
    assert _is_admin(engine, user_id)
    secret = granted.stdout.split("TOTP secret: ")[1].split()[0]
    with engine.connect() as conn:
        pw_hash, stored = conn.execute(
            text("SELECT password_hash, totp_secret FROM admins WHERE user_id = :u"),
            {"u": user_id},
        ).one()
    assert pw_hash.startswith("$argon2id$") and ADMIN_PW not in pw_hash
    assert stored == secret
    # A weak admin password is refused.
    weak = _cli("reset-admin-credentials", email, "--password-stdin", stdin="short\n")
    assert weak.returncode != 0
    reset = _cli("reset-admin-credentials", email, "--password-stdin", stdin=ADMIN_PW + "\n")
    assert reset.returncode == 0, reset.stderr
    assert reset.stdout.split("TOTP secret: ")[1].split()[0] != secret
    revoked = _cli("revoke-admin", email)
    assert revoked.returncode == 0, revoked.stderr
    assert not _is_admin(engine, user_id)
    with engine.connect() as conn:
        actions = conn.execute(
            text("SELECT action FROM audit_events WHERE entity_id = :u ORDER BY occurred_at"),
            {"u": user_id},
        ).scalars()
        assert list(actions)[-3:] == ["admin.granted", "admin.credentials_reset", "admin.revoked"]


def test_unverified_or_unknown_users_cannot_be_granted(engine: Engine) -> None:
    user_id, email = _user(engine, verified=False)
    assert _cli("grant-admin", email, "--password-stdin", stdin=ADMIN_PW + "\n").returncode != 0
    assert not _is_admin(engine, user_id)
    missing = _cli("grant-admin", "nobody-here@example.com", "--password-stdin", stdin=ADMIN_PW)
    assert missing.returncode != 0


def test_auto_release_policy_switch_is_owner_only_and_audited(engine: Engine) -> None:
    on = _cli("set-auto-release", "on", "--note", "test")
    try:
        assert on.returncode == 0, on.stderr
        with engine.connect() as conn:
            assert conn.execute(text("SELECT auto_release_enabled FROM platform_policy")).scalar()
    finally:
        assert _cli("set-auto-release", "off").returncode == 0
    with engine.connect() as conn:
        assert not conn.execute(text("SELECT auto_release_enabled FROM platform_policy")).scalar()
        changes = conn.execute(
            text("SELECT count(*) FROM audit_events WHERE action = 'policy.auto_release_changed'")
        ).scalar_one()
    assert changes >= 2
