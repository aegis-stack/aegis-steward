"""What a live call runs on, laid out as the parts it is made of, for the
voice dialog (``chat_voices``).

Two ways a call can run, picked first: one model that hears and speaks by
itself (a realtime model), or a chain, hear then think then speak (any
chat model that calls tools, local or cloud, between the active voice's
STT and TTS: ``cascade``). A chain
shows its three parts, each opening its own list below: Hears is the
voice's hearing model, Thinks the model calls run on, Speaks the voice.
A line under them says where the call runs, what it costs and how long a
caller waits (``call_setup``). Every list is searched in one box: the
Thinks list holds every tool-calling model of every vendor with a key. The mode is the model's, not stored: picking
one of the other kind switches it.
"""

from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

from app.components.web_frontend import chat_models as models
from app.core.model_picker import filter_models, is_local_model, newest_first

ONE, CHAIN = "one", "chain"
MODES = {ONE: "One model hears and speaks", CHAIN: "Hear → think → speak"}
HEARS, THINKS, SPEAKS = "hears", "thinks", "speaks"
SLOTS = {HEARS: "Hears", THINKS: "Thinks", SPEAKS: "Speaks"}
# What a row or a part shows of where it runs.
LOCAL = {"label": "Local", "tone": "ok"}
CLOUD = {"label": "Cloud", "tone": "warn"}
PICK = "Pick a model below"  # a part with no model yet
NO_MATCH = "No models match."
NO_LIVE = (
    "No live model can be reached: a call needs an OpenAI or Google key "
    "with a realtime model in the catalog."
)
NO_THINKER = (
    "No model here can call tools: add a cloud provider's key, or load a "
    "local model in the inference engine and sync the catalog "
    "(llm sync --source local)."
)


def where(local: bool) -> dict[str, str]:
    return LOCAL if local else CLOUD


def address(path: str, mode: str, slot: str | None = None) -> str:
    """The dialog opened on ``mode`` (and a chain's ``slot``)."""
    return f"{path}?{urlencode({'mode': mode, **({'slot': slot} if slot else {})})}"


