"""Operations CLI. Administrator rights are granted ONLY here, using the schema
owner credential (MIGRATION_DATABASE_URL). The admin API cannot create admins.

    python -m app.cli grant-admin someone@example.com --note "ops on-call"
        (prompts for a separate ADMIN password; prints a TOTP secret once)
    python -m app.cli reset-admin-credentials someone@example.com
    python -m app.cli revoke-admin someone@example.com
    python -m app.cli set-auto-release off --note "beta policy"   # default: off
    python -m app.cli outbox tester@example.com   # simulated emails (no real email yet)
"""

import argparse
import getpass
import sys

from sqlalchemy import Connection, Engine, create_engine, text

from app.core import totp
from app.core.config import get_settings
from app.core.security import WeakPasswordError, check_password_policy, hash_password
from app.services.accounts import normalize_email


def _engine() -> Engine:
    url = get_settings().migration_database_url
    if url is None:
        sys.exit("MIGRATION_DATABASE_URL (schema owner) is required for admin grants")
    return create_engine(str(url))


def _read_admin_password(email: str, from_stdin: bool) -> str:
    """The admin password is separate from the user's normal password."""
    if from_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass("New ADMIN password (not the user's login password): ")
        if getpass.getpass("Repeat: ") != password:
            sys.exit("passwords do not match")
    try:
        check_password_policy(password, email=email)
    except WeakPasswordError as exc:
        sys.exit(f"admin password rejected: {exc}")
    return password


def _issue_credentials(conn: Connection, user_id: object, email: str, password: str) -> str:
    secret = totp.new_secret()
    conn.execute(
        text(
            "UPDATE admins SET password_hash = :h, totp_secret = :s, totp_last_step = 0 "
            "WHERE user_id = :u"
        ),
        {"h": hash_password(password), "s": secret, "u": user_id},
    )
    conn.execute(
        text(
            "UPDATE admin_sessions SET revoked_at = now() "
            "WHERE admin_user_id = :u AND revoked_at IS NULL"
        ),
        {"u": user_id},
    )
    return secret


def _print_totp(secret: str, email: str) -> None:
    # Shown ONCE. Add it to an authenticator app (scan the URI as a QR code or type
    # the secret), then store nothing else: it cannot be read back later.
    print(f"TOTP secret: {secret}")
    print(f"otpauth URI: {totp.provisioning_uri(secret, email)}")


def grant_admin(email: str, note: str, *, password_stdin: bool = False) -> None:
    address = normalize_email(email)
    password = _read_admin_password(address, password_stdin)
    with _engine().begin() as conn:
        user_id = conn.execute(
            text("SELECT id FROM users WHERE email = :e AND email_verified_at IS NOT NULL"),
            {"e": address},
        ).scalar()
        if user_id is None:
            sys.exit("no verified user with that email")
        conn.execute(
            text("INSERT INTO admins (user_id, note) VALUES (:u, :n) ON CONFLICT DO NOTHING"),
            {"u": user_id, "n": note[:200]},
        )
        secret = _issue_credentials(conn, user_id, address, password)
        conn.execute(
            text(
                "INSERT INTO audit_events (actor_type, action, entity_type, entity_id, data) "
                "VALUES ('SYSTEM', 'admin.granted', 'user', :u, "
                "jsonb_build_object('note', CAST(:n AS text)))"
            ),
            {"u": user_id, "n": note[:200]},
        )
    print(f"granted admin to {address}")
    _print_totp(secret, address)


def reset_admin_credentials(email: str, *, password_stdin: bool = False) -> None:
    """New admin password + new TOTP secret; revokes every admin session."""
    address = normalize_email(email)
    password = _read_admin_password(address, password_stdin)
    with _engine().begin() as conn:
        user_id = conn.execute(
            text(
                "SELECT a.user_id FROM admins a JOIN users u ON u.id = a.user_id WHERE u.email = :e"
            ),
            {"e": address},
        ).scalar()
        if user_id is None:
            sys.exit("no administrator with that email")
        secret = _issue_credentials(conn, user_id, address, password)
        conn.execute(
            text(
                "INSERT INTO audit_events (actor_type, action, entity_type, entity_id) "
                "VALUES ('SYSTEM', 'admin.credentials_reset', 'user', :u)"
            ),
            {"u": user_id},
        )
    print(f"reset admin credentials for {address}")
    _print_totp(secret, address)


