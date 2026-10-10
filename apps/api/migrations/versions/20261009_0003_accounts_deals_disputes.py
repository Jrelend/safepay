"""accounts, deals, disputes (Beta v0.1)

* Accounts: email + Argon2id password, verification, sessions (hashed tokens),
  one-time tokens, a simulated email outbox, DB-backed rate limits, and an
  explicit ``admins`` table (granted only by the schema owner via the ops CLI).
* Privilege split: the public ``safepay_transition_deal`` now DERIVES the
  actor (BUYER/SELLER) from the participant row and can never act as SYSTEM or
  ADMIN. SYSTEM transitions (expiry, auto-release, eligibility re-checked in
  SQL) are executable only by ``safepay_system``; ADMIN refunds, dispute
  decisions and account suspension only by ``safepay_admin``. All share one
  internal implementation that no runtime role can execute.
* Deal terms (item type, delivery, inspection window) frozen after DRAFT; invite
  link (hashed token); disputes, append-only private evidence, notifications.
* Escrow and wallet balances can never go negative (deferred check).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-09 19:54:59.363613

"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.domain.deal_terms import EXPIRY_DAYS
from migrations.safety import refuse_data_loss

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PREFLIGHT_SQL = r"""
DO $$
BEGIN
    IF current_user <> 'safepay_migrator' THEN
        RAISE EXCEPTION 'SafePay: run migrations as safepay_migrator (connected as %)', current_user;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'safepay_system')
       OR NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'safepay_admin') THEN
        RAISE EXCEPTION 'SafePay: roles safepay_system / safepay_admin are missing; '
                        're-run infra/postgres/bootstrap-roles.sql';
    END IF;
END;
$$;
"""

GUARDS_SQL = r"""
-- ---------------------------------------------------------------- sessions
CREATE FUNCTION safepay_guard_session() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        NEW.created_at := now();
        NEW.last_seen_at := now();
        NEW.revoked_at := NULL;
        IF NEW.expires_at > now() + interval '30 days' THEN
            RAISE EXCEPTION 'SafePay: session lifetime too long' USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.id <> OLD.id OR NEW.token_hash <> OLD.token_hash OR NEW.csrf_hash <> OLD.csrf_hash
       OR NEW.user_id <> OLD.user_id OR NEW.created_at <> OLD.created_at
       OR NEW.expires_at <> OLD.expires_at OR NEW.user_agent <> OLD.user_agent
       OR NEW.ip_address <> OLD.ip_address THEN
        RAISE EXCEPTION 'SafePay: session identity is immutable' USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
        RAISE EXCEPTION 'SafePay: a revoked session cannot be restored'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.last_seen_at < OLD.last_seen_at THEN
        NEW.last_seen_at := OLD.last_seen_at;
    END IF;
    IF NEW.revoked_at IS NOT NULL AND OLD.revoked_at IS NULL THEN
        NEW.revoked_at := now();
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER sessions_guard
    BEFORE INSERT OR UPDATE ON sessions
    FOR EACH ROW EXECUTE FUNCTION safepay_guard_session();

-- ------------------------------------------------------------ auth tokens
CREATE FUNCTION safepay_guard_auth_token() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        NEW.created_at := now();
        NEW.used_at := NULL;
        IF NEW.expires_at > now() + interval '2 days' THEN
            RAISE EXCEPTION 'SafePay: token lifetime too long' USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.id <> OLD.id OR NEW.user_id <> OLD.user_id OR NEW.purpose <> OLD.purpose
       OR NEW.token_hash <> OLD.token_hash OR NEW.expires_at <> OLD.expires_at
       OR NEW.created_at <> OLD.created_at THEN
        RAISE EXCEPTION 'SafePay: auth tokens are immutable' USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.used_at IS NOT NULL THEN
        RAISE EXCEPTION 'SafePay: token already used' USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.used_at IS NOT NULL THEN
        NEW.used_at := now();
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER auth_tokens_guard
    BEFORE INSERT OR UPDATE ON auth_tokens
    FOR EACH ROW EXECUTE FUNCTION safepay_guard_auth_token();

-- ------------------------------------------------------------------ users
CREATE FUNCTION safepay_guard_user() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        NEW.created_at := now();
        NEW.updated_at := now();
        IF NEW.status <> 'ACTIVE' THEN
            RAISE EXCEPTION 'SafePay: users are created ACTIVE' USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.id <> OLD.id OR NEW.email <> OLD.email OR NEW.created_at <> OLD.created_at THEN
        RAISE EXCEPTION 'SafePay: user identity is immutable' USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.email_verified_at IS NOT NULL AND NEW.email_verified_at IS DISTINCT FROM OLD.email_verified_at THEN
        RAISE EXCEPTION 'SafePay: email verification cannot be changed once set'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.email_verified_at IS NOT NULL AND OLD.email_verified_at IS NULL THEN
        NEW.email_verified_at := now();
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER users_guard
    BEFORE INSERT OR UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION safepay_guard_user();