async def view(
    db: Any,
    path: str,
    *,
    voice: Any | None,
    calling: Any | None,
    mode: str | None = None,
    slot: str | None = None,
    query: str = "",
) -> dict[str, Any]:
    """The dialog's call setup: the mode shown (``mode``, else the kind of
    model calls run on), its parts with the open one's list (narrowed to
    ``query``), and the line that sums them up. ``calling`` is the model calls run on, ``voice`` the
    active profile."""
    from app.core.config import settings
    from app.services.ai.service import (
        call_setup,
        get_stt_models,
        get_stt_providers,
        get_tts_models,
        get_tts_providers,
        live_engines,
        realtime_calls,
    )

    live = newest_first(await models.call_models())
    on = next((m for m in live if calling and m["model_id"] == calling.model_id), None)
    mode = mode if mode in MODES else (CHAIN if on and on["kind"] == "cascade" else ONE)
    kind = "realtime" if mode == ONE else "cascade"
    shown = on if on and on["kind"] == kind else None
    wait = await live_engines.first_word_ms(db, shown["model_id"]) if shown else None
    # The one in use leads: the list is long, and it is what you check.
    live.sort(key=lambda m: m is not on)
    icons = await models.vendor_icons(live)
    rows = [
        models.picker_row(
            m,
            under_vendor=None,
            icons=icons,
            badges=[where(is_local_model(m))],
            priced=m["kind"] == "realtime",
        )
        for m in live
        if m["kind"] == kind
    ]
    modes = [
        {"label": label, "url": address(path, key), "active": key == mode}
        for key, label in MODES.items()
    ]
    if mode == ONE:
        voice_id = getattr(voice, "tts_voice", None)
        said = (
            realtime_calls.call_voice(
                f"{shown['vendor']}:{shown['model_id']}", voice_id
            )
            if shown
            else None
        )
        one = {
            "label": "Hears, thinks and speaks",
            "name": shown["title"] if shown else PICK,
            "badges": [CLOUD] if shown else [],
            "note": (f"speaks as {said}" if said else "speaks in its own voice")
            if shown
            else "",
        }
        return {
            "mode": mode,
            "modes": modes,
            "parts": [{**one, "key": ONE, "url": address(path, ONE), "open": True}],
            "summary": await call_setup.one_summary(
                shown["model_id"], shown["vendor"], wait_ms=wait
            )
            if shown
            else None,
            **_listed(rows, query, NO_LIVE),
            "search": {"mode": mode},
            "post": f"{path}/calls",
            "current": shown["model_id"] if shown else None,
            "mark": "data-call-model",
            "list": None,
        }
    slot = slot if slot in SLOTS else THINKS
    heard = call_setup.hears(voice, settings)
    spoken = call_setup.speaks(voice, settings)
    thinks = {
        "name": shown["title"] if shown else PICK,
        "badges": [where(is_local_model(shown))] if shown else [],
        "note": "",
    }
    parts = {
        HEARS: {"name": heard.name, "badges": [where(heard.local)], "note": ""},
        THINKS: thinks,
        SPEAKS: {
            "name": spoken.name,
            "badges": [where(spoken.local)],
            "note": spoken.note,
        },
    }
    # Each part's list: its rows, where a pick posts, the mark a row
    # carries, and the one in use. Speaks keeps the voices below its list.
    # Only the open one is built: a server of its is asked once whether it
    # answers (``_unanswered``).
    out = await _unanswered(slot)
    lists: dict[
        str, Callable[[], tuple[list[dict[str, Any]], str, str, str | None]]
    ] = {
        HEARS: lambda: (
            _rows(get_stt_models, get_stt_providers, out=out),
            "hears",
            "data-hear-model",
            heard.model,
        ),
        THINKS: lambda: (
            rows,
            "calls",
            "data-call-model",
            shown["model_id"] if shown else None,
        ),
        SPEAKS: lambda: (
            _rows(get_tts_models, get_tts_providers, out=out),
            "speaks",
            "data-speak-model",
            spoken.model,
        ),
    }
    listed, posts, mark, current = lists[slot]()
    return {
        "mode": mode,
        "modes": modes,
        "parts": [
            {
                **parts[key],
                "key": key,
                "label": label,
                "url": address(path, CHAIN, key),
                "open": key == slot,
            }
            for key, label in SLOTS.items()
        ],
        "summary": await call_setup.chain_summary(
            voice, settings, thinks_local=is_local_model(shown), wait_ms=wait
        )
        if shown
        else None,
        **_listed(listed, query, NO_THINKER),
        "search": {"mode": mode, "slot": slot},
        "post": f"{path}/{posts}",
        "mark": mark,
        "current": current,
        "list": slot,
    }


def _listed(rows: list[dict[str, Any]], query: str, empty: str) -> dict[str, Any]:
    """A list's rows narrowed to ``query``, and what it says when none are
    left: why there are none, or that none match."""
    query = query.strip()
    return {
        "rows": filter_models(rows, query),
        "query": query,
        "empty": NO_MATCH if query and rows else empty,
    }


async def _unanswered(slot: str) -> set[str]:
    """A server of yours on the list shown (Hears, Speaks) while it does
    not answer: Kokoro-FastAPI was picked while it was not running, and
    the call ended on its first line (2026-11-21)."""
    from app.core import speech_server
    from app.core.config import settings
    from app.services.ai.service import STTProvider, TTSProvider, server_url

    served = {HEARS: STTProvider.HEARING_SERVER, SPEAKS: TTSProvider.LOCAL_SERVER}
    provider = served.get(slot)
    if provider is None:
        return set()
    url = server_url(provider, settings)
    return set() if url and await speech_server.answers(url) else {provider.value}


def _rows(
    models: Callable[[], list[Any]],
    providers: Callable[[], list[Any]],
    out: set[str] | None = None,
) -> list[dict[str, Any]]:
    """A part's models that can run here, as rows: one whose packages are
    missing is left out (``uninstalled``): Parakeet was picked without
    them, and the call's hearing failed on every turn (2026-11-21); so is
    one whose provider is ``out`` (a server not answering)."""
    from app.services.ai.service import uninstalled

    local = {p.id for p in providers() if p.is_local}
    return [
        {
            "model_id": m.id,
            "title": m.name,
            "facts": "",
            "icon_name": None,
            "icon_url": None,
            "badges": [where(m.provider_id in local)],
        }
        for m in models()
        if not uninstalled(m.provider_id) and m.provider_id not in (out or set())
    ]
