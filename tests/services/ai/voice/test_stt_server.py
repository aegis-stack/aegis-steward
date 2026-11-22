"""A hearing server you run (``stt/server.py``): any OpenAI-compatible
transcription server at HEARING_BASE_URL (Parakeet in Docker first), the
way Kokoro-FastAPI speaks at SPEECH_BASE_URL. The server is a stub; the
real client's requests are answered in the test (lbedner/aegis-stack#2162)."""

import httpx
import pytest

from app.core import speech_server
from app.core.config import Settings
from app.services.ai.domains.voice import get_stt_models, get_stt_providers
from app.services.ai.domains.voice.models import (
    AudioFormat,
    AudioInput,
    CannotRunError,
    STTProvider,
)
from app.services.ai.domains.voice.stt import STTConfig, get_stt_provider, server
from tests._speech_server import Shell, openai_answering

URL = "http://localhost:5092/v1"


async def test_what_you_said_is_heard_by_the_server_at_its_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Asked as OpenAI's transcription endpoint is, without the app's
    OpenAI key: the server is not OpenAI."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real")
    asked = openai_answering(
        monkeypatch, lambda: httpx.Response(200, json={"text": "What is in checking?"})
    )
    heard = get_stt_provider(STTProvider.HEARING_SERVER, server_url=URL)

    result = await heard.transcribe(
        AudioInput(content=b"RIFF....WAVE", format=AudioFormat.WAV)
    )

    [request] = asked
    assert str(request.url) == f"{URL}/audio/transcriptions"
    assert b"sk-real" not in request.headers.get("authorization", "").encode()
    assert b"parakeet-tdt-0.6b-v3" in request.content
    assert result.text == "What is in checking?"


def test_it_is_refused_until_its_address_is_set() -> None:
    with pytest.raises(CannotRunError, match="HEARING_BASE_URL"):
        get_stt_provider(STTProvider.HEARING_SERVER)


def test_it_is_a_local_hearing_provider_with_its_model() -> None:
    assert server.PROVIDER in get_stt_providers()
    assert server.PROVIDER.is_local
    assert [m.id for m in get_stt_models(server.PROVIDER.id)] == [
        "parakeet-tdt-0.6b-v3"
    ]


def test_its_address_is_reached_from_the_host_as_the_speech_servers_is() -> None:
    """A shell on the host swaps a Docker name for localhost, on the port
    ``make serve`` published it on; the app in Docker keeps its name."""
    named = "http://hearing:5092/v1"  # compose's service (make serve)
    shell = Shell(HEARING_BASE_URL=named, HEARING_HOST_PORT=15092)

    assert speech_server.reach(shell, "HEARING_BASE_URL") == "http://localhost:15092/v1"
    assert speech_server.reach(Shell(), "HEARING_BASE_URL") is None
    docker = Shell(is_docker=True, HEARING_BASE_URL=named)
    assert speech_server.reach(docker, "HEARING_BASE_URL") == named


def test_the_config_carries_the_hearing_servers_address() -> None:
    told = Settings(
        STT_PROVIDER="hearing_server",
        HEARING_BASE_URL="http://host.docker.internal:5092/v1",
    )
    config = STTConfig.from_settings(told)
    assert config.server_url == speech_server.reach(told, "HEARING_BASE_URL")
    assert config.server_url is not None
