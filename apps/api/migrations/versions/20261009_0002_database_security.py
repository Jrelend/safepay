"""database security (Phase 1A)

Hardens the financial database before any money-moving feature exists:

* Least privilege. Every object is owned by ``safepay_migrator``; the runtime
  role ``safepay_app`` gets SELECT plus narrow column-level INSERT/UPDATE
  grants and **no** write access to the ledger tables or to ``deals.status``.
* All escrow money movement goes through one SECURITY DEFINER function,
  ``safepay_transition_deal``. It locks the deal row, checks the transition
  against ``deal_transitions``, verifies the acting participant, posts the
  escrow ledger transaction, bumps the deal version and writes the audit
  event, all inside the caller's database transaction.
* No double funding, release or refund: deterministic escrow idempotency keys
  plus partial unique indexes (one of each escrow kind per deal, and at most
  one settlement per deal).
* Guard triggers: deals start in DRAFT, only legal status changes are
  possible (for every role), identity columns are immutable, the amount is
  frozen after DRAFT, and every update bumps the version by exactly one.
* Audit timestamps and participant acceptance times are set by the database.
* ``idempotency_records`` rows are write-once after completion.

Requires ``infra/postgres/bootstrap-roles.sql`` to have been run, and must be
run as ``safepay_migrator`` (it refuses to run as a superuser).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-09 18:25:20.216206

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PREFLIGHT_SQL = r"""
DO $$
BEGIN
    IF current_user <> 'safepay_migrator' THEN
        RAISE EXCEPTION 'SafePay: run migrations as safepay_migrator (connected as %)', current_user;
    END IF;
    IF (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
        RAISE EXCEPTION 'SafePay: the migration role must not be a superuser';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'safepay_app') THEN
        RAISE EXCEPTION 'SafePay: role safepay_app is missing; run infra/postgres/bootstrap-roles.sql';
    END IF;
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tableowner <> current_user) THEN
        RAISE EXCEPTION 'SafePay: every table must be owned by %; see docs/SECURITY.md '
                        '("Migrating a Phase 0 database")', current_user;
    END IF;
END;
$$;
"""

SEED_SQL = r"""
INSERT INTO deal_transitions (from_status, action, to_status, actors, ledger_effect) VALUES
    ('DRAFT', 'SUBMIT', 'PENDING_ACCEPTANCE', ARRAY['BUYER','SELLER']::varchar[], 'NONE'),
    ('DRAFT', 'CANCEL', 'CANCELLED', ARRAY['BUYER','SELLER']::varchar[], 'NONE'),
    ('PENDING_ACCEPTANCE', 'ACCEPT', 'AWAITING_PAYMENT', ARRAY['BUYER','SELLER']::varchar[], 'NONE'),
    ('PENDING_ACCEPTANCE', 'DECLINE', 'CANCELLED', ARRAY['BUYER','SELLER']::varchar[], 'NONE'),
    ('PENDING_ACCEPTANCE', 'CANCEL', 'CANCELLED', ARRAY['BUYER','SELLER']::varchar[], 'NONE'),
    ('PENDING_ACCEPTANCE', 'EXPIRE', 'EXPIRED', ARRAY['SYSTEM']::varchar[], 'NONE'),
    ('AWAITING_PAYMENT', 'FUND', 'FUNDED', ARRAY['BUYER']::varchar[], 'HOLD_IN_ESCROW'),
    ('AWAITING_PAYMENT', 'CANCEL', 'CANCELLED', ARRAY['BUYER','SELLER']::varchar[], 'NONE'),
    ('AWAITING_PAYMENT', 'EXPIRE', 'EXPIRED', ARRAY['SYSTEM']::varchar[], 'NONE'),
    ('FUNDED', 'MARK_DELIVERED', 'DELIVERED', ARRAY['SELLER']::varchar[], 'NONE'),
    ('FUNDED', 'REFUND', 'REFUNDED', ARRAY['SELLER','ADMIN']::varchar[], 'REFUND_TO_BUYER'),
    ('FUNDED', 'OPEN_DISPUTE', 'DISPUTED', ARRAY['BUYER','SELLER']::varchar[], 'NONE'),
    ('DELIVERED', 'CONFIRM_RECEIPT', 'COMPLETED', ARRAY['BUYER']::varchar[], 'RELEASE_TO_SELLER'),
    ('DELIVERED', 'AUTO_RELEASE', 'COMPLETED', ARRAY['SYSTEM']::varchar[], 'RELEASE_TO_SELLER'),
    ('DELIVERED', 'OPEN_DISPUTE', 'DISPUTED', ARRAY['BUYER','SELLER']::varchar[], 'NONE'),
    ('DELIVERED', 'REFUND', 'REFUNDED', ARRAY['SELLER','ADMIN']::varchar[], 'REFUND_TO_BUYER'),
    ('DISPUTED', 'RESOLVE_RELEASE', 'COMPLETED', ARRAY['ADMIN']::varchar[], 'RELEASE_TO_SELLER'),
    ('DISPUTED', 'RESOLVE_REFUND', 'REFUNDED', ARRAY['ADMIN']::varchar[], 'REFUND_TO_BUYER');

