"""The live call's relay (#273): Gemini Live has no WebRTC hand-off, only
a WebSocket holding the key, so the call's audio comes through here.

Mic audio arrives as binary frames (PCM16 at the model's input rate) and
her voice goes back the same way (at its output rate); a few JSON events
tell the page what the call is doing. ``drive`` does the rest, as for a
WebRTC call: her tools, the saved turns, the priced usage. The opening,
the engine and her turns are ``chat_live``'s.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, WebSocket
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    PartEndEvent,
    PartStartEvent,
    RealtimeResponseInterruptedEvent,
    RealtimeTurnCompleteEvent,
    SpeechPart,
)

from app.components.backend.api.ai.router import sync_active_model
from app.components.web_frontend.routes import chat_live as live
from app.components.web_frontend.routes.chat import component_url
from app.core.chat_transcript import trace_label
from app.core.log import logger
from app.services.ai.service import MARKER, realtime_calls
from app.services.ai.service.trace import record_tool_call

router = APIRouter(dependencies=[Depends(sync_active_model)])


async def _tell(ws: WebSocket, event: Any) -> None:
    """What the page shows of an event, if anything."""
    said: dict[str, Any] | None = None
    if isinstance(event, RealtimeResponseInterruptedEvent):
        said = {"type": "interrupted"}  # flush what has not been played
    elif isinstance(event, FunctionToolCallEvent):
        if event.part.tool_name == realtime_calls.END_CALL:
            said = {"type": "hang_up"}  # after her goodbye has played
        else:
            step: list[dict[str, Any]] = []
            record_tool_call(step, event)
            said = {"type": "working", "label": trace_label(step[0])}
    elif isinstance(event, RealtimeTurnCompleteEvent):
        said = {"type": "done"}
    elif (
        isinstance(event, PartStartEvent)
        and isinstance(event.part, SpeechPart)
        and event.part.speaker == "user"
    ):
        # Gemini reports no speech onset; your first transcribed words are
        # it, and "heard" is the end (#458).
        said = {"type": "hearing"}
    elif isinstance(event, PartEndEvent) and isinstance(event.part, SpeechPart):
        side = "heard" if event.part.speaker == "user" else "said"
        said = {"type": side, "text": event.part.transcript or ""}
    if said:
        await _send(ws, said)


def drawn_card(card_id: str) -> dict[str, Any]:
    """What the page is told of a card she drew mid-call: where it loads,
    so a chart is up while she talks about it."""
    return {"type": "card", "url": component_url(MARKER, card_id)}


async def _show_cards(ws: WebSocket, card_ids: list[str]) -> None:
    for card_id in card_ids:
        await _send(ws, drawn_card(card_id))


async def _send(ws: WebSocket, message: dict[str, Any]) -> None:
    try:
        await ws.send_json(message)
    except Exception:  # the page hung up first
        return


async def _carry(
    ws: WebSocket, session: Any, conversation: Any, info: dict[str, Any] | None
) -> None:
    """The audio, both ways, until the page hangs up."""
    await ws.send_json(
        {
            "type": "ready",
            "input_rate": session.audio_input_sample_rate,
            "output_rate": session.audio_output_sample_rate,
            "conversation_id": conversation.id,
            "engine": info,
        }
    )

    async def speak() -> None:
        async for chunk in session.stream_audio():
            await ws.send_bytes(chunk)

    voice = asyncio.create_task(speak())
    looks: set[asyncio.Task[None]] = set()
    try:
        await session.send(live.opening(conversation))
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("bytes"):
                await session.send_audio(message["bytes"])
            elif message.get("text"):
                said = json.loads(message["text"])
                if said.get("type") == "shown":
                    # A picture: looked at beside the call, not in its way.
                    looking = asyncio.create_task(
                        _shown(ws, session, conversation.id, said.get("image"))
                    )
                    looks.add(looking)
                    looking.add_done_callback(looks.discard)
                    continue
                # The page's cue into the quiet: only lines of hers.
                line = live.LIVE_CUES.get(said.get("line"))
                if line:
                    await session.send(line)
    finally:
        voice.cancel()
        for looking in looks:
            looking.cancel()
        await session.close()


async def _shown(ws: WebSocket, session: Any, conversation_id: str, image: Any) -> None:
    """A picture up the relay: her turn on it, said by the server - the
    page sends no words of hers."""
    try:
        picture = live.Shown(image=image).image
    except ValueError:
        # Not a picture: nothing to say, but the page is waiting on it.
        await _send(ws, {"type": "looked", "cost": None})
        return
    turn = await live.turn(live.LIVE_SHOWN, conversation_id, picture)
    await session.send(turn["speak"])
    await _send(ws, {"type": "looked", "cost": turn["cost"]})


@router.websocket(live.RELAY)
async def relay(ws: WebSocket, conversation_id: str | None = None) -> None:
    """A call on a relay engine, for as long as the page holds the socket."""
    await ws.accept()
    engine, info = await live.current_engine()
    if engine is None or engine.transport != "relay":
        await ws.close(code=1008, reason="The live engine is not a relay engine.")
        return
    try:
        conversation, realtime = await live.start_call(conversation_id, engine)
    except Exception:
        logger.exception("Opening a relay call failed")
        await ws.close(code=1011)
        return
    await realtime_calls.drive(
        realtime,
        alongside=lambda session: _carry(ws, session, conversation, info),
        on_event=lambda event: _tell(ws, event),
        on_saved=lambda cost: _send(ws, {"type": "saved", "cost": cost}),
        on_drawn=lambda card_ids: _show_cards(ws, card_ids),
        **live.driving(conversation, engine),
    )
    try:
        await ws.close()
    except Exception:  # already closed by the page
        return
