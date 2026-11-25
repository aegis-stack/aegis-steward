"""Where a turn's time went: the engine reading its prompt, the model
thinking and writing, the tools it ran. A cold local model read its prompt
for 319s and thought for 4s (2026-11-23), and only the total was kept."""

from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
)

from app.services.ai.domains.llm.timing import TurnClock


def test_each_stretch_of_a_turn_is_its_phase() -> None:
    """Reading until the first token of each request, thinking until the
    answer or a call starts, writing until its calls run, the tools until
    the last one is back, then reading their results."""
    now = iter([0.0, 61.0, 65.0, 70.0, 77.0, 80.0, 85.0])
    clock = TurnClock(clock=lambda: next(now))
    call = ToolCallPart(tool_name="ledger", args="{}", tool_call_id="c1")

    for event in (
        PartStartEvent(index=0, part=ThinkingPart(content="")),  # 61
        PartStartEvent(index=1, part=TextPart(content="Let me")),  # 65
        PartDeltaEvent(index=1, delta=TextPartDelta(content_delta=" look.")),
        FunctionToolCallEvent(part=call),  # 70
        FunctionToolResultEvent(
            part=ToolReturnPart(tool_name="ledger", content="{}", tool_call_id="c1")
        ),  # 77
        PartStartEvent(index=0, part=TextPart(content="You spent")),  # 80
    ):
        clock.observe(event)

    assert clock.spent() == {  # ends at 85
        "read_ms": 64_000,
        "think_ms": 4_000,
        "write_ms": 10_000,
        "tools_ms": 7_000,
    }


def test_the_tools_run_until_the_last_is_back() -> None:
    """Calls run at once: the model reads only once every result is in."""
    now = iter([0.0, 1.0, 1.0, 9.0, 10.0])  # back("a") changes nothing
    clock = TurnClock(clock=lambda: next(now))

    def called(i: str) -> FunctionToolCallEvent:
        return FunctionToolCallEvent(
            part=ToolCallPart(tool_name="ledger", args="{}", tool_call_id=i)
        )

    def back(i: str) -> FunctionToolResultEvent:
        return FunctionToolResultEvent(
            part=ToolReturnPart(tool_name="ledger", content="{}", tool_call_id=i)
        )

    for event in (called("a"), called("b"), back("a"), back("b")):
        clock.observe(event)

    assert clock.spent() == {
        "read_ms": 2_000,
        "think_ms": 0,
        "write_ms": 0,
        "tools_ms": 8_000,
    }
