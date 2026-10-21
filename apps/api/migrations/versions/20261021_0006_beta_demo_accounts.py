"""beta demo accounts: a permanent demo/real partition for users and deals

``BETA_DEMO_MODE`` lets new accounts use deal workflows without email
verification. Every such account, and every deal it creates, is marked
``is_demo`` at insert time, so demo data can always be told apart from (and
never mixed with) accounts and deals that a future real-money release may keep:

* ``users.is_demo`` / ``deals.is_demo``: NOT NULL, default false. ``safepay_app``
  has no UPDATE privilege on either column, so the flag cannot be changed after
  insert by the runtime role (only the schema owner could).
* A deal's flag must equal its creator's, and every participant's flag must
  equal the deal's (triggers). A demo account can therefore never join a real
  deal, nor a real account a demo deal, even if the API check were bypassed.

Defence in depth: the transition core (``safepay__apply_transition``, behind
``safepay_transition_deal``, the only way a buyer or seller moves a deal or
simulated money) still requires a verified email, and now also
accepts an unverified actor only when that actor is a demo account AND
``platform_policy.beta_demo_enabled`` is true. That policy is writable only by
the schema owner (``python -m app.cli set-beta-demo on|off``, audited), so a
stolen runtime credential cannot enable it, and it never exempts a non-demo
account.

All money stays simulated in both partitions.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-21 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GUARDS_SQL = r"""
CREATE FUNCTION safepay_guard_deal_demo() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF NEW.is_demo IS DISTINCT FROM (SELECT u.is_demo FROM users u WHERE u.id = NEW.created_by_id) THEN
        RAISE EXCEPTION 'SafePay: a deal must be demo exactly when its creator is a demo account'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER deals_demo_guard BEFORE INSERT ON deals
    FOR EACH ROW EXECUTE FUNCTION safepay_guard_deal_demo();

CREATE FUNCTION safepay_guard_participant_demo() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF (SELECT u.is_demo FROM users u WHERE u.id = NEW.user_id)
       IS DISTINCT FROM (SELECT d.is_demo FROM deals d WHERE d.id = NEW.deal_id) THEN
        RAISE EXCEPTION 'SafePay: demo and non-demo accounts cannot share a deal'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER deal_participants_demo_guard BEFORE INSERT ON deal_participants
    FOR EACH ROW EXECUTE FUNCTION safepay_guard_participant_demo();

REVOKE EXECUTE ON FUNCTION safepay_guard_deal_demo() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION safepay_guard_participant_demo() FROM PUBLIC;
"""

# The shared core behind the public, admin and system transition functions.
TRANSITION = "safepay__apply_transition(uuid, text, text, uuid, integer, text, text)"
VERIFIED_ONLY = "WHERE id = p_actor_user_id AND status = 'ACTIVE' AND email_verified_at IS NOT NULL"
VERIFIED_OR_DEMO = (
    "WHERE id = p_actor_user_id AND status = 'ACTIVE' AND (email_verified_at IS NOT NULL\n"
    "                  OR (is_demo AND (SELECT beta_demo_enabled FROM platform_policy WHERE id)))"
)


def _patch_transition(old: str, new: str) -> None:
    """Swap one exact clause in the live function body (keeping owner, SECURITY
    DEFINER, search_path and grants: CREATE OR REPLACE preserves them)."""
    op.execute(
        f"""
DO $do$
DECLARE
    old_clause text := $old${old}$old$;
    new_clause text := $new${new}$new$;
    def text := pg_get_functiondef('{TRANSITION}'::regprocedure);
BEGIN
    IF (length(def) - length(replace(def, old_clause, ''))) / length(old_clause) <> 1 THEN
        RAISE EXCEPTION 'SafePay: expected exactly one eligibility clause in %', '{TRANSITION}';
    END IF;
    EXECUTE replace(def, old_clause, new_clause);
END
$do$;
"""
    )


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.add_column(
        "deals", sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.create_index("ix_deals_is_demo", "deals", ["is_demo"])
    op.add_column(
        "platform_policy",
        sa.Column("beta_demo_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(GUARDS_SQL)
    _patch_transition(VERIFIED_ONLY, VERIFIED_OR_DEMO)


def downgrade() -> None:
    _patch_transition(VERIFIED_OR_DEMO, VERIFIED_ONLY)
    op.execute("DROP TRIGGER deal_participants_demo_guard ON deal_participants")
    op.execute("DROP TRIGGER deals_demo_guard ON deals")
    op.execute("DROP FUNCTION safepay_guard_participant_demo()")
    op.execute("DROP FUNCTION safepay_guard_deal_demo()")
    op.drop_column("platform_policy", "beta_demo_enabled")
    op.drop_index("ix_deals_is_demo", table_name="deals")
    op.drop_column("deals", "is_demo")
    op.drop_column("users", "is_demo")
