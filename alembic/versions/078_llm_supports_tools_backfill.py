"""llm_supports_tools_backfill

Revision ID: 078
Revises: 077
Create Date: 2026-11-22 13:00:00.000000

A cloud model says whether it calls tools on its catalog row too
(``supports_tools``), which the cloud sync now fills: until then only its
deployment said (``llm_deployment.function_calling``), so a call's Thinks
list offered local models alone. Filled from the deployment where 077 left
it null; a local model has no deployment and keeps its engine's word.

Proven by a deployed model that says (``row``); a replay changes nothing.
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "078"
down_revision = "077"
branch_labels = None
depends_on = None
aegis_stamp_signature = (
    "row",
    "large_language_model",
    "supports_tools IS NOT NULL AND id IN (SELECT llm_id FROM llm_deployment)",
)

DEPLOYED = "FROM llm_deployment d WHERE d.llm_id = large_language_model.id"


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE large_language_model SET supports_tools = "
            f"EXISTS (SELECT 1 {DEPLOYED} AND d.function_calling) "
            f"WHERE supports_tools IS NULL AND EXISTS (SELECT 1 {DEPLOYED})"
        )
    )


def downgrade() -> None:
    """Nothing to undo: 077's downgrade drops the column."""
