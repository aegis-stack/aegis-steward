"""What the catalog lists for the voice that runs in the app's own process:
Parakeet hearing (``stt/parakeet.py``); speech runs on a server of yours
(``tts/server.py``). Kept out of ``catalog`` for its size; it adds these
to its lists. Also how a model in the app's process is fetched
(``fetched``) and loaded (``loaded_once``): theirs, and a cascade call's
turn detection (``cascade/turns.py``)."""

from collections.abc import Callable
from functools import cache
import logging
import os
from pathlib import Path
import tempfile
import threading
from typing import Any

import httpx

from .models import (
    DEFAULT_STT_MODELS,
    ModelInfo,
    ProviderInfo,
    STTProvider,
)

_IN_APP = "runs in the app on the CPU, no key"
logger = logging.getLogger(__name__)


def fetched(url: str, cache_dir: Path) -> Path:
    """The model file at ``url`` in ``cache_dir``, downloaded into it first
    when absent (whole into a file of its own, then moved, so a cut-off
    download, or another process fetching it too, never leaves half a
    file)."""
    path = cache_dir / url.rpartition("/")[2]
    if path.exists():
        return path
    cache_dir.mkdir(parents=True, exist_ok=True)
    fd, partial = tempfile.mkstemp(dir=cache_dir, suffix=".partial")
    logger.info(f"Fetching {url} into {cache_dir}")
    try:
        with (
            os.fdopen(fd, "wb") as out,
            httpx.stream("GET", url, follow_redirects=True, timeout=60) as response,
        ):
            response.raise_for_status()
            for chunk in response.iter_bytes(1 << 20):
                out.write(chunk)
        os.replace(partial, path)
    except BaseException:
        Path(partial).unlink(missing_ok=True)
        raise
    return path


def loaded_once(load: Callable[..., Any]) -> Callable[..., Any]:
    """``load`` run once per argument for the whole process, however many
    threads ask at once: a model is seconds and hundreds of MB to load,
    and the meetings bot hears several speakers together."""
    loaded = cache(load)
    lock = threading.Lock()

    def model(*args: str) -> Any:
        with lock:  # ponytail: per loader, so two models of one load in turn
            return loaded(*args)

    return model


STT_PROVIDER = ProviderInfo(
    id=STTProvider.PARAKEET.value,
    name="Parakeet",
    type="stt",
    requires_api_key=False,
    is_local=True,
    description=f"NVIDIA Parakeet v3, 25 languages: {_IN_APP}",
)

STT_MODELS = [
    ModelInfo(
        id=DEFAULT_STT_MODELS[STTProvider.PARAKEET],
        name="Parakeet TDT 0.6B v3",
        provider_id=STTProvider.PARAKEET.value,
        description="int8, about 670MB, fetched from Hugging Face on first use",
        supports_streaming=False,
    )
]
