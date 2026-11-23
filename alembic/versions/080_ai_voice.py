"""call_setup

Revision ID: 080
Revises: 079
Create Date: 2026-11-22 21:06:22.214405

A voice profile held two things: how a call runs (its engines, how a reply
is heard, what plays while it works, when it checks in) and how she sounds.
Picking a model rewrote the voice, and a live call ignored the voice it
could not speak. The run half moves to ``call_setup``, one row made from the
active profile; the voice keeps how she sounds, with a voice per speaking
provider (``voices``): her own on hers, and on OpenAI's ``marin``, the one a
call there spoke in all along, so nothing sounds different on day one.

``voice_pronunciation.ipa`` goes too: nothing ever read it.

Proven by the table (``call_setup``).
"""

import json
from typing import Any

import sqlalchemy as sa
import sqlmodel

from alembic import op

# revision identifiers, used by Alembic.
revision = "080"
down_revision = "079"
branch_labels = None
depends_on = None
aegis_stamp_signature = ("table", "call_setup")

# What moves from each profile to the call setup.
SETUP = (
    "stt_provider",
    "stt_model",
    "tts_provider",
    "tts_model",
    "reply",
    "working_sound",
    "live_idle_seconds",
    "live_engine",
)
# The voice a call on OpenAI spoke when the profile's was another
# provider's (``realtime_calls.OPENAI_VOICE``, gone with this revision).
OPENAI_VOICE = "marin"


def _voices(provider: str | None, voice: str | None) -> dict[str, str]:
    """A profile's voice on each provider, as it was heard: its own on its
    provider, and ``marin`` on OpenAI's where its own was elsewhere."""
    voices = {provider: voice} if provider and voice else {}
    voices.setdefault("openai", OPENAI_VOICE)
    return voices


def upgrade() -> None:
    op.create_table(
        "call_setup",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stt_provider", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("stt_model", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("tts_provider", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("tts_model", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("reply", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("working_sound", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("live_idle_seconds", sa.Integer(), nullable=False),
        sa.Column(
            "live_engine", sqlmodel.sql.sqltypes.AutoString(length=48), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    with op.batch_alter_table("voice_profile", schema=None) as batch_op:
        batch_op.add_column(sa.Column("voices", sa.JSON(), nullable=True))

    bind = op.get_bind()
    columns = ", ".join(SETUP)
    # The active profile's setup (else the first's); none on a fresh
    # database, where startup seeds it from .env.
    bind.execute(
        sa.text(
            f"INSERT INTO call_setup ({columns}, updated_at)"
            f" SELECT {columns}, updated_at FROM voice_profile"
            " ORDER BY is_active DESC, id LIMIT 1"
        )
    )
    rows: list[Any] = bind.execute(
        sa.text("SELECT id, tts_provider, tts_voice FROM voice_profile")
    ).all()
    for row in rows:
        voices = json.dumps(_voices(row.tts_provider, row.tts_voice))
        bind.execute(
            sa.text("UPDATE voice_profile SET voices = :voices WHERE id = :id"),
            {"voices": voices, "id": row.id},
        )

    # By name, not looped over SETUP: the drops are read as written
    # (tests/test_models_write_what_migrations_require.py).
    with op.batch_alter_table("voice_profile", schema=None) as batch_op:
        batch_op.drop_column("stt_provider")
        batch_op.drop_column("stt_model")
        batch_op.drop_column("tts_provider")
        batch_op.drop_column("tts_model")
        batch_op.drop_column("reply")
        batch_op.drop_column("working_sound")
        batch_op.drop_column("live_idle_seconds")
        batch_op.drop_column("live_engine")
        batch_op.drop_column("tts_voice")
    with op.batch_alter_table("voice_pronunciation", schema=None) as batch_op:
        batch_op.drop_column("ipa")


def downgrade() -> None:
    with op.batch_alter_table("voice_pronunciation", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "ipa", sqlmodel.sql.sqltypes.AutoString(length=200), nullable=True
            )
        )
    text, number = sqlmodel.sql.sqltypes.AutoString(), sa.Integer()
    with op.batch_alter_table("voice_profile", schema=None) as batch_op:
        for column in SETUP:
            kind = number if column == "live_idle_seconds" else text
            batch_op.add_column(sa.Column(column, kind, nullable=True))
        batch_op.add_column(sa.Column("tts_voice", text, nullable=True))

    bind = op.get_bind()
    setup = bind.execute(sa.text(f"SELECT {', '.join(SETUP)} FROM call_setup")).first()
    rows: list[Any] = bind.execute(
        sa.text("SELECT id, voices FROM voice_profile")
    ).all()
    for row in rows:
        values = dict(setup._mapping) if setup else {}
        voices = json.loads(row.voices) if isinstance(row.voices, str) else row.voices
        values["tts_voice"] = (voices or {}).get(values.get("tts_provider") or "")
        assigned = ", ".join(f"{key} = :{key}" for key in values)
        bind.execute(
            sa.text(f"UPDATE voice_profile SET {assigned} WHERE id = :id"),
            {**values, "id": row.id},
        )

    with op.batch_alter_table("voice_profile", schema=None) as batch_op:
        batch_op.drop_column("voices")
    op.drop_table("call_setup")
