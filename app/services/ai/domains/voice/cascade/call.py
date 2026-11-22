"""A chain call built for its model (``connection``): the chat model it
thinks with, hearing and speaking in the voice profile's own STT and TTS."""

from __future__ import annotations

import io
from typing import Any
import wave

from app.services.ai.models.provider_names import LOCAL_PROVIDERS
from app.services.ai.models.providers import AIProvider

from ..live_engines import split_model
from ..models import AudioFormat, AudioInput, SpeechRequest
from ..tts import realtime
from .connection import INPUT_RATE, OUTPUT_RATE, CascadeRealtimeModel


def local(model: str) -> bool:
    """Whether ``model`` (a Pydantic AI model string) runs on this machine:
    its prompt is minutes of prefill, so it reads a lean turn and is warmed
    before the first question."""
    return split_model(model)[0] in LOCAL_PROVIDERS


async def for_call(ai: Any, model: str, *, user_id: str | None) -> CascadeRealtimeModel:
    """The cascade on ``model`` ("llamacpp:<id>", "anthropic:<id>"), hearing
    and speaking in the voice profile's own STT and TTS (``ai.stt``,
    ``ai.tts``), what they spend recorded against the caller (``user_id``)."""
    from app.core.config import settings
    from app.services.ai.domains.llm import providers
    from app.services.ai.domains.llm.config import AIServiceConfig

    provider, name = split_model(model)
    config = AIServiceConfig(provider=AIProvider(provider), model=name)
    brain, _ = await providers.model_for(config, settings)

    async def hear(pcm: bytes) -> str:
        audio = AudioInput(
            content=realtime.wav(pcm, INPUT_RATE),
            format=AudioFormat.WAV,
            sample_rate=INPUT_RATE,
        )
        return (await ai.stt.transcribe(audio, user_id=user_id)).text

    async def say(sentence: str) -> bytes:
        line = SpeechRequest(text=sentence, format=AudioFormat.WAV)
        return pcm_at(OUTPUT_RATE, (await ai.tts.synthesize(line, user_id)).audio)

    return CascadeRealtimeModel(brain, hear=hear, say=say, warm=local(model))


def pcm_at(rate: int, audio: bytes) -> bytes:
    """A mono WAV's sound as PCM16 at ``rate``, resampled when it is not."""
    with wave.open(io.BytesIO(audio)) as w:
        pcm, at = w.readframes(w.getnframes()), w.getframerate()
    if at == rate:
        return pcm
    import numpy as np

    samples = np.frombuffer(pcm, "<i2").astype(np.float32)
    times = np.arange(round(len(samples) * rate / at)) * at / rate
    return np.interp(times, np.arange(len(samples)), samples).astype("<i2").tobytes()
