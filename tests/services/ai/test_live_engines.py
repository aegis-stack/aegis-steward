"""Her live engines, as table data (#273).

A live call runs on an engine: GPT-Live (full duplex) or a Pydantic AI
realtime model (turn-taking, her own agent as the brain). Engines are rows, like agents and voice profiles: seeded
when missing, never overwritten once edited. The model an engine runs
on - its name, its maker, its price - is the catalog's row.
"""

from __future__ import annotations

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.ai.domains.voice import live_engines
from app.services.ai.domains.voice.profiles import SETUP
from app.services.ai.models.voice.live_engine import LiveEngine
from app.services.finance.domains.detection.analyst.live_engines import (
    ENGINE_SEEDS,
    HER_REALTIME_DEFAULTS,
)
from app.services.finance.domains.detection.analyst.prompts import (
    FINANCE_REALTIME_INSTRUCTIONS,
    LIVE_SIGN_OFF,
)
from tests._voice_catalog import seed_voice_catalog

# Her realtime manners before they were the template's (#273's copy).
FORMER_REALTIME = """\
## THIS IS A LIVE VOICE CALL

You are talking with them out loud, in real time. Everything below still \
applies - your role, your tools, how you compute and how you propose \
changes - except how you answer, which this section decides:

- One or two short sentences a reply. Lead with the answer.
- Never read out a list, a table or markdown. Round money to the dollar \
and say dates the way a person would.
- If there is more, say you can tell them more and let them ask.
- Before you look something up, say a few words ("Let me check") so there \
is no silence.
- If you propose a change, say in one sentence what it is; the card is on \
their screen to approve.
- When they are done - a goodbye, "that's all", thanks with nothing more \
to ask - say a short goodbye that ends with exactly "Talk soon." \
Never say those words at any other time."""


@pytest.fixture
async def seeded(async_db_session: AsyncSession) -> AsyncSession:
    await seed_voice_catalog(async_db_session)
    await live_engines.seed_missing(async_db_session, ENGINE_SEEDS)
    return async_db_session


async def _keyed(session: AsyncSession) -> dict[str, LiveEngine]:
    return {row.key: row for row in await live_engines.enabled(session)}


class TestTheRows:
    @pytest.mark.asyncio
    async def test_the_engines_on_offer(self, seeded: AsyncSession) -> None:
        keyed = await _keyed(seeded)
        assert list(keyed) == [
            "gpt-live",
            "gpt-realtime-2.1",
            "gpt-realtime-2.1-mini",
            "gemini-live",
        ]
        assert live_engines.DEFAULT in keyed

    @pytest.mark.asyncio
    async def test_each_names_its_model(self, seeded: AsyncSession) -> None:
        rows = await _keyed(seeded)
        live, realtime = rows["gpt-live"], rows["gpt-realtime-2.1"]
        assert live.llm.model_id == "gpt-live-1"
        assert live_engines.realtime_model(realtime) == "openai:gpt-realtime-2.1"

    @pytest.mark.asyncio
    async def test_an_edit_survives_the_next_seed(self, seeded: AsyncSession) -> None:
        row = (await _keyed(seeded))["gpt-realtime-2.1"]
        row.instructions = "Be terse."
        seeded.add(row)
        await seeded.commit()

        await live_engines.seed_missing(seeded, ENGINE_SEEDS)

        stored = await seeded.exec(
            select(LiveEngine.instructions).where(LiveEngine.key == row.key)
        )
        assert stored.one() == "Be terse."


class TestHowTheyTalk:
    @pytest.mark.asyncio
    async def test_gpt_live_carries_its_persona_and_its_rate(
        self, seeded: AsyncSession
    ) -> None:
        live = (await _keyed(seeded))["gpt-live"]
        assert LIVE_SIGN_OFF in (live.instructions or "")
        # The catalog's rate for its model, not a copy on the engine.
        assert await live_engines.per_second(seeded, live) == pytest.approx(0.05 / 60)

    @pytest.mark.asyncio
    async def test_a_realtime_engine_knows_it_is_a_live_call(
        self, seeded: AsyncSession
    ) -> None:
        """Her voice agent's prompt is mostly her chat prompt; on a realtime
        engine the model speaks it straight out, and she went on. Each
        realtime row leads with a live-call section and caps a reply."""
        realtime = (await _keyed(seeded))["gpt-realtime-2.1"]
        assert "LIVE" in (realtime.instructions or "")
        assert realtime.max_output_tokens
        assert await live_engines.per_second(seeded, realtime) is None  # tokens


def test_the_active_profile_carries_its_engine() -> None:
    assert SETUP["live_engine"] == "VOICE_LIVE_ENGINE"


