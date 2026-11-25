"""Where a turn's time went, for its reply to keep (``timing``): the engine
reading its prompt (until the first token of each model request), the model
thinking, writing (its answer and its calls), and the tools it ran.

A cold local model read its prompt for 319s and thought for 4s (2026-11-23);
only the total was kept, so a slow read looked like a slow model. One clock
over the turn's stream events, the same for every engine: Ollama's OpenAI
endpoint reports no timings of its own.
"""

from collections.abc import Callable
import time

from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartStartEvent,
    ThinkingPart,
)

READ, THINK, WRITE, TOOLS = "read_ms", "think_ms", "write_ms", "tools_ms"


class TurnClock:
    """Each stretch of a turn, by the event that starts it."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._phase = READ
        self._since = clock()
        self._running = 0  # calls not back yet
        self._spent: dict[str, float] = dict.fromkeys((READ, THINK, WRITE, TOOLS), 0.0)

    def _enter(self, phase: str) -> None:
        now = self._clock()
        self._spent[self._phase] += now - self._since
        self._phase, self._since = phase, now

    def observe(self, event: object) -> None:
        if isinstance(event, PartStartEvent):
            self._enter(THINK if isinstance(event.part, ThinkingPart) else WRITE)
        elif isinstance(event, FunctionToolCallEvent):
            self._running += 1
            self._enter(TOOLS)
        elif isinstance(event, FunctionToolResultEvent):
            self._running = max(self._running - 1, 0)
            if not self._running:
                self._enter(READ)  # the next request reads the results

    def spent(self) -> dict[str, int]:
        """Milliseconds per phase, to now."""
        self._enter(self._phase)
        return {phase: round(seconds * 1000) for phase, seconds in self._spent.items()}
