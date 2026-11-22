"""A live call with no realtime model: the app runs the chain itself.

The caller's audio is heard (``turns``: Silero, then Smart Turn), each
finished turn transcribed (``hear``), answered by a chat model, tools and
all (``brain``), and the answer said a sentence at a time as it is written
(``say``). Built as a Pydantic AI realtime model, so a call on it takes the
one path every engine takes (``realtime_calls``): the relay, the tools, the
saved turns and the bill are the same as on Gemini Live.

It keeps the call's history itself, as a chat model reads it: the
session's own records speech as realtime parts, and this has to answer the
moment a turn ends, before the session has read the transcript.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine, Sequence
from contextlib import asynccontextmanager, suppress
import re
import time
from typing import Any

from pydantic_ai.messages import (
    BinaryAudio,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    PartDeltaEvent,
    PartStartEvent,
    RealtimeInputSpeechEndEvent,
    RealtimeInputSpeechStartEvent,
    RealtimeResponseInterruptedEvent,
    TextPart,
    TextPartDelta,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.realtime import RealtimeModel
from pydantic_ai.realtime.codec import (
    AudioDelta,
    CancelResponse,
    CreateResponse,
    InputTranscript,
    OutputTranscript,
    RealtimeCodecEvent,
    RealtimeConnection,
    RealtimeInput,
    ResponseDone,
    SessionUsage,
    TextContext,
    ToolCall,
    ToolResult,
)
from pydantic_ai.realtime.profiles import RealtimeModelProfile

try:  # Pydantic AI 2.6x on: a connection yields frames, its lifecycle in them
    from pydantic_ai.realtime.lifecycle import InferredLifecycle
except ImportError:  # before: it yields its codec events alone
    InferredLifecycle = None

from app.core.hooks import Hook
from app.core.log import logger

from ..tts import realtime
from . import turns

SYSTEM = "cascade"
# What the call hears in (Silero and Smart Turn's rate) and says out (Kokoro's).
INPUT_RATE = turns.RATE
OUTPUT_RATE = realtime.RATE
# Where a sentence ends, as the chat's own voice splits a streamed answer.
ENDS = re.compile(r"(?<=[.!?])\s+|\n+")
# A turn of these alone is the caller thinking aloud: "Um" and "Hm." were
# each answered ("No rush, take your time") while they gathered the
# question (2026-11-22). Held, they lead the words that come next.
FILLERS = frozenset({"ah", "er", "erm", "hm", "hmm", "mm", "uh", "uhm", "um"})
# How a call opens: said at once, while the model reads the call's context
# (``CascadeConnection._open``). Fits a first call, a resumed one and one
# carried on alike.
OPENING = "Hi, I'm here. Go ahead."

# Each stage of a turn as it starts, to whoever watches the call (the
# relay: its status line and trail), and logged with how long the one
# before took. None ends a turn's stages with no answer to come. A local
# model sat on "working" for minutes with nothing to say it was reading a
# 20k-token prompt (2026-11-21).
stages = Hook("call stage")
HEARING = "Hearing you"
WARMING = "Waiting on the model's warm-up"
READING = "The model is reading the call"

Hear = Callable[[bytes], Awaitable[str]]
Say = Callable[[str], Awaitable[bytes]]


class CascadeRealtimeModel(RealtimeModel):
    """``brain`` (any chat model) on a call: ``hear`` turns a finished turn
    (PCM16 at 16 kHz) into its words, ``say`` a sentence into PCM16 at 24
    kHz, and ``ear`` makes each call's listener (``turns.Listener``). A
    ``warm`` brain reads the call's context while the opening plays: a
    local one's cache; a cloud one would bill the prompt for it."""

    def __init__(
        self,
        brain: Model,
        *,
        hear: Hear,
        say: Say,
        ear: Callable[[], turns.Listener] = turns.Listener,
        warm: bool = True,
    ) -> None:
        super().__init__(
            profile=RealtimeModelProfile(
                audio_input_sample_rate=INPUT_RATE,
                audio_output_sample_rate=OUTPUT_RATE,
                supports_interruption=True,
            )
        )
        self.brain, self._hear, self._say, self._ear = brain, hear, say, ear
        self.warm = warm

    @property
    def model_name(self) -> str:
        return self.brain.model_name

    @property
    def system(self) -> str:
        return SYSTEM

    @asynccontextmanager
    async def connect(
        self,
        *,
        messages: Sequence[ModelMessage],
        model_settings: Any,
        model_request_parameters: ModelRequestParameters,
    ) -> AsyncIterator[CascadeConnection]:
        connection = CascadeConnection(
            self,
            list(messages),
            self._merge_model_settings(model_settings),
            model_request_parameters,
        )
        try:
            yield connection
        finally:
            await connection.close()


