"""Stand-ins for a speech server of yours (Kokoro-FastAPI, the hearing
server): the settings a host shell has, and the server answering the real
OpenAI client."""

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.core.config import Settings


class Shell:
    """Settings as a shell on the host has them, with only the speech
    settings given: this ships to every stack, and only inference and
    ai[voice] carry them."""

    is_docker = False
    localhost_url = staticmethod(Settings.localhost_url)

    def __init__(self, **given: Any) -> None:
        self.__dict__.update(given)


def openai_answering(
    monkeypatch: pytest.MonkeyPatch, answer: Callable[[], httpx.Response]
) -> list[httpx.Request]:
    """Every request the OpenAI client makes answered with ``answer()``;
    returns the requests, as they come."""
    import openai

    real = openai.AsyncOpenAI
    asked: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        return answer()

    def client(**kw: Any) -> Any:
        stub = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        return real(http_client=stub, **kw)

    monkeypatch.setattr(openai, "AsyncOpenAI", client)
    return asked
