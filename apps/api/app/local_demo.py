# ruff: noqa: RUF001 - Mongolian (Cyrillic) display names
"""LOCAL DEMO ONLY: fixed demo accounts and a pre-funded simulated buyer wallet,
for presenting the escrow workflow on a single machine.

Everything here is gated twice, the same way ``BETA_DEMO_MODE`` is:

1. ``LOCAL_DEMO=true`` for the API (refused at startup unless ``APP_ENV`` is
   local/test). It mounts ``/demo/*`` (account list for one-click switching and the
   demo admin's current TOTP code) and lifts the login rate limits for the seeded
   accounts only.
2. ``platform_policy.demo_wallets_enabled`` in the database, set only by the
   schema owner through ``python -m app.cli demo-seed`` (which also refuses outside
   local/test). While it is on, funding a **demo** deal pays from the buyer's
   simulated wallet instead of the platform's simulated-cash account (migration
   0007). Non-demo deals are funded exactly as before.

The credentials below are public by design: they exist only in a local demo
database, which ``scripts/demo-reset.ps1`` throws away and recreates.
"""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Connection, text

from app.core.security import hash_password

# 10,000,000 MNT of simulated money for the demo buyer.
BUYER_STARTING_BALANCE_MNT = 10_000_000
DEMO_PASSWORD = "SafePay-Demo-2026"  # noqa: S105 - public local-demo credential
DEMO_ADMIN_PASSWORD = "SafePay-Admin-Demo-2026"  # noqa: S105 - public local-demo credential
# Base32 TOTP secret of the demo admin. The web app never sees it: /demo/admin-code
# returns only the current six-digit code.
DEMO_ADMIN_TOTP_SECRET = "SAFEPAYLOCALDEMOADMINTOTP234567A"  # noqa: S105 - local demo only
TOPUP_KIND = "DEMO_TOPUP"
_POLICY_ID = "00000000-0000-0000-0000-000000000000"


@dataclass(frozen=True, slots=True)
class Persona:
    key: Literal["buyer", "seller", "admin"]
    email: str
    display_name: str
    # Deal parties are demo accounts (their deals are flagged DEMO). The admin is a
    # regular verified account, like every admin (grant-admin refuses others).
    is_demo: bool


BUYER = Persona("buyer", "demo.buyer@example.com", "Сараа (Худалдан авагч)", True)
SELLER = Persona("seller", "demo.seller@example.com", "Болд (Худалдагч)", True)
ADMIN = Persona("admin", "demo.admin@example.com", "SafePay Админ", False)
PERSONAS = (BUYER, SELLER, ADMIN)
PERSONA_EMAILS = frozenset(p.email for p in PERSONAS)
PARTY_EMAILS = frozenset(p.email for p in PERSONAS if p.is_demo)


def _audit(conn: Connection, action: str, entity_type: str, entity_id: object) -> None:
    conn.execute(
        text(
            "INSERT INTO audit_events (actor_type, action, entity_type, entity_id, data) "
            "VALUES ('SYSTEM', :a, :t, :i, jsonb_build_object('note', 'local demo seed'))"
        ),
        {"a": action, "t": entity_type, "i": entity_id},
    )


def _ensure_user(conn: Connection, p: Persona) -> object:
    user_id = conn.execute(text("SELECT id FROM users WHERE email = :e"), {"e": p.email}).scalar()
    if user_id is not None:
        return user_id
    user_id = conn.execute(
        text(
            "INSERT INTO users (email, password_hash, email_verified_at, display_name, status, "
            "is_demo) VALUES (:e, :h, now(), :n, 'ACTIVE', :d) RETURNING id"
        ),
        {"e": p.email, "h": hash_password(DEMO_PASSWORD), "n": p.display_name, "d": p.is_demo},
    ).scalar_one()
    _audit(conn, "demo.user_seeded", "user", user_id)
    return user_id


def _ensure_admin(conn: Connection, user_id: object) -> None:
    exists = conn.execute(text("SELECT 1 FROM admins WHERE user_id = :u"), {"u": user_id}).scalar()
    if exists:
        return
    conn.execute(
        text(
            "INSERT INTO admins (user_id, note, password_hash, totp_secret) "
            "VALUES (:u, 'local demo admin', :h, :s)"
        ),
        {"u": user_id, "h": hash_password(DEMO_ADMIN_PASSWORD), "s": DEMO_ADMIN_TOTP_SECRET},
    )
    _audit(conn, "admin.granted", "user", user_id)


def _ensure_topup(conn: Connection, user_id: object) -> None:
    key = f"demo-topup:{user_id}"
    if conn.execute(
        text("SELECT 1 FROM ledger_transactions WHERE idempotency_key = :k"), {"k": key}
    ).scalar():
        return
    conn.execute(
        text(
            "INSERT INTO ledger_accounts (code, account_type, purpose, owner_user_id) "
            "VALUES ('WALLET:' || CAST(:u AS text), 'LIABILITY', 'USER_WALLET', :u) "
            "ON CONFLICT DO NOTHING"
        ),
        {"u": user_id},
    )
    tx = conn.execute(
        text(
            "INSERT INTO ledger_transactions (idempotency_key, kind, description) "
            "VALUES (:k, :kind, 'Local demo: starting simulated balance') RETURNING id"
        ),
        {"k": key, "kind": TOPUP_KIND},
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO ledger_entries (transaction_id, account_id, direction, amount_mnt) "
            "SELECT :t, id, 'DEBIT', :a FROM ledger_accounts WHERE purpose = 'SIMULATED_CASH' "
            "UNION ALL "
            "SELECT :t, id, 'CREDIT', :a FROM ledger_accounts "
            " WHERE purpose = 'USER_WALLET' AND owner_user_id = :u"
        ),
        {"t": tx, "a": BUYER_STARTING_BALANCE_MNT, "u": user_id},
    )


def seed(conn: Connection) -> None:
    """Idempotent. Run as the schema owner, in one transaction."""
    ids = {p.key: _ensure_user(conn, p) for p in PERSONAS}
    _ensure_admin(conn, ids["admin"])
    _ensure_topup(conn, ids["buyer"])
    # Nobody verifies an email in a local demo: accounts registered before LOCAL_DEMO
    # was on (or before registration skipped verification) are verified here.
    verified = (
        conn.execute(
            text(
                "UPDATE users SET email_verified_at = now() "
                "WHERE email_verified_at IS NULL RETURNING id"
            )
        )
        .scalars()
        .all()
    )
    for user_id in verified:
        _audit(conn, "demo.user_verified", "user", user_id)
    enabled = conn.execute(
        text("SELECT demo_wallets_enabled FROM platform_policy WHERE id FOR UPDATE")
    ).scalar_one()
    if not enabled:
        conn.execute(
            text(
                "UPDATE platform_policy SET demo_wallets_enabled = true, "
                "note = 'local demo: demo deals pay from the buyer wallet' WHERE id"
            )
        )
        _audit(conn, "policy.demo_wallets_changed", "platform_policy", _POLICY_ID)