-- ------------------------------------------------------------ deal terms
-- Runs alongside 0002's deals_guard_update (triggers fire in name order).
CREATE FUNCTION safepay_guard_deal_terms() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        NEW.status_changed_at := now();
        RETURN NEW;
    END IF;
    IF OLD.status <> 'DRAFT' AND (
           NEW.title <> OLD.title OR NEW.description <> OLD.description
        OR NEW.item_type <> OLD.item_type OR NEW.delivery_method <> OLD.delivery_method
        OR NEW.inspection_days <> OLD.inspection_days) THEN
        RAISE EXCEPTION 'SafePay: deal terms are frozen once the deal leaves DRAFT'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.status NOT IN ('DRAFT') AND (
           NEW.invite_token_hash <> OLD.invite_token_hash
        OR NEW.invite_email IS DISTINCT FROM OLD.invite_email) THEN
        RAISE EXCEPTION 'SafePay: invitations can only change while DRAFT'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.status <> OLD.status THEN
        NEW.status_changed_at := now();
    ELSE
        NEW.status_changed_at := OLD.status_changed_at;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER deals_guard_terms
    BEFORE INSERT OR UPDATE ON deals
    FOR EACH ROW EXECUTE FUNCTION safepay_guard_deal_terms();

-- --------------------------------------------------------------- disputes
CREATE FUNCTION safepay_guard_dispute() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        NEW.opened_at := now();
        NEW.status := 'OPEN';
        NEW.resolved_at := NULL;
        NEW.outcome := NULL;
        NEW.decided_by_id := NULL;
        NEW.decision_reason := NULL;
        RETURN NEW;
    END IF;
    IF NEW.id <> OLD.id OR NEW.deal_id <> OLD.deal_id OR NEW.opened_by_id <> OLD.opened_by_id
       OR NEW.reason <> OLD.reason OR NEW.opened_at <> OLD.opened_at THEN
        RAISE EXCEPTION 'SafePay: dispute facts are immutable' USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.status <> 'OPEN' OR NEW.status <> 'RESOLVED' THEN
        RAISE EXCEPTION 'SafePay: a dispute can only be resolved once'
            USING ERRCODE = 'restrict_violation';
    END IF;
    NEW.resolved_at := now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER disputes_guard
    BEFORE INSERT OR UPDATE ON disputes
    FOR EACH ROW EXECUTE FUNCTION safepay_guard_dispute();

CREATE TRIGGER disputes_no_delete
    BEFORE DELETE ON disputes
    FOR EACH ROW EXECUTE FUNCTION safepay_forbid_mutation();

-- ---------------------------------------------------------------- evidence
CREATE FUNCTION safepay_guard_evidence() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_deal uuid;
BEGIN
    SELECT d.deal_id INTO v_deal FROM disputes d WHERE d.id = NEW.dispute_id AND d.status = 'OPEN';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'SafePay: evidence can only be added to an open dispute'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.kind = 'ADMIN_NOTE' THEN
        IF NOT EXISTS (
            SELECT FROM admins a JOIN users u ON u.id = a.user_id
             WHERE a.user_id = NEW.author_user_id AND u.status = 'ACTIVE'
        ) THEN
            RAISE EXCEPTION 'SafePay: only administrators may add admin notes'
                USING ERRCODE = 'restrict_violation';
        END IF;
    ELSIF NOT EXISTS (
        SELECT FROM deal_participants WHERE deal_id = v_deal AND user_id = NEW.author_user_id
    ) THEN
        RAISE EXCEPTION 'SafePay: only deal participants may submit evidence'
            USING ERRCODE = 'restrict_violation';
    END IF;
    NEW.created_at := now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER dispute_evidence_guard
    BEFORE INSERT ON dispute_evidence
    FOR EACH ROW EXECUTE FUNCTION safepay_guard_evidence();

CREATE TRIGGER dispute_evidence_no_update_delete
    BEFORE UPDATE OR DELETE ON dispute_evidence
    FOR EACH ROW EXECUTE FUNCTION safepay_forbid_mutation();

CREATE TRIGGER dispute_evidence_no_truncate
    BEFORE TRUNCATE ON dispute_evidence
    FOR EACH STATEMENT EXECUTE FUNCTION safepay_forbid_mutation();

-- ------------------------------------------------------------ notifications
CREATE FUNCTION safepay_guard_notification() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        NEW.created_at := now();
        NEW.read_at := NULL;
        RETURN NEW;
    END IF;
    IF NEW.id <> OLD.id OR NEW.user_id <> OLD.user_id OR NEW.kind <> OLD.kind
       OR NEW.deal_id IS DISTINCT FROM OLD.deal_id OR NEW.data <> OLD.data
       OR NEW.created_at <> OLD.created_at THEN
        RAISE EXCEPTION 'SafePay: notifications are immutable except read_at'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.read_at IS NOT NULL THEN
        NEW.read_at := OLD.read_at;
    ELSIF NEW.read_at IS NOT NULL THEN
        NEW.read_at := now();
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER notifications_guard
    BEFORE INSERT OR UPDATE ON notifications
    FOR EACH ROW EXECUTE FUNCTION safepay_guard_notification();

