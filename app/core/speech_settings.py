"""Where the app reaches the inference component's servers: its engine
(``inference[<engine>]``), and a speech server (``app.core.speech_server``),
the one the component runs beside its engine (``inference[kokoro_fastapi]``)
or any set in ``.env``. Kept out of config.py's size budget; ai[voice]'s
settings build on these.
"""

from typing import TYPE_CHECKING

from pydantic_settings import BaseSettings

if TYPE_CHECKING:
    pass


class InferenceEngineSettings(BaseSettings):
    """The engine: what ``get_inference_engine`` reads and the local AI
    provider of the same name chats with."""

    INFERENCE_ENGINE: str = "ollama"


class SpeechServerSettings(InferenceEngineSettings):
    # Its OpenAI-compatible base, None for none. Docker reaches one on the
    # host at host.docker.internal; a shell on the host, at localhost.
    SPEECH_BASE_URL: str | None = "http://host.docker.internal:8880/v1"
    # The host port ``make serve`` published its container on (``.env.ports``).
    SPEECH_HOST_PORT: int | None = None
