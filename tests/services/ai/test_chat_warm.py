"""The chat's opening, read into a local model ahead of the first question
(``chat.warm``)."""

from types import SimpleNamespace
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage
import pytest

from app.services.ai.domains.chat import warm
from app.services.ai.models import AIProvider

MODEL = "inkling:q4"


class Engine:
    """llama.cpp, holding the model in memory or not; what it was asked."""

    def __init__(self, loaded: bool) -> None:
        self.loaded = loaded
        self.asked: list[tuple[str, str, str]] = []

    async def waiting_reason(self, model: str) -> str:
        return "thinking" if self.loaded else "loading"

    async def slot(self, action: str, model: str, filename: str) -> None:
        self.asked.append((action, model, filename))


def _ai(
    monkeypatch: pytest.MonkeyPatch, *, cached: int, provider: str, engine: Any
) -> tuple[Any, list[dict[str, Any]]]:
    """A service whose turn's agent answers one token, having read 36,000
    tokens of which ``cached`` were in the cache; the settings it was sent."""
    sent: list[dict[str, Any]] = []

    def reply(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        sent.append(dict(info.model_settings or {}))
        usage = RequestUsage(input_tokens=36_000, cache_read_tokens=cached)
        return ModelResponse(parts=[TextPart("I")], usage=usage)

    async def build_turn(conversation: Any, config: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(
            agent=Agent(FunctionModel(reply)), conversation_context="Hello."
        )

    async def held(*args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(model_id=None)

    monkeypatch.setattr("app.services.ai.service.chat.held_agent", held)
    monkeypatch.setattr(warm, "_engine", lambda provider: engine)
    config = SimpleNamespace(provider=provider, model=MODEL)
    return SimpleNamespace(config=config, _build_turn=build_turn), sent


async def test_a_freshly_loaded_model_gets_the_saved_read_then_keeps_a_new_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = Engine(loaded=False)
    ai, sent = _ai(monkeypatch, cached=0, provider=AIProvider.LLAMACPP, engine=engine)

    assert await warm.warm_chat(ai, "finance-assistant", "0") == 36_000
    assert engine.asked == [
        ("restore", MODEL, "inkling_q4.bin"),
        ("save", MODEL, "inkling_q4.bin"),
    ]
    # One model call, one token long, on the slot that is saved.
    assert sent == [{"max_tokens": 1, "extra_body": {"id_slot": 0}}]


async def test_a_model_in_memory_keeps_its_cache_and_a_warm_read_is_not_saved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Its slot may hold a conversation past the opening: not replaced."""
    engine = Engine(loaded=True)
    ai, _ = _ai(monkeypatch, cached=35_990, provider=AIProvider.LLAMACPP, engine=engine)

    assert await warm.warm_chat(ai, "finance-assistant", "0") == 10
    assert engine.asked == []


async def test_a_hosted_model_is_not_warmed(monkeypatch: pytest.MonkeyPatch) -> None:
    ai, sent = _ai(monkeypatch, cached=0, provider=AIProvider.OPENAI, engine=None)

    assert await warm.warm_chat(ai, "finance-assistant", "0") is None
    assert sent == []
