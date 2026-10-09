"""Operations CLI. Administrator rights are granted ONLY here, using the schema
owner credential (MIGRATION_DATABASE_URL). The admin API cannot create admins.

    python -m app.cli grant-admin someone@example.com --note "ops on-call"
    python -m app.cli revoke-admin someone@example.com
"""

import argparse
import sys

from sqlalchemy import Engine, create_engine, text

from app.core.config import get_settings
from app.services.accounts import normalize_email


def _engine() -> Engine:
    url = get_settings().migration_database_url
    if url is None:
        sys.exit("MIGRATION_DATABASE_URL (schema owner) is required for admin grants")
    return create_engine(str(url))


def grant_admin(email: str, note: str) -> None:
    address = normalize_email(email)
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
        conn.execute(
            text(
                "INSERT INTO audit_events (actor_type, action, entity_type, entity_id, data) "
                "VALUES ('SYSTEM', 'admin.granted', 'user', :u, "
                "jsonb_build_object('note', CAST(:n AS text)))"
            ),
            {"u": user_id, "n": note[:200]},
        )
    print(f"granted admin to {address}")


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


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    g = sub.add_parser("grant-admin")
    g.add_argument("email")
    g.add_argument("--note", default="")
    r = sub.add_parser("revoke-admin")
    r.add_argument("email")
    args = parser.parse_args()
    if args.command == "grant-admin":
        grant_admin(args.email, args.note)
    else:
        revoke_admin(args.email)


if __name__ == "__main__":
    main()
