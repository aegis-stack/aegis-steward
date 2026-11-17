"""change_queue_carry_over

Revision ID: 076
Revises: 075
Create Date: 2026-11-16 21:30:00.000000

Finance's approval cards move onto the one queue: every
``finance_pending_change`` row is copied into ``pending_change``, ids
included (a chat transcript names its cards by id), then the old table goes.
The template's change_queue revision carries the same columns over
(``_FINANCE_QUEUE_CARRY_OVER``); 073 left it out while finance still filed
into its own queue.

Proven by the old table's absence beside the queue's (``no_table``); a
replay with the old table already gone does nothing.
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "076"
down_revision = "075"
branch_labels = None
depends_on = None
aegis_stamp_signature = ("no_table", "finance.finance_pending_change", "pending_change")

COLUMNS = (
    "id",
    "owner_user_id",
    "change_type",
    "payload",
    "proposed_by_agent",
    "conversation_id",
    "batch_id",
    "status",
    "result",
    "created_at",
    "updated_at",
    "resolved_at",
)


def _schema(bind: sa.engine.Connection) -> str | None:
    """Where finance's tables live: its own schema on Postgres, the one
    file on SQLite."""
    return "finance" if bind.dialect.name == "postgresql" else None


def _copy(
    bind: sa.engine.Connection,
    source: tuple[str, str | None],
    target: tuple[str, str | None],
) -> None:
    """Every row of ``source`` into ``target`` (each a table and its
    schema), ids included, and the target's id sequence moved past them on
    Postgres."""
    meta = sa.MetaData()
    old = sa.Table(source[0], meta, schema=source[1], autoload_with=bind)
    new = sa.Table(target[0], meta, schema=target[1], autoload_with=bind)
    op.execute(
        new.insert().from_select(
            list(COLUMNS), sa.select(*(old.c[name] for name in COLUMNS))
        )
    )
    if bind.dialect.name == "postgresql":
        named = f"{target[1]}.{target[0]}" if target[1] else target[0]
        op.execute(
            f"SELECT setval(pg_get_serial_sequence('{named}', 'id'), "
            f"COALESCE((SELECT MAX(id) FROM {named}), 0) + 1, false)"
        )


def upgrade() -> None:
    bind = op.get_bind()
    schema = _schema(bind)
    if not sa.inspect(bind).has_table("finance_pending_change", schema=schema):
        return
    _copy(bind, ("finance_pending_change", schema), ("pending_change", None))
    op.drop_table("finance_pending_change", schema=schema)


def downgrade() -> None:
    bind = op.get_bind()
    schema = _schema(bind)
    op.create_table(
        "finance_pending_change",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("change_type", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("proposed_by_agent", sa.String(64), nullable=True),
        sa.Column("conversation_id", sa.String(64), nullable=True),
        sa.Column("batch_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired')",
            name="ck_finance_pending_status",
        ),
        schema=schema,
    )
    with op.batch_alter_table("finance_pending_change", schema=schema) as batch_op:
        batch_op.create_index("ix_finance_pending_owner", ["owner_user_id"])
        batch_op.create_index("ix_finance_pending_status", ["status"])
        batch_op.create_index("ix_finance_pending_change_batch_id", ["batch_id"])
    _copy(bind, ("pending_change", None), ("finance_pending_change", schema))
    op.execute(sa.text("DELETE FROM pending_change"))
