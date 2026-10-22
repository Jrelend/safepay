"""local demo wallets: demo deals pay from the buyer's simulated wallet

LOCAL DEMO ONLY (see ``app/local_demo.py``). Until now funding a deal moved
simulated money from the platform's ``SIMULATED_CASH`` account into escrow, so
the buyer's balance never changed. For presentations, the buyer starts with a
simulated balance and watches it move into escrow.

``platform_policy.demo_wallets_enabled`` (default false, writable only by the
schema owner, set by ``python -m app.cli demo-seed`` which refuses outside
local/test) switches the HOLD posting of **demo** deals (``deals.is_demo``) to
debit the buyer's ``USER_WALLET`` instead, refusing with SPD11 when the wallet
holds less than the deal amount. The buyer's wallet row is locked first, so two
concurrent fundings cannot overspend it.

Unchanged: non-demo deals (always funded from ``SIMULATED_CASH``), every deal while
the policy is off (the default everywhere), release and refund postings, and all
other checks in the transition core.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-21 15:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRANSITION = "safepay__apply_transition(uuid, text, text, uuid, integer, text, text)"
CASH_ONLY = """            v_kind := 'ESCROW_HOLD';
            SELECT id INTO STRICT v_debit FROM ledger_accounts WHERE purpose = 'SIMULATED_CASH';
"""
DEMO_WALLET_OR_CASH = """            v_kind := 'ESCROW_HOLD';
            IF v_deal.is_demo
               AND coalesce((SELECT demo_wallets_enabled FROM platform_policy WHERE id), false) THEN
                -- LOCAL DEMO ONLY (migration 0007): pay from the buyer's simulated wallet.
                DECLARE
                    v_wallet_balance bigint;
                BEGIN
                    SELECT a.id INTO v_debit FROM ledger_accounts a
                      JOIN deal_participants p ON p.user_id = a.owner_user_id
                     WHERE p.deal_id = p_deal_id AND p.role = 'BUYER' AND a.purpose = 'USER_WALLET'
                       FOR UPDATE OF a;
                    SELECT COALESCE(SUM(CASE direction WHEN 'CREDIT' THEN amount_mnt
                                                       ELSE -amount_mnt END), 0)
                      INTO v_wallet_balance FROM ledger_entries WHERE account_id = v_debit;
                    IF v_debit IS NULL OR v_wallet_balance < v_deal.amount_mnt THEN
                        RAISE EXCEPTION 'SafePay: demo wallet holds %, deal needs %',
                            v_wallet_balance, v_deal.amount_mnt USING ERRCODE = 'SPD11';
                    END IF;
                END;
            ELSE
                SELECT id INTO STRICT v_debit FROM ledger_accounts WHERE purpose = 'SIMULATED_CASH';
            END IF;
"""


def _patch_transition(old: str, new: str) -> None:
    """Swap one exact block in the live function body (keeping owner, SECURITY
    DEFINER, search_path and grants: CREATE OR REPLACE preserves them). Line endings
    are normalised first: a Windows checkout stores the body with CRLF."""
    op.execute(
        f"""
DO $do$
DECLARE
    old_block text := replace($old${old}$old$, chr(13), '');
    new_block text := replace($new${new}$new$, chr(13), '');
    def text := replace(pg_get_functiondef('{TRANSITION}'::regprocedure), chr(13), '');
BEGIN
    IF (length(def) - length(replace(def, old_block, ''))) / length(old_block) <> 1 THEN
        RAISE EXCEPTION 'SafePay: expected exactly one escrow-hold block in %', '{TRANSITION}';
    END IF;
    EXECUTE replace(def, old_block, new_block);
END
$do$;
"""
    )


def upgrade() -> None:
    op.add_column(
        "platform_policy",
        sa.Column("demo_wallets_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _patch_transition(CASH_ONLY, DEMO_WALLET_OR_CASH)


def downgrade() -> None:
    _patch_transition(DEMO_WALLET_OR_CASH, CASH_ONLY)
    op.drop_column("platform_policy", "demo_wallets_enabled")
