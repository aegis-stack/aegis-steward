"""Hearing (Parakeet) in the app's own process: no server, no key,
opt-in packages; Kokoro's voices, which a speech server of yours speaks. The models are stubbed: their files are
fetched on first use, never in a test."""

from pathlib import Path
import re
import threading

import pytest

from app.services.ai.domains.voice import get_voice, local
from app.services.ai.domains.voice.models import (
    AudioFormat,
    AudioInput,
    STTProvider,
    TTSProvider,
)
from app.services.ai.domains.voice.stt import STTConfig, get_stt_provider, parakeet
from tests._voice_packages import packages_installed


def test_a_model_file_already_fetched_is_not_fetched_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "voices-v1.0.bin").write_bytes(b"kept")

    url = "https://example.com/models/voices-v1.0.bin"
    assert local.fetched(url, tmp_path).read_bytes() == b"kept"


async def test_parakeet_hears_what_was_said(monkeypatch: pytest.MonkeyPatch) -> None:
    packages_installed(monkeypatch, True)
    heard = get_stt_provider(STTProvider.PARAKEET)
    assert isinstance(heard, parakeet.ParakeetProvider)
    asr = type("Asr", (), {"recognize": lambda self, s, **kw: " Hi there "})()
    monkeypatch.setattr(parakeet, "model", lambda name: asr)
    monkeypatch.setattr(parakeet, "decoded", lambda content: [0.0] * 32_000)

    result = await heard.transcribe(
        AudioInput(content=b"webm", format=AudioFormat.WEBM)
    )

    assert (result.text, result.duration_seconds) == ("Hi there", 2.0)


async def test_not_installed_each_says_how_to_install_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In the settings, and at the first call for whatever reaches the
    provider without them (a saved profile, the meetings bot)."""
    packages_installed(monkeypatch, False)
    heard = 'parakeet is not installed: uv add "onnx-asr[cpu,hub]" av'

    stt = await STTConfig(provider=STTProvider.PARAKEET).validation_errors(None)

    assert stt == [heard]
    with pytest.raises(RuntimeError, match=re.escape(heard)):
        get_stt_provider(STTProvider.PARAKEET)


def test_a_model_is_loaded_once_however_many_ask_at_once() -> None:
    """Seconds and hundreds of MB each: the meetings bot hears several
    speakers together, and each must not load its own."""
    loads: list[str] = []
    gate = threading.Event()

    def load(name: str) -> str:
        gate.wait(1)
        loads.append(name)
        return name.upper()

    model = local.loaded_once(load)
    threads = [threading.Thread(target=model, args=("tdt",)) for _ in range(4)]
    for thread in threads:
        thread.start()
    gate.set()
    for thread in threads:
        thread.join()

    assert (loads, model("tdt")) == (["tdt"], "TDT")


def test_kokoros_voices_are_listed_by_their_own_ids() -> None:
    """Kokoro speaks on Kokoro-FastAPI (``tts/server.py``), not in the app."""
    george = get_voice("local_server:bm_george")

    assert george is not None and george.provider_id == TTSProvider.LOCAL_SERVER
    assert (george.gender, george.accent) == ("male", "British")