INSERT INTO ledger_accounts (code, account_type, purpose)
VALUES ('SYSTEM:SIMULATED_CASH', 'ASSET', 'SIMULATED_CASH');
"""

GUARDS_SQL = r"""
-- Server-generated audit timestamps: whatever the client sends is overwritten.
CREATE FUNCTION safepay_stamp_audit_event() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.occurred_at := clock_timestamp();
    RETURN NEW;
END;
$$;

CREATE TRIGGER audit_events_stamp
    BEFORE INSERT ON audit_events
    FOR EACH ROW EXECUTE FUNCTION safepay_stamp_audit_event();

CREATE FUNCTION safepay_guard_deal_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status <> 'DRAFT' OR NEW.version <> 1 THEN
        RAISE EXCEPTION 'SafePay: deals must be created in DRAFT at version 1'
            USING ERRCODE = 'check_violation';
    END IF;
    NEW.created_at := now();
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

CREATE FUNCTION safepay_guard_deal_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.id <> OLD.id OR NEW.reference <> OLD.reference
       OR NEW.created_by_id <> OLD.created_by_id OR NEW.currency <> OLD.currency
       OR NEW.created_at <> OLD.created_at THEN
        RAISE EXCEPTION 'SafePay: deal identity columns are immutable'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.amount_mnt <> OLD.amount_mnt AND OLD.status <> 'DRAFT' THEN
        RAISE EXCEPTION 'SafePay: deal amount is frozen once the deal leaves DRAFT'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.status <> OLD.status AND NOT EXISTS (
        SELECT FROM deal_transitions
         WHERE from_status = OLD.status AND to_status = NEW.status
    ) THEN
        RAISE EXCEPTION 'SafePay: illegal deal transition % -> %', OLD.status, NEW.status
            USING ERRCODE = 'SPD03';
    END IF;
    IF NEW.version <> OLD.version + 1 THEN
        RAISE EXCEPTION 'SafePay: every deal update must increment version by exactly 1'
            USING ERRCODE = 'restrict_violation';
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER deals_guard_insert
    BEFORE INSERT ON deals
    FOR EACH ROW EXECUTE FUNCTION safepay_guard_deal_insert();

CREATE TRIGGER deals_guard_update
    BEFORE UPDATE ON deals
    FOR EACH ROW EXECUTE FUNCTION safepay_guard_deal_update();

CREATE FUNCTION safepay_guard_participant_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT FROM deals WHERE id = NEW.deal_id AND status IN ('DRAFT', 'PENDING_ACCEPTANCE')
    ) THEN
        RAISE EXCEPTION 'SafePay: participants can only be added before the deal is accepted'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.accepted_at IS NOT NULL THEN
        RAISE EXCEPTION 'SafePay: acceptance is recorded by updating accepted_at'
            USING ERRCODE = 'check_violation';
    END IF;
    NEW.created_at := now();
    RETURN NEW;
END;
$$;

CREATE FUNCTION safepay_guard_participant_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.id <> OLD.id OR NEW.deal_id <> OLD.deal_id OR NEW.user_id <> OLD.user_id
       OR NEW.role <> OLD.role OR NEW.created_at <> OLD.created_at THEN
        RAISE EXCEPTION 'SafePay: deal participants are immutable'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.accepted_at IS NOT NULL THEN
        RAISE EXCEPTION 'SafePay: acceptance cannot be changed once recorded'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.accepted_at IS NOT NULL THEN
        NEW.accepted_at := now();  -- server time, never the client's
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER deal_participants_guard_insert
    BEFORE INSERT ON deal_participants
    FOR EACH ROW EXECUTE FUNCTION safepay_guard_participant_insert();

