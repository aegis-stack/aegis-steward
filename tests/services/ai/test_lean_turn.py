"""A lean turn (``_build_turn(lean=True)``): what a local model on a call
reads. Built whole, a call to a local 27B model was 53k tokens (her
memory, her readings, the change catalog, the whole thread): over Ollama's
32k window, and minutes of prefill before a word (2026-11-21). A lean
turn keeps her prompt and tools and the last few turns, nothing else."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

from app.services.ai.domains.chat import agent_loader
from app.services.ai.domains.chat.readings import Reading
from app.services.ai.domains.chat.user_memory import UserContext
from app.services.ai.models import AIProvider, Conversation
from app.services.ai.service import turn
from app.services.ai.service.prompt import HISTORY_CHAR_BUDGET_MIN


async def _built(
    monkeypatch: pytest.MonkeyPatch, *, fold_to: int = 0, **asked: Any
) -> dict[str, Any]:
    """What ``_build_turn`` handed the agent builder, her row carrying a
    context module, saved memory and a reading; what it handed back
    (``setup``) and the folds it queued (``folded``). Her history window
    starts three turns in, under a summary, a fold to ``fold_to`` due."""
    known = UserContext(
        memory="Saved: likes round numbers.",
        readings=[Reading(title="Form 1099-INT", fields={"Interest": "$12"})],
    )

    async def memory(_: str) -> UserContext:
        return known

    async def modules(names: Any, **_: Any) -> str | None:
        return f"modules: {list(names)}" if names else None

    async def window(_: Any) -> int:
        return 200_000

    async def prepare(_: Any, **kwargs: Any) -> tuple[Any, str]:
        from app.services.ai.domains.chat.self_context import (
            begin_turn_context,
            record_turn_context,
        )

        prepared.update(kwargs)
        begin_turn_context()
        record_turn_context(messages_dropped=3, summary="S", fold_to=fold_to)
        return None, ""

    import app.services.ai.domains.llm.catalog as catalog

    monkeypatch.setattr(turn, "build_user_memory_context", memory)
    monkeypatch.setattr(turn, "render_context_modules", modules)
    monkeypatch.setattr(catalog, "context_window_for", window)
    monkeypatch.setattr(turn, "enqueue_fold", lambda *args: args)
    monkeypatch.setattr(turn, "background", lambda work: folded.append(work))
    prepared: dict[str, Any] = {}
    folded: list[Any] = []
    config = replace(
        agent_loader.default_agent_config(), context_modules=("finance_changes",)
    )
    ai = SimpleNamespace(config=SimpleNamespace(model="m", provider="openai"))
    ai._prepare_agent_and_context = prepare
    setup = await turn.TurnMixin._build_turn(
        ai,  # type: ignore[arg-type]
        Conversation(id="c", provider=AIProvider.OLLAMA, model="m"),
        config,
        user_id="u",
        **asked,
    )
    return prepared | {"setup": setup, "folded": folded}


@pytest.mark.asyncio
async def test_a_turn_hands_back_its_history_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Where her history starts and the summary ahead of it: GPT-Live's
    voice is seeded with the same window (``realtime_calls``)."""
    setup = (await _built(monkeypatch))["setup"]

    assert (setup.history_start, setup.history_summary) == (3, "S")


@pytest.mark.asyncio
async def test_a_turn_queues_the_fold_its_window_found_due(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every turn, typed or spoken: a call never queued one, so a thread
    only ever talked on kept no summary of what fell out (2026-11-22)."""
    assert (await _built(monkeypatch, fold_to=4))["folded"] == [("c", 4)]
    assert (await _built(monkeypatch))["folded"] == []


@pytest.mark.asyncio
async def test_a_lean_turn_never_moves_the_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Its window is a few turns: folded to its cut, the summary would
    take every typed turn's history from there on."""
    assert (await _built(monkeypatch, fold_to=4, lean=True))["folded"] == []


@pytest.mark.asyncio
async def test_a_turn_reads_everything_it_knows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = await _built(monkeypatch)

    assert prepared["memory_context"] == "Saved: likes round numbers."
    assert len(prepared["readings"]) == 1
    assert prepared["agent_modules_context"] == "modules: ['finance_changes']"
    assert prepared["history_budget"] > HISTORY_CHAR_BUDGET_MIN


@pytest.mark.asyncio
async def test_a_lean_turn_is_her_prompt_and_the_last_few_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = await _built(monkeypatch, lean=True)

    assert prepared["memory_context"] is None
    assert prepared["readings"] == []
    assert not prepared["agent_modules_context"]
    assert prepared["history_budget"] == HISTORY_CHAR_BUDGET_MIN