def revoke_admin(email: str) -> None:
    address = normalize_email(email)
    with _engine().begin() as conn:
        user_id = conn.execute(
            text("SELECT id FROM users WHERE email = :e"), {"e": address}
        ).scalar()
        if user_id is None:
            sys.exit("no user with that email")
        conn.execute(text("DELETE FROM admins WHERE user_id = :u"), {"u": user_id})
        conn.execute(
            text(
                "INSERT INTO audit_events (actor_type, action, entity_type, entity_id) "
                "VALUES ('SYSTEM', 'admin.revoked', 'user', :u)"
            ),
            {"u": user_id},
        )
    print(f"revoked admin from {address}")


def set_auto_release(enabled: bool, note: str) -> None:
    """Owner-only: flip the platform policy. Off by default in Beta v0.1."""
    with _engine().begin() as conn:
        old = conn.execute(
            text("SELECT auto_release_enabled FROM platform_policy WHERE id FOR UPDATE")
        ).scalar_one()
        conn.execute(
            text("UPDATE platform_policy SET auto_release_enabled = :e, note = :n WHERE id"),
            {"e": enabled, "n": note[:200]},
        )
        conn.execute(
            text(
                "INSERT INTO audit_events (actor_type, action, entity_type, entity_id, data) "
                "VALUES ('SYSTEM', 'policy.auto_release_changed', 'platform_policy', "
                "'00000000-0000-0000-0000-000000000000', "
                "jsonb_build_object('from', CAST(:o AS boolean), 'to', CAST(:e AS boolean), "
                "'note', CAST(:n AS text)))"
            ),
            {"o": old, "e": enabled, "n": note[:200]},
        )
    print(f"automatic release {'ENABLED' if enabled else 'disabled'}")


def show_outbox(email: str, limit: int) -> None:
    """Owner-only: print recent simulated emails (no real email in Beta v0.1).

    For a private staging run: lets the operator relay a tester's verification or
    reset link over a trusted channel. Never expose this over HTTP.
    """
    address = normalize_email(email)
    with _engine().connect() as conn:
        rows = conn.execute(
            text(
                "SELECT created_at, template, data FROM email_outbox WHERE to_email = :e "
                "ORDER BY created_at DESC LIMIT :n"
            ),
            {"e": address, "n": limit},
        ).all()
    if not rows:
        print("no simulated emails for that address")
    for created_at, template, data in rows:
        print(f"{created_at:%Y-%m-%d %H:%M} {template}: {data.get('link', '')}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    g = sub.add_parser("grant-admin")
    g.add_argument("email")
    g.add_argument("--note", default="")
    g.add_argument("--password-stdin", action="store_true")
    c = sub.add_parser("reset-admin-credentials")
    c.add_argument("email")
    c.add_argument("--password-stdin", action="store_true")
    r = sub.add_parser("revoke-admin")
    r.add_argument("email")
    a = sub.add_parser("set-auto-release")
    a.add_argument("state", choices=["on", "off"])
    a.add_argument("--note", default="")
    o = sub.add_parser("outbox")
    o.add_argument("email")
    o.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    if args.command == "grant-admin":
        grant_admin(args.email, args.note, password_stdin=args.password_stdin)
    elif args.command == "reset-admin-credentials":
        reset_admin_credentials(args.email, password_stdin=args.password_stdin)
    elif args.command == "revoke-admin":
        revoke_admin(args.email)
    elif args.command == "set-auto-release":
        set_auto_release(args.state == "on", args.note)
    else:
        show_outbox(args.email, args.limit)


if __name__ == "__main__":
    main()
