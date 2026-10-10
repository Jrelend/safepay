"""separate admin authentication (admin password + TOTP + admin-only sessions)

Security review finding: the admin API trusted the public ``sessions`` table and
``users.password_hash``, both writable by ``safepay_app``, so a leaked public-API
credential could mint an admin session. Now:

* admins log in to the admin API with an admin-only password and a TOTP code,
  both stored on ``admins`` and readable only by ``safepay_admin``;
* admin sessions live in ``admin_sessions``, writable only by ``safepay_admin``;
* ``safepay_app`` can read only ``admins.user_id`` (to show an "admin" badge) and
  ``safepay_admin`` can no longer read public ``sessions``.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-10 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GUARDS_SQL = r"""
CREATE FUNCTION safepay_guard_admin_session() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        NEW.created_at := now();
        NEW.last_seen_at := now();
        NEW.revoked_at := NULL;
        RETURN NEW;
    END IF;
    IF NEW.id <> OLD.id OR NEW.token_hash <> OLD.token_hash OR NEW.csrf_hash <> OLD.csrf_hash
       OR NEW.admin_user_id <> OLD.admin_user_id OR NEW.expires_at <> OLD.expires_at
       OR NEW.created_at <> OLD.created_at THEN
        RAISE EXCEPTION 'SafePay: admin session identity is immutable';
    END IF;
    IF OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
        RAISE EXCEPTION 'SafePay: a revoked admin session stays revoked';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER admin_sessions_guard BEFORE INSERT OR UPDATE ON admin_sessions
    FOR EACH ROW EXECUTE FUNCTION safepay_guard_admin_session();

CREATE FUNCTION safepay_guard_admin_totp() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    -- One-time codes: the accepted step only moves forward, except when the owner
    -- re-issues credentials (new secret).
    IF NEW.totp_last_step < OLD.totp_last_step
       AND NEW.totp_secret IS NOT DISTINCT FROM OLD.totp_secret THEN
        RAISE EXCEPTION 'SafePay: TOTP step cannot move backwards';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER admins_totp_guard BEFORE UPDATE ON admins
    FOR EACH ROW EXECUTE FUNCTION safepay_guard_admin_totp();

REVOKE EXECUTE ON FUNCTION safepay_guard_admin_session() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION safepay_guard_admin_totp() FROM PUBLIC;
"""

GRANTS_SQL = r"""
REVOKE ALL ON admins FROM safepay_app, safepay_admin;
GRANT SELECT (user_id) ON admins TO safepay_app;
GRANT SELECT (user_id, granted_at, note, password_hash, totp_secret, totp_last_step)
    ON admins TO safepay_admin;
GRANT UPDATE (totp_last_step) ON admins TO safepay_admin;

REVOKE ALL ON admin_sessions FROM PUBLIC;
GRANT SELECT, INSERT ON admin_sessions TO safepay_admin;
GRANT UPDATE (last_seen_at, revoked_at) ON admin_sessions TO safepay_admin;

-- The admin API no longer reads public sessions at all.
REVOKE SELECT ON sessions FROM safepay_admin;
-- Admin login is rate limited like public login.
GRANT SELECT, INSERT ON rate_limits TO safepay_admin;
GRANT UPDATE (count) ON rate_limits TO safepay_admin;
"""


def upgrade() -> None:
    op.add_column("admins", sa.Column("password_hash", sa.String(length=255), nullable=True))
    op.add_column("admins", sa.Column("totp_secret", sa.String(length=64), nullable=True))
    op.add_column(
        "admins",
        sa.Column("totp_last_step", sa.BigInteger(), server_default="0", nullable=False),
    )
    op.create_table(
        "admin_sessions",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_hash", sa.String(length=64), nullable=False),
        sa.Column("admin_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(length=255), server_default="", nullable=False),
        sa.Column("ip_address", sa.String(length=64), server_default="", nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "token_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_admin_sessions_token_hash_sha256")
        ),
        sa.CheckConstraint(
            "csrf_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_admin_sessions_csrf_hash_sha256")
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name=op.f("ck_admin_sessions_expires_after_creation")
        ),
        sa.ForeignKeyConstraint(
            ["admin_user_id"],
            ["admins.user_id"],
            name=op.f("fk_admin_sessions_admin_user_id_admins"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_admin_sessions_token_hash")),
    )
    op.create_index(
        "ix_admin_sessions_admin_user_id", "admin_sessions", ["admin_user_id"], unique=False
    )
    op.execute(GUARDS_SQL)
    op.execute(GRANTS_SQL)


def downgrade() -> None:
    op.execute("DROP TABLE admin_sessions")
    op.execute("DROP TRIGGER admins_totp_guard ON admins")
    op.execute("DROP FUNCTION safepay_guard_admin_totp()")
    op.execute("DROP FUNCTION safepay_guard_admin_session()")
    op.drop_column("admins", "totp_last_step")
    op.drop_column("admins", "totp_secret")
    op.drop_column("admins", "password_hash")
    op.execute(
        """
        REVOKE ALL ON admins FROM safepay_app, safepay_admin;
        GRANT SELECT ON admins TO safepay_app, safepay_admin;
        GRANT SELECT ON sessions TO safepay_admin;
        REVOKE ALL ON rate_limits FROM safepay_admin;
        """
    )