-- ------------------------------------------- escrow / wallets never negative
CREATE FUNCTION safepay_check_account_not_negative() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_purpose text;
    v_balance numeric;
BEGIN
    SELECT purpose INTO v_purpose FROM ledger_accounts WHERE id = NEW.account_id;
    IF v_purpose IN ('USER_WALLET', 'DEAL_ESCROW') THEN
        SELECT COALESCE(SUM(CASE direction WHEN 'CREDIT' THEN amount_mnt ELSE -amount_mnt END), 0)
          INTO v_balance
          FROM ledger_entries WHERE account_id = NEW.account_id;
        IF v_balance < 0 THEN
            RAISE EXCEPTION 'SafePay: account % would have a negative balance (%)',
                NEW.account_id, v_balance USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER ledger_entries_not_negative
    AFTER INSERT ON ledger_entries
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION safepay_check_account_not_negative();
"""

FUNCTIONS_SQL = r"""
-- The single implementation of a deal transition. Executable by NO runtime role:
-- only the wrappers below (owned by the same role) may call it.
CREATE FUNCTION safepay__apply_transition(
    p_deal_id uuid,
    p_action text,
    p_actor text,
    p_actor_user_id uuid,
    p_expected_version integer,
    p_request_id text,
    p_note text
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
    v_dispute uuid;
BEGIN
    IF p_actor IS NULL OR p_actor NOT IN ('BUYER', 'SELLER', 'SYSTEM', 'ADMIN') THEN
        RAISE EXCEPTION 'SafePay: unknown actor %', p_actor USING ERRCODE = 'SPD03';
    END IF;

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

    IF v_deal.status = 'DRAFT' AND v_rule.to_status <> 'CANCELLED' AND (
        SELECT count(*) FROM deal_participants WHERE deal_id = p_deal_id
    ) <> 2 THEN
        RAISE EXCEPTION 'SafePay: deal % needs a buyer and a seller before %', p_deal_id, p_action
            USING ERRCODE = 'SPD04';
    END IF;

    IF p_actor IN ('BUYER', 'SELLER') THEN
        IF p_actor_user_id IS NULL OR NOT EXISTS (
            SELECT FROM deal_participants
             WHERE deal_id = p_deal_id AND user_id = p_actor_user_id AND role = p_actor
        ) THEN
            RAISE EXCEPTION 'SafePay: user % is not the % of deal %', p_actor_user_id, p_actor, p_deal_id
                USING ERRCODE = 'SPD04';
        END IF;
        IF NOT EXISTS (
            SELECT FROM users
             WHERE id = p_actor_user_id AND status = 'ACTIVE' AND email_verified_at IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'SafePay: user % is not active and verified', p_actor_user_id
                USING ERRCODE = 'SPD06';
        END IF;
        IF p_action = 'SUBMIT' AND p_actor_user_id <> v_deal.created_by_id THEN
            RAISE EXCEPTION 'SafePay: only the deal creator submits the terms'
                USING ERRCODE = 'SPD03';
        END IF;
        IF p_action IN ('ACCEPT', 'DECLINE') AND p_actor_user_id = v_deal.created_by_id THEN
            RAISE EXCEPTION 'SafePay: the counterparty, not the creator, accepts or declines'
                USING ERRCODE = 'SPD03';
        END IF;
    ELSIF p_actor = 'SYSTEM' THEN
        IF p_actor_user_id IS NOT NULL THEN
            RAISE EXCEPTION 'SafePay: SYSTEM transitions have no acting user'
                USING ERRCODE = 'SPD04';
        END IF;
    ELSE  -- ADMIN
        IF NOT EXISTS (
            SELECT FROM admins a JOIN users u ON u.id = a.user_id
             WHERE a.user_id = p_actor_user_id AND u.status = 'ACTIVE'
        ) THEN
            RAISE EXCEPTION 'SafePay: user % is not an administrator', p_actor_user_id
                USING ERRCODE = 'SPD09';
        END IF;
        IF EXISTS (
            SELECT FROM deal_participants WHERE deal_id = p_deal_id AND user_id = p_actor_user_id
        ) THEN
            RAISE EXCEPTION 'SafePay: administrators cannot act on their own deals'
                USING ERRCODE = 'SPD09';
        END IF;
        IF coalesce(btrim(p_note), '') = '' THEN
            RAISE EXCEPTION 'SafePay: administrative actions require a reason'
                USING ERRCODE = 'SPD07';
        END IF;
    END IF;

    IF p_action = 'OPEN_DISPUTE' AND char_length(coalesce(btrim(p_note), '')) < 10 THEN
        RAISE EXCEPTION 'SafePay: a dispute needs a reason of at least 10 characters'
            USING ERRCODE = 'SPD07';
    END IF;

    IF v_rule.ledger_effect <> 'NONE' THEN
        INSERT INTO ledger_accounts (code, account_type, purpose, deal_id)
        VALUES ('ESCROW:' || p_deal_id, 'LIABILITY', 'DEAL_ESCROW', p_deal_id)
        ON CONFLICT DO NOTHING;
        SELECT id INTO STRICT v_escrow FROM ledger_accounts
         WHERE purpose = 'DEAL_ESCROW' AND deal_id = p_deal_id;

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
            ON CONFLICT DO NOTHING;
            v_debit := v_escrow;
            SELECT id INTO STRICT v_credit FROM ledger_accounts
             WHERE purpose = 'USER_WALLET' AND owner_user_id = v_payee;
        END IF;

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

    IF p_action IN ('SUBMIT', 'ACCEPT') THEN
        UPDATE deal_participants SET accepted_at = now()
         WHERE deal_id = p_deal_id AND user_id = p_actor_user_id AND accepted_at IS NULL;
    END IF;

    IF p_action = 'OPEN_DISPUTE' THEN
        INSERT INTO disputes (deal_id, opened_by_id, reason)
        VALUES (p_deal_id, p_actor_user_id, left(btrim(p_note), 5000))
        RETURNING id INTO v_dispute;
    END IF;

    INSERT INTO audit_events
        (actor_type, actor_user_id, action, entity_type, entity_id, deal_id, request_id, data)
    VALUES
        (p_actor, p_actor_user_id, 'deal.transition', 'deal', p_deal_id, p_deal_id,
         left(p_request_id, 64),
         jsonb_strip_nulls(jsonb_build_object(
             'action', p_action,
             'from', v_deal.status,
             'to', v_rule.to_status,
             'version', v_deal.version + 1,
             'amount_mnt', v_deal.amount_mnt,
             'ledger_transaction_id', v_tx,
             'dispute_id', v_dispute,
             'reason', CASE WHEN p_actor = 'ADMIN' THEN left(btrim(p_note), 2000) END)))
    RETURNING id INTO v_audit;

    INSERT INTO notifications (user_id, kind, deal_id, data)
    SELECT dp.user_id, 'deal.transition', p_deal_id,
           jsonb_build_object('action', p_action, 'from', v_deal.status,
                              'to', v_rule.to_status, 'actor', p_actor,
                              'title', v_deal.title, 'reference', v_deal.reference)
      FROM deal_participants dp
     WHERE dp.deal_id = p_deal_id AND dp.user_id IS DISTINCT FROM p_actor_user_id;

    RETURN jsonb_build_object(
        'deal_id', p_deal_id,
        'action', p_action,
        'from_status', v_deal.status,
        'to_status', v_rule.to_status,
        'version', v_deal.version + 1,
        'ledger_transaction_id', v_tx,
        'audit_event_id', v_audit,
        'dispute_id', v_dispute);
END;
$$;

-- PUBLIC (web API): the actor role is DERIVED from the participant row; the
-- caller cannot claim BUYER/SELLER, and can never act as SYSTEM or ADMIN.
CREATE FUNCTION safepay_transition_deal(
    p_deal_id uuid,
    p_action text,
    p_actor_user_id uuid,
    p_expected_version integer DEFAULT NULL,
    p_request_id text DEFAULT NULL,
    p_note text DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_role text;
BEGIN
    SELECT role INTO v_role FROM deal_participants
     WHERE deal_id = p_deal_id AND user_id = p_actor_user_id;
    IF NOT FOUND THEN
        IF NOT EXISTS (SELECT FROM deals WHERE id = p_deal_id) THEN
            RAISE EXCEPTION 'SafePay: deal % not found', p_deal_id USING ERRCODE = 'SPD01';
        END IF;
        RAISE EXCEPTION 'SafePay: user % is not a participant of deal %', p_actor_user_id, p_deal_id
            USING ERRCODE = 'SPD04';
    END IF;
    RETURN safepay__apply_transition(
        p_deal_id, p_action, v_role, p_actor_user_id, p_expected_version, p_request_id, p_note);
END;
$$;

-- SYSTEM (worker only): expiry and auto-release, re-checked for eligibility here.
CREATE FUNCTION safepay_system_transition_deal(
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

-- ADMIN (admin API only).
CREATE FUNCTION safepay_admin_transition_deal(
    p_deal_id uuid,
    p_action text,
    p_admin_user_id uuid,
    p_reason text,
    p_request_id text DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF p_action IS NULL OR p_action <> 'REFUND' THEN
        RAISE EXCEPTION 'SafePay: admins resolve disputes with safepay_admin_resolve_dispute'
            USING ERRCODE = 'SPD03';
    END IF;
    RETURN safepay__apply_transition(
        p_deal_id, p_action, 'ADMIN', p_admin_user_id, NULL, p_request_id, p_reason);
END;
$$;

CREATE FUNCTION safepay_admin_resolve_dispute(
    p_dispute_id uuid,
    p_outcome text,
    p_admin_user_id uuid,
    p_reason text,
    p_request_id text DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_dispute disputes%ROWTYPE;
    v_action text;
    v_result jsonb;
BEGIN
    v_action := CASE p_outcome
        WHEN 'RELEASE_TO_SELLER' THEN 'RESOLVE_RELEASE'
        WHEN 'REFUND_TO_BUYER' THEN 'RESOLVE_REFUND'
    END;
    IF v_action IS NULL THEN
        RAISE EXCEPTION 'SafePay: unknown dispute outcome %', p_outcome USING ERRCODE = 'SPD03';
    END IF;
    SELECT * INTO v_dispute FROM disputes WHERE id = p_dispute_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'SafePay: dispute % not found', p_dispute_id USING ERRCODE = 'SPD01';
    END IF;
    IF v_dispute.status <> 'OPEN' THEN
        RAISE EXCEPTION 'SafePay: dispute % is already resolved', p_dispute_id
            USING ERRCODE = 'SPD03';
    END IF;
    v_result := safepay__apply_transition(
        v_dispute.deal_id, v_action, 'ADMIN', p_admin_user_id, NULL, p_request_id, p_reason);
    UPDATE disputes
       SET status = 'RESOLVED', outcome = p_outcome, decided_by_id = p_admin_user_id,
           decision_reason = left(btrim(p_reason), 2000)
     WHERE id = p_dispute_id;
    RETURN v_result || jsonb_build_object('dispute_id', p_dispute_id, 'outcome', p_outcome);
END;
$$;

CREATE FUNCTION safepay_admin_set_user_status(
    p_admin_user_id uuid,
    p_user_id uuid,
    p_status text,
    p_reason text
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_old text;
BEGIN
    IF NOT EXISTS (
        SELECT FROM admins a JOIN users u ON u.id = a.user_id
         WHERE a.user_id = p_admin_user_id AND u.status = 'ACTIVE'
    ) THEN
        RAISE EXCEPTION 'SafePay: user % is not an administrator', p_admin_user_id
            USING ERRCODE = 'SPD09';
    END IF;
    IF p_status IS NULL OR p_status NOT IN ('ACTIVE', 'SUSPENDED') THEN
        RAISE EXCEPTION 'SafePay: invalid status %', p_status USING ERRCODE = 'SPD03';
    END IF;
    IF p_user_id = p_admin_user_id THEN
        RAISE EXCEPTION 'SafePay: administrators cannot change their own status'
            USING ERRCODE = 'SPD09';
    END IF;
    IF coalesce(btrim(p_reason), '') = '' THEN
        RAISE EXCEPTION 'SafePay: administrative actions require a reason' USING ERRCODE = 'SPD07';
    END IF;
    SELECT status INTO v_old FROM users WHERE id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'SafePay: user % not found', p_user_id USING ERRCODE = 'SPD01';
    END IF;
    UPDATE users SET status = p_status WHERE id = p_user_id;
    IF p_status = 'SUSPENDED' THEN
        UPDATE sessions SET revoked_at = now() WHERE user_id = p_user_id AND revoked_at IS NULL;
    END IF;
    INSERT INTO audit_events (actor_type, actor_user_id, action, entity_type, entity_id, data)
    VALUES ('ADMIN', p_admin_user_id, 'user.status_changed', 'user', p_user_id,
            jsonb_build_object('from', v_old, 'to', p_status,
                               'reason', left(btrim(p_reason), 2000)));
END;
$$;
"""

FUNCTIONS_SQL = FUNCTIONS_SQL.replace("__EXPIRY_DAYS__", str(int(EXPIRY_DAYS)))

PUBLIC_SIGNATURE = "safepay_transition_deal(uuid, text, uuid, integer, text, text)"
SYSTEM_SIGNATURE = "safepay_system_transition_deal(uuid, text, text)"
ADMIN_SIGNATURES = (
    "safepay_admin_transition_deal(uuid, text, uuid, text, text)",
    "safepay_admin_resolve_dispute(uuid, text, uuid, text, text)",
    "safepay_admin_set_user_status(uuid, uuid, text, text)",
)
OLD_SIGNATURE = "safepay_transition_deal(uuid, text, text, uuid, integer, text)"

# Deferred constraint triggers fire at COMMIT, outside the SECURITY DEFINER transition
# functions, i.e. with the *caller's* privileges. The worker and admin roles cannot read
# ledger tables, so these integrity checks run as their owner instead. (Trigger
# functions cannot be called directly, EXECUTE is revoked and search_path is pinned.)
DEFERRED_CHECKS = (
    "safepay_check_ledger_balanced()",
    "safepay_check_account_not_negative()",
    "safepay_require_idempotency_completion()",
)
PRE_0003_DEFERRED_CHECKS = (
    "safepay_check_ledger_balanced()",
    "safepay_require_idempotency_completion()",
)

GRANTS_SQL = rf"""
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM safepay_app, safepay_system, safepay_admin;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM safepay_system, safepay_admin;

-- ----------------------------------------------------------- safepay_app
-- Account status is changed only by administrators now.
REVOKE UPDATE (status) ON users FROM safepay_app;
-- Acceptance is recorded only by the transition function (SUBMIT / ACCEPT).
REVOKE UPDATE (accepted_at) ON deal_participants FROM safepay_app;
GRANT UPDATE (display_name, phone_e164, password_hash, email_verified_at, updated_at)
    ON users TO safepay_app;
GRANT UPDATE (item_type, delivery_method, inspection_days, invite_token_hash, invite_email)
    ON deals TO safepay_app;
GRANT SELECT ON admins, sessions, auth_tokens, email_outbox, rate_limits,
    disputes, dispute_evidence, notifications TO safepay_app;
GRANT INSERT ON sessions, auth_tokens, email_outbox, rate_limits,
    dispute_evidence, notifications TO safepay_app;
GRANT UPDATE (last_seen_at, revoked_at) ON sessions TO safepay_app;
GRANT UPDATE (used_at) ON auth_tokens TO safepay_app;
GRANT UPDATE (count) ON rate_limits TO safepay_app;
GRANT UPDATE (read_at) ON notifications TO safepay_app;
GRANT EXECUTE ON FUNCTION {PUBLIC_SIGNATURE} TO safepay_app;

-- -------------------------------------------------------- safepay_system
GRANT SELECT ON alembic_version, deals, rate_limits, email_outbox TO safepay_system;
GRANT DELETE ON rate_limits, email_outbox TO safepay_system;
GRANT EXECUTE ON FUNCTION {SYSTEM_SIGNATURE} TO safepay_system;

-- --------------------------------------------------------- safepay_admin
GRANT SELECT ON alembic_version, users, admins, sessions, deals, deal_participants,
    deal_transitions, disputes, dispute_evidence, ledger_accounts, ledger_transactions,
    ledger_entries, audit_events TO safepay_admin;
GRANT INSERT ON dispute_evidence TO safepay_admin;
GRANT EXECUTE ON FUNCTION {ADMIN_SIGNATURES[0]} TO safepay_admin;
GRANT EXECUTE ON FUNCTION {ADMIN_SIGNATURES[1]} TO safepay_admin;
GRANT EXECUTE ON FUNCTION {ADMIN_SIGNATURES[2]} TO safepay_admin;
"""

PIN_SEARCH_PATH_SQL = r"""
DO $$
DECLARE
    fn regprocedure;
BEGIN
    FOR fn IN
        SELECT p.oid::regprocedure FROM pg_proc p
          JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname = 'public' AND p.proname LIKE 'safepay\_%'
    LOOP
        EXECUTE format('ALTER FUNCTION %s SET search_path = pg_catalog, public, pg_temp', fn);
    END LOOP;
END;
$$;
"""

NEW_TRIGGERS = (
    ("sessions_guard", "sessions"),
    ("auth_tokens_guard", "auth_tokens"),
    ("users_guard", "users"),
    ("deals_guard_terms", "deals"),
    ("disputes_guard", "disputes"),
    ("disputes_no_delete", "disputes"),
    ("dispute_evidence_guard", "dispute_evidence"),
    ("dispute_evidence_no_update_delete", "dispute_evidence"),
    ("dispute_evidence_no_truncate", "dispute_evidence"),
    ("notifications_guard", "notifications"),
    ("ledger_entries_not_negative", "ledger_entries"),
)

NEW_FUNCTIONS = (
    "safepay_guard_session()",
    "safepay_guard_auth_token()",
    "safepay_guard_user()",
    "safepay_guard_deal_terms()",
    "safepay_guard_dispute()",
    "safepay_guard_evidence()",
    "safepay_guard_notification()",
    "safepay_check_account_not_negative()",
    PUBLIC_SIGNATURE,
    SYSTEM_SIGNATURE,
    *ADMIN_SIGNATURES,
    "safepay__apply_transition(uuid, text, text, uuid, integer, text, text)",
)


def _load_0002() -> ModuleType:
    """Load revision 0002 to restore its function exactly on downgrade."""
    path = next(Path(__file__).parent.glob("*_0002_*.py"))
    spec = importlib.util.spec_from_file_location("safepay_migration_0002", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def upgrade() -> None:
    op.execute(PREFLIGHT_SQL)
    op.create_table(
        "email_outbox",
        sa.Column("to_email", sa.String(length=254), nullable=False),
        sa.Column("template", sa.String(length=64), nullable=False),
        sa.Column(
            "data", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_outbox")),
    )
    op.create_index(op.f("ix_email_outbox_to_email"), "email_outbox", ["to_email"], unique=False)
    op.create_table(
        "rate_limits",
        sa.Column("bucket", sa.String(length=64), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("bucket", "key_hash", "window_start", name=op.f("pk_rate_limits")),
    )
    op.create_table(
        "admins",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("note", sa.String(length=200), server_default="", nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_admins_user_id_users"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_admins")),
    )
    op.create_table(
        "auth_tokens",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "purpose",
            sa.Enum(
                "VERIFY_EMAIL",
                "RESET_PASSWORD",
                name="token_purpose",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "purpose IN ('VERIFY_EMAIL', 'RESET_PASSWORD')",
            name=op.f("ck_auth_tokens_token_purpose"),
        ),
        sa.CheckConstraint(
            "token_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_auth_tokens_token_hash_sha256")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_auth_tokens_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_auth_tokens_token_hash")),
    )
    op.create_index(
        "ix_auth_tokens_user_id_purpose", "auth_tokens", ["user_id", "purpose"], unique=False
    )
    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
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
            "csrf_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_sessions_csrf_hash_sha256")
        ),
        sa.CheckConstraint(
            "token_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_sessions_token_hash_sha256")
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name=op.f("ck_sessions_expires_after_creation")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_sessions_user_id_users"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sessions_token_hash")),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"], unique=False)
    op.create_table(
        "disputes",
        sa.Column("deal_id", sa.Uuid(), nullable=False),
        sa.Column("opened_by_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "OPEN",
                "RESOLVED",
                name="dispute_status",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "opened_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "outcome",
            sa.Enum(
                "RELEASE_TO_SELLER",
                "REFUND_TO_BUYER",
                name="dispute_outcome",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("decided_by_id", sa.Uuid(), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.CheckConstraint(
            "(status = 'OPEN') = (resolved_at IS NULL AND outcome IS NULL AND decided_by_id IS NULL)",
            name=op.f("ck_disputes_resolution_consistent"),
        ),
        sa.CheckConstraint(
            "outcome IN ('RELEASE_TO_SELLER', 'REFUND_TO_BUYER')",
            name=op.f("ck_disputes_dispute_outcome"),
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'RESOLVED')", name=op.f("ck_disputes_dispute_status")
        ),
        sa.ForeignKeyConstraint(
            ["deal_id"], ["deals.id"], name=op.f("fk_disputes_deal_id_deals"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_id"],
            ["users.id"],
            name=op.f("fk_disputes_decided_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["opened_by_id"],
            ["users.id"],
            name=op.f("fk_disputes_opened_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_disputes")),
        sa.UniqueConstraint("deal_id", name=op.f("uq_disputes_deal_id")),
    )
    op.create_index(
        "ix_disputes_status_opened_at", "disputes", ["status", "opened_at"], unique=False
    )
    op.create_table(
        "notifications",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("deal_id", sa.Uuid(), nullable=True),
        sa.Column(
            "data", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["deal_id"],
            ["deals.id"],
            name=op.f("fk_notifications_deal_id_deals"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notifications_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    op.create_index(
        "ix_notifications_user_id_created_at",
        "notifications",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "dispute_evidence",
        sa.Column("dispute_id", sa.Uuid(), nullable=False),
        sa.Column("author_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "STATEMENT",
                "FILE",
                "ADMIN_NOTE",
                name="evidence_kind",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("body", sa.Text(), server_default="", nullable=False),
        sa.Column("file_name", sa.String(length=200), nullable=True),
        sa.Column("content_type", sa.String(length=64), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("file_sha256", sa.String(length=64), nullable=True),
        sa.Column("file_data", sa.LargeBinary(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(kind = 'FILE') = (file_data IS NOT NULL)",
            name=op.f("ck_dispute_evidence_file_kind_has_data"),
        ),
        sa.CheckConstraint(
            "file_data IS NULL OR (octet_length(file_data) BETWEEN 1 AND 2097152 AND file_size = octet_length(file_data) AND content_type IN ('image/png', 'image/jpeg', 'application/pdf'))",
            name=op.f("ck_dispute_evidence_file_limits"),
        ),
        sa.CheckConstraint(
            "kind IN ('STATEMENT', 'FILE', 'ADMIN_NOTE')",
            name=op.f("ck_dispute_evidence_evidence_kind"),
        ),
        sa.CheckConstraint(
            "char_length(body) <= 5000", name=op.f("ck_dispute_evidence_body_length")
        ),
        sa.ForeignKeyConstraint(
            ["author_user_id"],
            ["users.id"],
            name=op.f("fk_dispute_evidence_author_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dispute_id"],
            ["disputes.id"],
            name=op.f("fk_dispute_evidence_dispute_id_disputes"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dispute_evidence")),
    )
    op.create_index(
        "ix_dispute_evidence_dispute_id_created_at",
        "dispute_evidence",
        ["dispute_id", "created_at"],
        unique=False,
    )
    op.add_column(
        "deals",
        sa.Column(
            "status_changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "deals",
        sa.Column(
            "item_type",
            sa.Enum(
                "PHYSICAL_GOODS",
                "DIGITAL_GOODS",
                "SERVICE",
                name="item_type",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            server_default="PHYSICAL_GOODS",
            nullable=False,
        ),
    )
    op.add_column(
        "deals",
        sa.Column(
            "delivery_method",
            sa.Enum(
                "FACE_TO_FACE",
                "COURIER",
                "DIGITAL",
                name="delivery_method",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            server_default="FACE_TO_FACE",
            nullable=False,
        ),
    )
    op.add_column(
        "deals", sa.Column("inspection_days", sa.Integer(), server_default="3", nullable=False)
    )
    op.add_column("deals", sa.Column("invite_token_hash", sa.String(length=64), nullable=True))
    op.add_column("deals", sa.Column("invite_email", sa.String(length=254), nullable=True))
    op.create_index(
        "ix_deals_status_status_changed_at", "deals", ["status", "status_changed_at"], unique=False
    )
    op.create_unique_constraint(op.f("uq_deals_invite_token_hash"), "deals", ["invite_token_hash"])
    op.add_column("users", sa.Column("email", sa.String(length=254), nullable=True))
    op.add_column("users", sa.Column("password_hash", sa.Text(), nullable=True))
    op.add_column(
        "users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.alter_column("users", "phone_e164", existing_type=sa.VARCHAR(length=16), nullable=True)
    op.create_unique_constraint(op.f("uq_users_email"), "users", ["email"])

    # Existing rows are kept: placeholder email + an unusable password hash, and
    # a random (unknown) invite token hash. Nothing is deleted.
    op.execute(
        "UPDATE users SET email = 'legacy+' || id || '@invalid.local', "
        "password_hash = '!legacy-account-no-login' WHERE email IS NULL"
    )
    op.execute(
        "UPDATE deals SET invite_token_hash = "
        "encode(sha256(convert_to(gen_random_uuid()::text, 'UTF8')), 'hex'), "
        "version = version + 1 WHERE invite_token_hash IS NULL"
    )
    op.alter_column("users", "email", nullable=False)
    op.alter_column("users", "password_hash", nullable=False)
    op.alter_column("deals", "invite_token_hash", nullable=False)
    for table, name, condition in (
        ("users", "email_normalized", "email = lower(email) AND position('@' in email) > 1"),
        ("deals", "item_type", "item_type IN ('PHYSICAL_GOODS', 'DIGITAL_GOODS', 'SERVICE')"),
        ("deals", "delivery_method", "delivery_method IN ('FACE_TO_FACE', 'COURIER', 'DIGITAL')"),
        ("deals", "inspection_days_range", "inspection_days BETWEEN 1 AND 14"),
        ("deals", "title_length", "char_length(title) BETWEEN 3 AND 200"),
        ("deals", "invite_token_sha256", "invite_token_hash ~ '^[0-9a-f]{64}$'"),
        (
            "deals",
            "invite_email_normalized",
            "invite_email IS NULL OR invite_email = lower(invite_email)",
        ),
    ):
        op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, condition)

    op.execute(GUARDS_SQL)
    op.execute(f"DROP FUNCTION {OLD_SIGNATURE}")
    op.execute(FUNCTIONS_SQL)
    op.execute(GRANTS_SQL)
    op.execute(PIN_SEARCH_PATH_SQL)
    for signature in DEFERRED_CHECKS:
        op.execute(f"ALTER FUNCTION {signature} SECURITY DEFINER")


def downgrade() -> None:
    refuse_data_loss(
        (
            "users",
            "deals",
            "sessions",
            "auth_tokens",
            "email_outbox",
            "admins",
            "disputes",
            "dispute_evidence",
            "notifications",
            "rate_limits",
        )
    )
    for signature in NEW_FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS {signature} CASCADE")
    for signature in PRE_0003_DEFERRED_CHECKS:
        op.execute(f"ALTER FUNCTION {signature} SECURITY INVOKER")
    for table, name in (
        ("users", "email_normalized"),
        ("deals", "item_type"),
        ("deals", "delivery_method"),
        ("deals", "inspection_days_range"),
        ("deals", "title_length"),
        ("deals", "invite_token_sha256"),
        ("deals", "invite_email_normalized"),
    ):
        op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    # Restore exactly the 0002 public function and grants.
    m0002 = _load_0002()
    op.execute(m0002.TRANSITION_FUNCTION_SQL)
    op.execute(f"REVOKE EXECUTE ON FUNCTION {m0002.TRANSITION_SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {m0002.TRANSITION_SIGNATURE} TO safepay_app")
    op.execute("GRANT UPDATE (status) ON users TO safepay_app")
    op.execute("GRANT UPDATE (accepted_at) ON deal_participants TO safepay_app")
    op.execute(PIN_SEARCH_PATH_SQL)
    op.drop_constraint(op.f("uq_users_email"), "users", type_="unique")
    # Phone was mandatory before 0003; give phone-less accounts a unique placeholder.
    op.execute(
        "UPDATE users SET phone_e164 = '+000' || substr(md5(id::text), 1, 12) "
        "WHERE phone_e164 IS NULL"
    )
    op.alter_column("users", "phone_e164", existing_type=sa.VARCHAR(length=16), nullable=False)
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "password_hash")
    op.drop_column("users", "email")
    op.drop_constraint(op.f("uq_deals_invite_token_hash"), "deals", type_="unique")
    op.drop_index("ix_deals_status_status_changed_at", table_name="deals")
    op.drop_column("deals", "invite_email")
    op.drop_column("deals", "invite_token_hash")
    op.drop_column("deals", "inspection_days")
    op.drop_column("deals", "delivery_method")
    op.drop_column("deals", "item_type")
    op.drop_column("deals", "status_changed_at")
    op.drop_index("ix_dispute_evidence_dispute_id_created_at", table_name="dispute_evidence")
    op.drop_table("dispute_evidence")
    op.drop_index("ix_notifications_user_id_created_at", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_disputes_status_opened_at", table_name="disputes")
    op.drop_table("disputes")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("ix_auth_tokens_user_id_purpose", table_name="auth_tokens")
    op.drop_table("auth_tokens")
    op.drop_table("admins")
    op.drop_table("rate_limits")
    op.drop_index(op.f("ix_email_outbox_to_email"), table_name="email_outbox")
    op.drop_table("email_outbox")
