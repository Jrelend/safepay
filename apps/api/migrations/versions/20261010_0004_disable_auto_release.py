"""disable automatic release by default (Beta v0.1 release safety)

An expired inspection window must not release escrow by itself. Funds leave
escrow only by the buyer's CONFIRM_RECEIPT, the seller's REFUND, or an admin
decision. ``platform_policy.auto_release_enabled`` (one row, default false,
writable only by the schema owner) gates the SYSTEM function's AUTO_RELEASE in
SQL, so even a stolen worker credential cannot release funds. Re-enabling it is
an explicit, audited owner action (``python -m app.cli set-auto-release on``).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-10 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

from app.domain.deal_terms import EXPIRY_DAYS

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_HEADER = r"""
CREATE OR REPLACE FUNCTION safepay_system_transition_deal(
    p_deal_id uuid,
    p_action text,
    p_request_id text DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_deal deals%ROWTYPE;
BEGIN
    IF p_action IS NULL OR p_action NOT IN ('EXPIRE', 'AUTO_RELEASE') THEN
        RAISE EXCEPTION 'SafePay: SYSTEM may only EXPIRE or AUTO_RELEASE' USING ERRCODE = 'SPD03';
    END IF;
"""

_POLICY_GATE = r"""
    -- Beta v0.1: automatic release is OFF unless the owner explicitly enabled it.
    IF p_action = 'AUTO_RELEASE' AND NOT coalesce(
           (SELECT auto_release_enabled FROM platform_policy WHERE id), false) THEN
        RAISE EXCEPTION 'SafePay: automatic release is disabled' USING ERRCODE = 'SPD10';
    END IF;
"""

_BODY = r"""
    SELECT * INTO v_deal FROM deals WHERE id = p_deal_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'SafePay: deal % not found', p_deal_id USING ERRCODE = 'SPD01';
    END IF;
    IF p_action = 'EXPIRE'
       AND v_deal.status_changed_at > now() - make_interval(days => __EXPIRY_DAYS__) THEN
        RAISE EXCEPTION 'SafePay: deal % is not yet eligible to expire', p_deal_id
            USING ERRCODE = 'SPD08';
    END IF;
    IF p_action = 'AUTO_RELEASE' AND (
           v_deal.status <> 'DELIVERED'
        OR v_deal.status_changed_at > now() - make_interval(days => v_deal.inspection_days)) THEN
        RAISE EXCEPTION 'SafePay: inspection window of deal % has not ended', p_deal_id
            USING ERRCODE = 'SPD08';
    END IF;
    RETURN safepay__apply_transition(p_deal_id, p_action, 'SYSTEM', NULL, NULL, p_request_id, NULL);
END;
$$;
""".replace("__EXPIRY_DAYS__", str(EXPIRY_DAYS))

GATED_FUNCTION_SQL = _HEADER + _POLICY_GATE + _BODY
UNGATED_FUNCTION_SQL = _HEADER + _BODY  # exactly the 0003 version

POLICY_GUARD_SQL = r"""
CREATE FUNCTION safepay_guard_platform_policy() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'SafePay: platform_policy row cannot be deleted';
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;
CREATE TRIGGER platform_policy_guard BEFORE UPDATE OR DELETE ON platform_policy
    FOR EACH ROW EXECUTE FUNCTION safepay_guard_platform_policy();
REVOKE EXECUTE ON FUNCTION safepay_guard_platform_policy() FROM PUBLIC;
"""


def upgrade() -> None:
    op.create_table(
        "platform_policy",
        sa.Column("id", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "auto_release_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("note", sa.String(length=200), server_default="", nullable=False),
        sa.CheckConstraint("id", name=op.f("ck_platform_policy_single_row")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_policy")),
    )
    op.execute(
        "INSERT INTO platform_policy (id, auto_release_enabled, note) "
        "VALUES (true, false, 'Beta v0.1: automatic release disabled')"
    )
    op.execute(POLICY_GUARD_SQL)
    op.execute(GATED_FUNCTION_SQL)
    # Read-only for every runtime role; only the owner may change the policy.
    op.execute("REVOKE ALL ON platform_policy FROM PUBLIC")
    op.execute("GRANT SELECT ON platform_policy TO safepay_app, safepay_system, safepay_admin")


def downgrade() -> None:
    # Going back to 0003 restores time-based AUTO_RELEASE. Refuse while any deal is
    # DELIVERED (its escrow would become releasable by the worker) unless forced.
    if context.get_x_argument(as_dictionary=True).get("allow_data_loss") != "true":
        op.execute(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT FROM deals WHERE status = 'DELIVERED') THEN
                    RAISE EXCEPTION 'SafePay: refusing to downgrade below 0004 while deals '
                                    'are DELIVERED: it would re-enable time-based automatic '
                                    'release. Re-run with -x allow_data_loss=true to force.';
                END IF;
            END $$;
            """
        )
    op.execute(UNGATED_FUNCTION_SQL)
    op.execute("DROP TABLE platform_policy")
    op.execute("DROP FUNCTION safepay_guard_platform_policy()")