CREATE TRIGGER deal_participants_guard_update
    BEFORE UPDATE ON deal_participants
    FOR EACH ROW EXECUTE FUNCTION safepay_guard_participant_update();

CREATE FUNCTION safepay_guard_idempotency_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.response IS NOT NULL OR NEW.completed_at IS NOT NULL THEN
        RAISE EXCEPTION 'SafePay: idempotency keys must be claimed before completion'
            USING ERRCODE = 'check_violation';
    END IF;
    NEW.created_at := now();
    RETURN NEW;
END;
$$;

CREATE FUNCTION safepay_guard_idempotency_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.completed_at IS NOT NULL THEN
        RAISE EXCEPTION 'SafePay: completed idempotency records are immutable'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.scope <> OLD.scope OR NEW.key <> OLD.key OR NEW.request_hash <> OLD.request_hash
       OR NEW.created_at <> OLD.created_at OR NEW.response IS NULL THEN
        RAISE EXCEPTION 'SafePay: an idempotency record may only be completed with a response'
            USING ERRCODE = 'restrict_violation';
    END IF;
    NEW.completed_at := now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER idempotency_records_guard_insert
    BEFORE INSERT ON idempotency_records
    FOR EACH ROW EXECUTE FUNCTION safepay_guard_idempotency_insert();

CREATE TRIGGER idempotency_records_guard_update
    BEFORE UPDATE ON idempotency_records
    FOR EACH ROW EXECUTE FUNCTION safepay_guard_idempotency_update();

CREATE TRIGGER deal_transitions_no_update_delete
    BEFORE UPDATE OR DELETE ON deal_transitions
    FOR EACH ROW EXECUTE FUNCTION safepay_forbid_mutation();
