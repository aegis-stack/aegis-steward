"""llm_tools_on_deployment

Revision ID: 079
Revises: 078
Create Date: 2026-11-22 13:30:00.000000

Whether a model calls tools has one home, its deployment's
``function_calling`` (the cloud sync's since the start; the local sync
now writes it there too). 077's ``supports_tools`` copy goes: a local
model it alone spoke for gets its serving org's deployment first.

Proven by the column's absence (``no_column``).
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "079"
down_revision = "078"
branch_labels = None
depends_on = None
aegis_stamp_signature = ("no_column", "large_language_model", "supports_tools")


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO llm_deployment (llm_id, org_id, speed, intelligence,"
            " reasoning, output_max_tokens, function_calling, input_cache,"
            " structured_output)"
            " SELECT m.id, m.served_by_org_id, 50, 50, 50, 4096,"
            " m.supports_tools, FALSE, FALSE FROM large_language_model m"
            " WHERE m.supports_tools IS NOT NULL"
            " AND m.served_by_org_id IS NOT NULL AND NOT EXISTS (SELECT 1"
            " FROM llm_deployment d WHERE d.llm_id = m.id"
            " AND d.org_id = m.served_by_org_id)"
        )
    )
    with op.batch_alter_table("large_language_model", schema=None) as batch_op:
        batch_op.drop_column("supports_tools")


def downgrade() -> None:
    with op.batch_alter_table("large_language_model", schema=None) as batch_op:
        batch_op.add_column(sa.Column("supports_tools", sa.Boolean(), nullable=True))
