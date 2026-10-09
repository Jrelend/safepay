"""Guards shared by migration scripts.

Downgrades drop tables, and ``DROP TABLE`` bypasses the append-only triggers, so
a careless ``alembic downgrade`` could erase ledger and audit history. Every
destructive downgrade therefore refuses to run while the affected tables hold
rows, unless the operator explicitly opts in after taking a backup::

    alembic -x allow_data_loss=true downgrade <revision>
"""

from collections.abc import Sequence

from alembic import context, op


def refuse_data_loss(tables: Sequence[str]) -> None:
    if context.get_x_argument(as_dictionary=True).get("allow_data_loss") == "true":
        return
    names = ", ".join(tables)
    checks = " OR ".join(f"EXISTS (SELECT FROM {table})" for table in tables)
    op.execute(
        f"""
        DO $$
        BEGIN
            IF {checks} THEN
                RAISE EXCEPTION 'SafePay: refusing to downgrade; it would permanently delete '
                                'rows in: {names}. Take a backup, then re-run with '
                                '-x allow_data_loss=true'
                    USING ERRCODE = 'restrict_violation';
            END IF;
        END;
        $$;
        """
    )