class CascadeConnection(RealtimeConnection):
    """One call: what it has heard and said, the reply in flight, and the
    tool results it waits on before answering on."""

    def __init__(
        self,
        model: CascadeRealtimeModel,
        history: list[ModelMessage],
        settings: Any,
        parameters: ModelRequestParameters,
    ) -> None:
        self._model = model
        self._history = history
        self._settings = settings
        self._parameters = parameters
        self._instructions = next(
            (
                m.instructions
                for m in reversed(history)
                if isinstance(m, ModelRequest) and m.instructions
            ),
            None,
        )
        self._ear = model._ear()
        # What the call does; a failure ends it (``_failed``), None closes it.
        self._events: asyncio.Queue[RealtimeCodecEvent | Exception | None] = (
            asyncio.Queue()
        )
        # Which response, turn and input each event is about, worked out from
        # their order: nothing here names them (``InferredLifecycle``).
        self._lifecycle = InferredLifecycle() if InferredLifecycle else None
        self._reply: asyncio.Task[None] | None = None
        self._turns: set[asyncio.Task[None]] = set()
        self._spoken = 0  # turns heard: each one's id, start to transcript
        self._waiting: dict[str, str] = {}  # tool call id -> tool name
        self._returned: list[ToolReturnPart] = []
        self._opened = False  # the first words sent are the opening cue
        self._warming: asyncio.Task[None] | None = None
        # Words heard and not yet sent to the model (``_replied``).
        self._unasked: list[str] = []
        self._spoke = False  # the answer in flight has said something
        self._speaking = False  # the caller, between a turn's start and end
        # An answer is due: real words heard, or tool results back. It waits
        # while the caller speaks, so the next words join the question.
        self._owed = False
        self._stage: tuple[str | None, float] = (None, time.monotonic())

    @property
    def model_name(self) -> str | None:
        return self._model.model_name

    async def send(self, content: RealtimeInput) -> Any:
        """What ``content`` asks of the call, and (on a Pydantic AI that
        has lifecycles) the lifecycle events sending it settled."""
        if self._lifecycle is None:
            await self._take(content)
            return None
        with self._lifecycle.sending(content):
            await self._take(content)
        return self._lifecycle.take_pending()

    async def _take(self, content: RealtimeInput) -> None:
        if isinstance(content, BinaryAudio):
            for heard in await asyncio.to_thread(self._ear.hear, content.data):
                await self._heard(heard)
        elif isinstance(content, str):
            if self._opened:
                self._unasked.append(content)
                self._owed = True
                self._answer()
            else:  # the opening's cue: read by the warm-up, not answered
                self._opened = True
                self._asked(content)
                self._reply = self._run(self._open())
        elif isinstance(content, TextContext):
            self._asked(content.text)
        elif isinstance(content, ToolResult):
            self._tool_returned(content)
        elif isinstance(content, CancelResponse):
            await self._cut_off()
        elif isinstance(content, CreateResponse):
            self._owed = True
            self._answer()

    def frames(self) -> Any:
        """What the call does, a frame at a time (Pydantic AI 2.6x on)."""
        assert self._lifecycle is not None
        return self._lifecycle.frames(self._said())

    def __aiter__(self) -> AsyncIterator[RealtimeCodecEvent]:
        if self._lifecycle is None:
            return self._said()
        return super().__aiter__()

    async def _said(self) -> AsyncIterator[RealtimeCodecEvent]:
        while (event := await self._events.get()) is not None:
            if isinstance(event, Exception):
                raise event
            yield event

    async def close(self) -> None:
        for task in [*self._turns, *filter(None, [self._reply])]:
            task.cancel()
            # A task's failure already ended the call (``_failed``).
            with suppress(asyncio.CancelledError, Exception):
                await task
        self._events.put_nowait(None)

    # --- hearing ---------------------------------------------------------------

    async def _heard(self, heard: turns.Heard) -> None:
        if heard.kind == "start":
            self._speaking = True
            await self._cut_off()
            self._spoken += 1
            self._tell(RealtimeInputSpeechStartEvent(item_id=self._item))
            return
        self._speaking = False
        self._tell(RealtimeInputSpeechEndEvent(item_id=self._item))
        task = self._run(self._transcribed(heard.audio, self._item))
        self._turns.add(task)
        task.add_done_callback(self._turns.discard)

    @property
    def _item(self) -> str:
        return f"turn-{self._spoken}"

    async def _transcribed(self, pcm: bytes, item: str) -> None:
        self._staged(HEARING)
        words = (await self._model._hear(pcm)).strip()
        self._tell(InputTranscript(words, is_final=True, item_id=item))
        if words:
            self._unasked.append(words)
            self._owed = self._owed or not _filler(words)
        self._answer()
        if self._reply is None or self._reply.done():
            self._staged(None)  # no answer to come

    def _asked(self, words: str) -> ModelRequest:
        """Words of theirs (or a cue) into the history the model reads."""
        request = self._request(UserPromptPart(words))
        self._history.append(request)
        return request

    def _request(self, *parts: Any) -> ModelRequest:
        return ModelRequest(parts=list(parts), instructions=self._instructions)

    def _tool_returned(self, result: ToolResult) -> None:
        name = self._waiting.pop(result.tool_call_id, None)
        if name is None:
            return
        self._returned.append(
            ToolReturnPart(name, result.output, tool_call_id=result.tool_call_id)
        )
        if not self._waiting:
            self._history.append(self._request(*self._returned))
            self._returned = []
            self._owed = True
            self._answer()

    # --- answering -------------------------------------------------------------

    def _answer(self) -> None:
        """An answer owed is started, unless one is in flight, its tools'
        results are not all back (``_tool_returned``) or the caller is
        still speaking (their next words join the question)."""
        if not self._owed or self._waiting or self._speaking:
            return
        if self._reply is None or self._reply.done():
            self._owed = False
            self._reply = self._run(self._replied())

    async def _open(self) -> None:
        """The opening, said at once (``OPENING``); the model reads the
        call's context behind it, one token long, so the first question
        meets a warm cache: a local model read her prompt for minutes
        before its greeting (2026-11-21)."""
        if self._model.warm:
            warm = self._warming = self._run(self._warm([*self._history]))
            self._turns.add(warm)
            warm.add_done_callback(self._turns.discard)
        await self._say(OPENING, [])
        self._history.append(ModelResponse(parts=[TextPart(OPENING)]))
        self._tell(ResponseDone(finish_reason="stop"))

    async def _warm(self, history: list[ModelMessage]) -> None:
        brain = self._model.brain
        settings = {**(self._settings or {}), "max_tokens": 1}
        messages = brain.prepare_messages(history)
        began = time.monotonic()
        async with brain.request_stream(messages, settings, self._parameters) as stream:
            async for _ in stream:
                pass
        logger.info(f"Call: the model warmed up in {time.monotonic() - began:.1f}s")

    async def _cut_off(self) -> None:
        """The reply in flight stops where it is (the caller spoke over it).
        One that has said nothing yet is dropped unheard: the caller was not
        done, and its question joins what they say next ("Um" was answered
        while they went on, 2026-11-22). A local model's first read of the
        prompt is the warm-up's, which carries on (``_open``)."""
        reply = self._reply
        if reply is None or reply.done():
            return
        reply.cancel()
        with suppress(asyncio.CancelledError):
            await reply
        if self._spoke:
            self._tell(RealtimeResponseInterruptedEvent())
            self._tell(ResponseDone(interrupted=True))

    async def _replied(self) -> None:
        """One answer: written by the brain, said a sentence at a time as it
        comes; its tool calls handed to the session, which runs them and
        sends their results back (``_tool_returned``)."""
        said: list[str] = []
        pending = ""
        self._spoke = False
        if self._warming is not None and not self._warming.done():
            # The cache is kept once a request ends: sent beside the
            # warm-up, the question read the whole prompt again (2026-11-21).
            self._staged(WARMING)
            await asyncio.wait({self._warming})
        asked: ModelRequest | None = None
        if self._unasked:
            words = " ".join(self._unasked)
            self._unasked = []
            asked = self._asked(words)
        brain = self._model.brain
        messages = brain.prepare_messages(self._history)
        self._staged(READING)
        first = True
        try:
            async with brain.request_stream(
                messages, self._settings, self._parameters
            ) as stream:
                async for event in stream:
                    if first:
                        first = False
                        self._staged(None, tell=False)  # its first token: read
                    delta = _text_of(event)
                    if not delta:
                        continue
                    *whole, pending = ENDS.split(pending + delta)
                    for sentence in filter(str.strip, whole):
                        await self._say(sentence, said)
                if pending.strip():
                    await self._say(pending, said)
                response = stream.get()
        except asyncio.CancelledError:
            if said:
                self._history.append(ModelResponse(parts=[TextPart(" ".join(said))]))
            else:  # unheard: asked again, with what comes next
                if asked is not None:
                    self._history.remove(asked)
                    self._unasked.insert(0, words)
                self._owed = True
            raise
        self._history.append(response)
        calls = [p for p in response.parts if isinstance(p, ToolCallPart)]
        for call in calls:
            self._waiting[call.tool_call_id] = call.tool_name
            self._tell(
                ToolCall(
                    call.tool_call_id,
                    tool_name=call.tool_name,
                    args=call.args_as_json_str(),
                )
            )
        self._tell(SessionUsage(response.usage))
        self._tell(ResponseDone(finish_reason=response.finish_reason))
        self._reply = None
        self._answer()  # heard while it read

    async def _say(self, sentence: str, said: list[str]) -> None:
        text = sentence.strip()
        separator = " " if said else ""
        self._spoke = True
        self._tell(AudioDelta(await self._model._say(text)))
        self._tell(OutputTranscript(separator + text))
        said.append(text)

    def _staged(self, stage: str | None, *, tell: bool = True) -> None:
        """``stage`` starting (None: the last one over), to whoever watches
        (``stages``), and the one before it logged with how long it took."""
        was, began = self._stage
        if was is not None:
            logger.info(f"Call: {was} took {time.monotonic() - began:.1f}s")
        self._stage = (stage, time.monotonic())
        if tell:
            stages.tell(stage)

    def _tell(self, event: RealtimeCodecEvent) -> None:
        self._events.put_nowait(event)

    def _run(self, work: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
        """``work`` beside the call; a failure ends the call with its error,
        where nothing read it before and the call sat silent (2026-11-21)."""
        task = asyncio.create_task(work)
        task.add_done_callback(self._failed)
        return task

    def _failed(self, task: asyncio.Task[None]) -> None:
        if not task.cancelled() and (error := task.exception()):
            self._events.put_nowait(error if isinstance(error, Exception) else None)


def _filler(words: str) -> bool:
    """Only sounds of thinking ("Um", "Hm."), no words (``FILLERS``)."""
    return set(re.findall(r"[a-z]+", words.lower())) <= FILLERS


def _text_of(event: Any) -> str:
    """The answer's words an event of the stream adds, if any."""
    if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
        return event.part.content
    if isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
        return event.delta.content_delta
    return ""