class TestResolving:
    def test_an_unknown_engine_is_the_default(self) -> None:
        rows = [LiveEngine(llm_id=0, key=seed["key"]) for seed in ENGINE_SEEDS]
        found = live_engines.pick(rows, "nope")
        assert found is not None and found.key == live_engines.DEFAULT

    @pytest.mark.asyncio
    async def test_a_model_the_catalog_lacks_waits_for_a_sync(
        self, async_db_session: AsyncSession
    ) -> None:
        assert await live_engines.seed_missing(async_db_session, ENGINE_SEEDS) == 0

    @pytest.mark.asyncio
    async def test_a_turned_off_engine_is_not_on_offer(
        self, async_db_session: AsyncSession
    ) -> None:
        await seed_voice_catalog(async_db_session)
        off = tuple(
            {**seed, "is_enabled": seed["key"] != "gpt-realtime-2.1"}
            for seed in ENGINE_SEEDS
        )
        await live_engines.seed_missing(async_db_session, off)

        found = await live_engines.resolve(async_db_session, "gpt-realtime-2.1")
        assert found is not None and found.key == live_engines.DEFAULT


class TestChoosing:
    @pytest.mark.asyncio
    async def test_a_gemini_model_picked_talks_like_her_realtime_engines(
        self, async_db_session: AsyncSession
    ) -> None:
        """Picking a Gemini Live model with no engine makes one that talks
        like her seeded turn-taking engines, not the template's default."""
        from app.services.ai.models.llm import LargeLanguageModel, LLMOrg

        await seed_voice_catalog(async_db_session)
        google = (
            await async_db_session.exec(select(LLMOrg).where(LLMOrg.slug == "google"))
        ).one()
        async_db_session.add(
            LargeLanguageModel(
                model_id="gemini-3.1-flash-live-preview",
                title="Gemini 3.1 Flash Live",
                mode="realtime",
                served_by_org_id=google.id,
            )
        )
        await async_db_session.commit()

        made = await live_engines.choose(
            async_db_session, "gemini-3.1-flash-live-preview", ENGINE_SEEDS
        )

        assert made is not None
        seeded = next(s for s in ENGINE_SEEDS if s["key"] == "gemini-live")
        assert made.instructions == seeded["instructions"]
        assert made.max_output_tokens == seeded["max_output_tokens"]

    @pytest.mark.asyncio
    async def test_a_vendor_no_call_can_reach_is_refused(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.ai.models.llm import LargeLanguageModel, LLMOrg

        xai = LLMOrg(slug="xai", name="xai")
        async_db_session.add(xai)
        await async_db_session.flush()
        async_db_session.add(
            LargeLanguageModel(
                model_id="grok-voice",
                title="Grok Voice",
                mode="realtime",
                served_by_org_id=xai.id,
            )
        )
        await async_db_session.commit()

        assert (
            await live_engines.choose(async_db_session, "grok-voice", ENGINE_SEEDS)
            is None
        )


class TestHerCallManners:
    """Hers were a copy of the template's from before it drew cards: on a
    local call she said "charting them now" and drew nothing, announcing
    each lookup as the copy told her to (2026-11-21). Hers are the
    template's, with what only she does."""

    def test_they_are_the_templates_with_her_proposals(self) -> None:
        manners = FINANCE_REALTIME_INSTRUCTIONS
        assert manners.startswith(live_engines.LIVE_CALL_INSTRUCTIONS)
        assert "draw_card" in manners
        assert "propose a change" in manners

    def test_a_change_to_them_keeps_their_former_digest(self) -> None:
        """They follow the template's text, so an edit to either leaves rows
        on the old one: add its digest to HER_REALTIME_DEFAULTS, then
        pin the new one here."""
        text, former = HER_REALTIME_DEFAULTS
        assert live_engines.digest(text) == (
            "97b4468f754feb512ddbff0a55b2cf5b7c3226f69c006780c552b4d93b4ddf25"
        )
        assert live_engines.digest(text) not in former

    @pytest.mark.asyncio
    async def test_an_engine_on_her_former_manners_takes_the_current(
        self, seeded: AsyncSession
    ) -> None:
        rows = await _keyed(seeded)
        rows["gemini-live"].instructions = FORMER_REALTIME
        rows["gpt-realtime-2.1"].instructions = "Be terse."
        seeded.add_all(rows.values())
        await seeded.commit()

        await live_engines.refresh_defaults(seeded, HER_REALTIME_DEFAULTS)

        stored = dict(
            (await seeded.exec(select(LiveEngine.key, LiveEngine.instructions))).all()
        )
        assert stored["gemini-live"] == FINANCE_REALTIME_INSTRUCTIONS
        assert stored["gpt-realtime-2.1"] == "Be terse."
