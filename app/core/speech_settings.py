"""Where the app reaches the inference component's servers: its engine
(``inference[<engine>]``), and a speech server (``app.core.speech_server``),
the one the component runs beside its engine (``inference[kokoro_fastapi]``)
or any set in ``.env``. Kept out of config.py's size budget; ai[voice]'s
settings build on these.
"""

from typing import TYPE_CHECKING, cast

from pydantic_settings import BaseSettings

if TYPE_CHECKING:
    from app.core.config import Settings


class InferenceEngineSettings(BaseSettings):
    """The engine: what ``get_inference_engine`` reads and the local AI
    provider of the same name chats with."""

    INFERENCE_ENGINE: str = "llamacpp"
    # On the host: the folder a llama-server router serves (``--models-dir``),
    # and where Ollama keeps its pulls (its own variable, and its default),
    # for ``inference link-ollama`` (``ollama_library``).
    LLAMACPP_MODELS_DIR: str = "~/models"
    OLLAMA_MODELS: str = "~/.ollama/models"
    # The context each model is served at (the compose service's too), and
    # any further llama-server flags for ``make llama``: flash attention,
    # and two requests at once sharing the context, so a background call
    # does not evict the chat's cached prompt.
    LLAMACPP_CONTEXT: int = 32768
    LLAMACPP_ARGS: str = "-fa on -np 2 -kvu"
    # The model the compose service's router downloads and loads at start
    # (a Hugging Face repo[:quant]), listed under this name.
    LLAMACPP_MODEL: str = "ggml-org/Qwen3-1.7B-GGUF"
    # The most a reply may think before it answers, in tokens (a chat turn
    # is several replies); -1 leaves it to the model, as llama-server's own.
    LLAMACPP_THINKING_TOKENS: int = 512
    LLAMACPP_BASE_URL: str = "http://host.docker.internal:8080"  # on the host
    # The host port ``make serve`` published its container on (``.env.ports``).
    LLAMACPP_HOST_PORT: int | None = None

    @property
    def llamacpp_base_url_effective(self) -> str:
        """llama-server's URL from where this runs: off Docker, the service
        or host name is ``localhost`` (``Settings.localhost_url``)."""
        settings = cast("Settings", self)  # mixed into Settings
        if settings.is_docker:
            return self.LLAMACPP_BASE_URL
        return settings.localhost_url(
            self.LLAMACPP_BASE_URL,
            {"llamacpp", "host.docker.internal"},
            self.LLAMACPP_HOST_PORT,
        )


class SpeechServerSettings(InferenceEngineSettings):
    # Its OpenAI-compatible base, None for none. Docker reaches one on the
    # host at host.docker.internal; a shell on the host, at localhost.
    SPEECH_BASE_URL: str | None = "http://host.docker.internal:8880/v1"
    # The host port ``make serve`` published its container on (``.env.ports``).
    SPEECH_HOST_PORT: int | None = None
    # A Kokoro-FastAPI checkout on the host, for ``make kokoro``.
    SPEECH_SERVER_DIR: str = "~/Kokoro-FastAPI"
    # A hearing server you run: any OpenAI-compatible transcription server,
    # as the call setup's Hears lists it. Compose runs Parakeet as
    # ``hearing``; unset, none.
    HEARING_BASE_URL: str | None = "http://hearing:5092/v1"
    # The host port ``make serve`` published it on, where it runs in Docker.
    HEARING_HOST_PORT: int | None = None