"""

TRANSITION_FUNCTION_SQL = r"""
CREATE FUNCTION safepay_transition_deal(
    p_deal_id uuid,
    p_action text,
    p_actor text,
    p_actor_user_id uuid,
    p_expected_version integer DEFAULT NULL,
    p_request_id text DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_deal deals%ROWTYPE;
    v_rule deal_transitions%ROWTYPE;
    v_kind text;
    v_payee_role text;
    v_payee uuid;
    v_escrow uuid;
    v_debit uuid;
    v_credit uuid;
    v_escrow_balance numeric;
    v_tx uuid;
    v_audit uuid;
BEGIN
    IF p_actor IS NULL OR p_actor NOT IN ('BUYER', 'SELLER', 'SYSTEM', 'ADMIN') THEN
        RAISE EXCEPTION 'SafePay: unknown actor %', p_actor USING ERRCODE = 'SPD03';
    END IF;

    -- Row lock: concurrent transitions of the same deal are serialized here.
    SELECT * INTO v_deal FROM deals WHERE id = p_deal_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'SafePay: deal % not found', p_deal_id USING ERRCODE = 'SPD01';
    END IF;

    IF p_expected_version IS NOT NULL AND v_deal.version <> p_expected_version THEN
        RAISE EXCEPTION 'SafePay: deal % is at version %, expected %',
            p_deal_id, v_deal.version, p_expected_version USING ERRCODE = 'SPD02';
    END IF;

    SELECT * INTO v_rule FROM deal_transitions
     WHERE from_status = v_deal.status AND action = p_action;
    IF NOT FOUND OR NOT (p_actor = ANY (v_rule.actors)) THEN
        RAISE EXCEPTION 'SafePay: % may not % a deal in state %', p_actor, p_action, v_deal.status
            USING ERRCODE = 'SPD03';
    END IF;

    -- The acting user must really be that participant of this deal.
    IF p_actor IN ('BUYER', 'SELLER') THEN
        IF p_actor_user_id IS NULL OR NOT EXISTS (
            SELECT FROM deal_participants
             WHERE deal_id = p_deal_id AND user_id = p_actor_user_id AND role = p_actor
        ) THEN
            RAISE EXCEPTION 'SafePay: user % is not the % of deal %', p_actor_user_id, p_actor, p_deal_id
                USING ERRCODE = 'SPD04';
        END IF;
    ELSIF p_actor = 'SYSTEM' AND p_actor_user_id IS NOT NULL THEN
        RAISE EXCEPTION 'SafePay: SYSTEM transitions have no acting user' USING ERRCODE = 'SPD04';
    ELSIF p_actor = 'ADMIN' AND NOT EXISTS (
        SELECT FROM users WHERE id = p_actor_user_id AND status = 'ACTIVE'
    ) THEN
        -- Phase 1A has no admin registry yet: any ACTIVE user id is accepted
        -- (see docs/SECURITY.md, remaining risks). The caller must authorize it.
        RAISE EXCEPTION 'SafePay: ADMIN transitions must name an active user' USING ERRCODE = 'SPD04';
    END IF;

    IF v_rule.ledger_effect <> 'NONE' THEN
        INSERT INTO ledger_accounts (code, account_type, purpose, deal_id)
        VALUES ('ESCROW:' || p_deal_id, 'LIABILITY', 'DEAL_ESCROW', p_deal_id)
        ON CONFLICT (code) DO NOTHING;
        SELECT id INTO STRICT v_escrow FROM ledger_accounts WHERE code = 'ESCROW:' || p_deal_id;

        SELECT COALESCE(SUM(CASE direction WHEN 'CREDIT' THEN amount_mnt ELSE -amount_mnt END), 0)
          INTO v_escrow_balance
          FROM ledger_entries WHERE account_id = v_escrow;

        IF v_rule.ledger_effect = 'HOLD_IN_ESCROW' THEN
            IF v_escrow_balance <> 0 THEN
                RAISE EXCEPTION 'SafePay: escrow of deal % already holds %', p_deal_id, v_escrow_balance
                    USING ERRCODE = 'SPD05';
            END IF;
            v_kind := 'ESCROW_HOLD';
            SELECT id INTO STRICT v_debit FROM ledger_accounts WHERE purpose = 'SIMULATED_CASH';
            v_credit := v_escrow;
        ELSE
            IF v_escrow_balance <> v_deal.amount_mnt THEN
                RAISE EXCEPTION 'SafePay: escrow of deal % holds %, expected %',
                    p_deal_id, v_escrow_balance, v_deal.amount_mnt USING ERRCODE = 'SPD05';
            END IF;
            IF v_rule.ledger_effect = 'RELEASE_TO_SELLER' THEN
                v_kind := 'ESCROW_RELEASE';
                v_payee_role := 'SELLER';
            ELSE
                v_kind := 'ESCROW_REFUND';
                v_payee_role := 'BUYER';
            END IF;
            SELECT user_id INTO v_payee FROM deal_participants
             WHERE deal_id = p_deal_id AND role = v_payee_role;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'SafePay: deal % has no %', p_deal_id, v_payee_role
                    USING ERRCODE = 'SPD04';
            END IF;
            INSERT INTO ledger_accounts (code, account_type, purpose, owner_user_id)
            VALUES ('WALLET:' || v_payee, 'LIABILITY', 'USER_WALLET', v_payee)
            ON CONFLICT (code) DO NOTHING;
            v_debit := v_escrow;
            SELECT id INTO STRICT v_credit FROM ledger_accounts WHERE code = 'WALLET:' || v_payee;
        END IF;

        -- Deterministic key + partial unique indexes: posted at most once per deal.
        INSERT INTO ledger_transactions (idempotency_key, kind, deal_id, description)
        VALUES ('deal:' || p_deal_id || ':' || v_kind, v_kind, p_deal_id,
                p_action || ' by ' || p_actor)
        RETURNING id INTO v_tx;

        INSERT INTO ledger_entries (transaction_id, account_id, direction, amount_mnt) VALUES
            (v_tx, v_debit, 'DEBIT', v_deal.amount_mnt),
            (v_tx, v_credit, 'CREDIT', v_deal.amount_mnt);
    END IF;

    UPDATE deals
       SET status = v_rule.to_status, version = v_deal.version + 1
     WHERE id = p_deal_id;

    INSERT INTO audit_events
        (actor_type, actor_user_id, action, entity_type, entity_id, deal_id, request_id, data)
    VALUES
        (p_actor, p_actor_user_id, 'deal.transition', 'deal', p_deal_id, p_deal_id,
         left(p_request_id, 64),
         jsonb_build_object(
             'action', p_action,
             'from', v_deal.status,
             'to', v_rule.to_status,
             'version', v_deal.version + 1,
             'amount_mnt', v_deal.amount_mnt,
             'ledger_transaction_id', v_tx))
    RETURNING id INTO v_audit;

    RETURN jsonb_build_object(
        'deal_id', p_deal_id,
        'action', p_action,
        'from_status', v_deal.status,
        'to_status', v_rule.to_status,
        'version', v_deal.version + 1,
        'ledger_transaction_id', v_tx,
        'audit_event_id', v_audit);
END;
$$;
"""

TRANSITION_SIGNATURE = "safepay_transition_deal(uuid, text, text, uuid, integer, text)"

GRANTS_SQL = rf"""
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM safepay_app;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM safepay_app;

GRANT SELECT ON
    alembic_version, users, deals, deal_participants, deal_transitions,
    ledger_accounts, ledger_transactions, ledger_entries,
    audit_events, idempotency_records
TO safepay_app;

GRANT INSERT ON users, deals, deal_participants, audit_events, idempotency_records
TO safepay_app;

GRANT UPDATE (display_name, status, updated_at) ON users TO safepay_app;
GRANT UPDATE (title, description, amount_mnt, version, updated_at) ON deals TO safepay_app;
GRANT UPDATE (accepted_at) ON deal_participants TO safepay_app;
GRANT UPDATE (response, completed_at) ON idempotency_records TO safepay_app;

GRANT EXECUTE ON FUNCTION {TRANSITION_SIGNATURE} TO safepay_app;
"""

REVOKE_SQL = rf"""
REVOKE EXECUTE ON FUNCTION {TRANSITION_SIGNATURE} FROM safepay_app;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM safepay_app;
"""

GUARD_FUNCTIONS = (
    "safepay_stamp_audit_event",
    "safepay_guard_deal_insert",
    "safepay_guard_deal_update",
    "safepay_guard_participant_insert",
    "safepay_guard_participant_update",
    "safepay_guard_idempotency_insert",
    "safepay_guard_idempotency_update",
)


def upgrade() -> None:
    op.execute(PREFLIGHT_SQL)
    op.create_table(
        "deal_transitions",
        sa.Column(
            "from_status",
            sa.Enum(
                "DRAFT",
                "PENDING_ACCEPTANCE",
                "AWAITING_PAYMENT",
                "FUNDED",
                "DELIVERED",
                "COMPLETED",
                "DISPUTED",
                "REFUNDED",
                "CANCELLED",
                "EXPIRED",
                name="transition_from_status",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "action",
            sa.Enum(
                "SUBMIT",
                "ACCEPT",
                "DECLINE",
                "CANCEL",
                "EXPIRE",
                "FUND",
                "MARK_DELIVERED",
                "CONFIRM_RECEIPT",
                "AUTO_RELEASE",
                "OPEN_DISPUTE",
                "REFUND",
                "RESOLVE_RELEASE",
                "RESOLVE_REFUND",
                name="transition_action",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "to_status",
            sa.Enum(
                "DRAFT",
                "PENDING_ACCEPTANCE",
                "AWAITING_PAYMENT",
                "FUNDED",
                "DELIVERED",
                "COMPLETED",
                "DISPUTED",
                "REFUNDED",
                "CANCELLED",
                "EXPIRED",
                name="transition_to_status",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("actors", postgresql.ARRAY(sa.String(length=16)), nullable=False),
        sa.Column(
            "ledger_effect",
            sa.Enum(
                "NONE",
                "HOLD_IN_ESCROW",
                "RELEASE_TO_SELLER",
                "REFUND_TO_BUYER",
                name="transition_ledger_effect",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('SUBMIT', 'ACCEPT', 'DECLINE', 'CANCEL', 'EXPIRE', 'FUND', 'MARK_DELIVERED', 'CONFIRM_RECEIPT', 'AUTO_RELEASE', 'OPEN_DISPUTE', 'REFUND', 'RESOLVE_RELEASE', 'RESOLVE_REFUND')",
            name=op.f("ck_deal_transitions_transition_action"),
        ),
        sa.CheckConstraint(
            "actors <@ ARRAY['BUYER', 'SELLER', 'SYSTEM', 'ADMIN']::varchar[]",
            name=op.f("ck_deal_transitions_known_actors"),
        ),
        sa.CheckConstraint(
            "from_status IN ('DRAFT', 'PENDING_ACCEPTANCE', 'AWAITING_PAYMENT', 'FUNDED', 'DELIVERED', 'COMPLETED', 'DISPUTED', 'REFUNDED', 'CANCELLED', 'EXPIRED')",
            name=op.f("ck_deal_transitions_transition_from_status"),
        ),
        sa.CheckConstraint(
            "ledger_effect IN ('NONE', 'HOLD_IN_ESCROW', 'RELEASE_TO_SELLER', 'REFUND_TO_BUYER')",
            name=op.f("ck_deal_transitions_transition_ledger_effect"),
        ),
        sa.CheckConstraint(
            "to_status IN ('DRAFT', 'PENDING_ACCEPTANCE', 'AWAITING_PAYMENT', 'FUNDED', 'DELIVERED', 'COMPLETED', 'DISPUTED', 'REFUNDED', 'CANCELLED', 'EXPIRED')",
            name=op.f("ck_deal_transitions_transition_to_status"),
        ),
        sa.CheckConstraint("cardinality(actors) > 0", name=op.f("ck_deal_transitions_has_actors")),
        sa.PrimaryKeyConstraint("from_status", "action", name=op.f("pk_deal_transitions")),
    )
    op.create_table(
        "idempotency_records",
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_idempotency_records_request_hash_sha256"),
        ),
        sa.CheckConstraint(
            "(completed_at IS NULL) = (response IS NULL)",
            name=op.f("ck_idempotency_records_completed_has_response"),
        ),
        sa.CheckConstraint("length(key) > 0", name=op.f("ck_idempotency_records_key_not_empty")),
        sa.PrimaryKeyConstraint("scope", "key", name=op.f("pk_idempotency_records")),
    )
    op.create_index(
        "uq_ledger_transactions_deal_escrow_kind",
        "ledger_transactions",
        ["deal_id", "kind"],
        unique=True,
        postgresql_where=sa.text("kind IN ('ESCROW_HOLD', 'ESCROW_RELEASE', 'ESCROW_REFUND')"),
    )
    op.create_index(
        "uq_ledger_transactions_deal_settlement",
        "ledger_transactions",
        ["deal_id"],
        unique=True,
        postgresql_where=sa.text("kind IN ('ESCROW_RELEASE', 'ESCROW_REFUND')"),
    )

    op.create_check_constraint(
        op.f("ck_ledger_transactions_escrow_kind_has_deal"),
        "ledger_transactions",
        "kind NOT IN ('ESCROW_HOLD', 'ESCROW_RELEASE', 'ESCROW_REFUND') OR deal_id IS NOT NULL",
    )
    op.execute(SEED_SQL)
    op.execute(GUARDS_SQL)
    op.execute(TRANSITION_FUNCTION_SQL)
    op.execute(GRANTS_SQL)


def downgrade() -> None:
    op.execute(REVOKE_SQL)
    op.execute(f"DROP FUNCTION {TRANSITION_SIGNATURE}")
    for trigger, table in (
        ("audit_events_stamp", "audit_events"),
        ("deals_guard_insert", "deals"),
        ("deals_guard_update", "deals"),
        ("deal_participants_guard_insert", "deal_participants"),
        ("deal_participants_guard_update", "deal_participants"),
    ):
        op.execute(f"DROP TRIGGER {trigger} ON {table}")
    for fn in GUARD_FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS {fn}() CASCADE")
    # Accounts can only be removed while nothing has been posted to them.
    op.execute(
        "DELETE FROM ledger_accounts WHERE code = 'SYSTEM:SIMULATED_CASH' "
        "OR code LIKE 'ESCROW:%' OR code LIKE 'WALLET:%'"
    )
    op.drop_constraint(
        op.f("ck_ledger_transactions_escrow_kind_has_deal"), "ledger_transactions", type_="check"
    )
    op.drop_index(
        "uq_ledger_transactions_deal_settlement",
        table_name="ledger_transactions",
        postgresql_where=sa.text("kind IN ('ESCROW_RELEASE', 'ESCROW_REFUND')"),
    )
    op.drop_index(
        "uq_ledger_transactions_deal_escrow_kind",
        table_name="ledger_transactions",
        postgresql_where=sa.text("kind IN ('ESCROW_HOLD', 'ESCROW_RELEASE', 'ESCROW_REFUND')"),
    )
    op.drop_table("idempotency_records")
    op.drop_table("deal_transitions")
