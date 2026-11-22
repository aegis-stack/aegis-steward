"""A hearing server you run: any OpenAI-compatible transcription server at
HEARING_BASE_URL (Parakeet in Docker first), heard through OpenAI's client
as Kokoro-FastAPI is spoken through it (``tts/server.py``). Its model is
what the server names it; the call setup's Hears lists it while it answers
(lbedner/aegis-stack#2162)."""

from __future__ import annotations

from app.core import speech_server

from ..models import DEFAULT_STT_MODELS, ModelInfo, ProviderInfo, STTProvider
from .providers import OpenAIWhisperProvider

PROVIDER_ID = STTProvider.HEARING_SERVER.value

PROVIDER = ProviderInfo(
    id=PROVIDER_ID,
    name="Hearing server",
    type="stt",
    requires_api_key=False,
    is_local=True,
    description="A transcription server you run (Parakeet), at HEARING_BASE_URL",
)
MODELS = [
    ModelInfo(
        id=DEFAULT_STT_MODELS[STTProvider.HEARING_SERVER],
        name="Parakeet TDT 0.6B v3 (server)",
        provider_id=PROVIDER_ID,
        description="NVIDIA Parakeet on a hearing server of yours; 25 languages",
        supports_streaming=False,
    )
]


class ServerSTTProvider(OpenAIWhisperProvider):
    """A hearing server over OpenAI's transcription endpoint."""

    provider_type = STTProvider.HEARING_SERVER

    def __init__(self, base_url: str, model: str) -> None:
        super().__init__(api_key=speech_server.NO_KEY, model=model, base_url=base_url)
