"""The chat turn: ``stream_chat()`` yields ``StreamingMessage`` chunks as
the model produces them, with usage captured after the stream drains;
``chat()`` runs the same turn to its end and returns the reply. One turn
however it is asked for, so an announcement or an API call keeps the
steps it took and their cost as the chat page does.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
import uuid

from pydantic_ai.exceptions import ModelRetry, UnexpectedModelBehavior
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ThinkingPart,
)
from pydantic_ai.run import AgentRunResultEvent

from app.core.concurrency import interleave
from app.core.log import logger
from app.services.ai.domains.chat.agent_loader import sandboxed_tools
from app.services.ai.domains.chat.attachments import (
    ChatAttachment,
    LiftedTurn,
    build_user_content,
)
from app.services.ai.domains.chat.cards import attach_cards, card_stage
from app.services.ai.domains.chat.readings import (
    merge_staged_readings,
    reading_stage,
)
from app.services.ai.domains.chat.user_memory import memory_user
from app.services.ai.domains.llm.providers import ProviderNotInstalledError
from app.services.ai.domains.spend.recording import chat_action
from app.services.ai.models import (
    ConversationMessage,
    MessageRole,
    StreamingConversation,
    StreamingMessage,
)
from app.services.ai.service.base import (
    AIServiceError,
    ProviderError,
)
from app.services.ai.service.chat import ChatMixin, reply_metadata
from app.services.ai.service.trace import (
    Heard,
    record_tool_call,
    record_tool_result,
    script_reads,
    thinking_notice,
    tool_notice,
)


class StreamingMixin(ChatMixin):
    """The chat turn, streamed or run to its end."""

    async def chat(
        self,
        message: str,
        conversation_id: str | None = None,
        user_id: str = "default",
        owner_user_id: int | None = None,
        admin: bool | None = None,
        agent_slug: str | None = None,
        surface: str | None = None,
        attachments: list[ChatAttachment] | None = None,
        subject: str | None = None,
        instructions: str | None = None,
        hand_over: bool = True,
        lifted: LiftedTurn | None = None,
    ) -> ConversationMessage:
        """``stream_chat`` run to its end: the reply, with the steps it
        took, its model and its cost, as the streamed turn keeps them;
        ``AIServiceError`` if the turn ends with no reply."""
        final: StreamingMessage | None = None
        async for frame in self.stream_chat(
            message,
            conversation_id=conversation_id,
            user_id=user_id,
            owner_user_id=owner_user_id,
            admin=admin,
            agent_slug=agent_slug,
            surface=surface,
            attachments=attachments,
            subject=subject,
            instructions=instructions,
            hand_over=hand_over,
            lifted=lifted,
        ):
            if frame.is_final:
                final = frame
        if final is None or final.message_id is None:
            raise AIServiceError("The turn ended without a reply.")
        return ConversationMessage(
            id=final.message_id,
            role=MessageRole.ASSISTANT,
            content=final.content,
            timestamp=final.timestamp,
            metadata=final.metadata,
        )

    async def stream_chat(
        self,
        message: str,
        conversation_id: str | None = None,
        user_id: str = "default",
        owner_user_id: int | None = None,
        admin: bool | None = None,
        stream_delta: bool = False,
        agent_slug: str | None = None,
        surface: str | None = None,
        attachments: list[ChatAttachment] | None = None,
        subject: str | None = None,
        instructions: str | None = None,
        hand_over: bool = True,
        lifted: LiftedTurn | None = None,
    ) -> AsyncIterator[StreamingMessage]:
        """Stream a chat message with real-time response generation.

        Args:
            message: The user's message
            conversation_id: Optional conversation ID (creates new if None)
            user_id: User identifier for conversation ownership
            owner_user_id: The turn's owner (``current_owner_user_id``)
            stream_delta: Whether to stream delta changes or full content
            agent_slug: Agent row to speak as (None = the default agent)
            surface: Originating chat surface, recorded on new
                conversations so each embedded chat lists only its own
                history
            instructions: This turn's manners (a meeting's), over its prompt
            hand_over: Whether naming ``agent_slug`` hands the conversation
                to it (``held_agent``); a live call's look does not
            lifted: The turn its way in lifted before it (``lift_turn``),
                in a session of its own: none is held across the answer

        Yields:
            StreamingMessage: Real-time message chunks

        Raises:
            AIServiceError: If service is disabled or not configured
            ProviderError: If AI provider fails
            ConversationError: If conversation management fails
        """
        if not self.config.enabled:
            raise AIServiceError("AI service is disabled")

        try:
            current = self.config
            setup = await self._assemble_turn(
                message,
                conversation_id=conversation_id,
                user_id=user_id,
                agent_slug=agent_slug,
                surface=surface,
                attachments=attachments,
                subject=subject,
                owner_user_id=owner_user_id,
                admin=admin,
                instructions=instructions,
                hand_over=hand_over,
                lifted=lifted,
            )
            conversation = setup.conversation
            agent_config = setup.agent_config  # usage is attributed to the agent

            streaming_conv = StreamingConversation(conversation=conversation)
            streaming_conv.reset_stream()
            agent, conversation_context = setup.agent, setup.conversation_context

            start_time = datetime.now(UTC)

            message_id = str(uuid.uuid4())

            # Turn state the bookkeeping after the stream reads, whichever
            # framework produced the stream. Pydantic AI fills all of it
            # from its event stream; LangChain streams text deltas (no tool
            # events) and token counts only where its provider reports them.

            stream_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}

            tool_trace: list[dict[str, Any]] = []
            # Why the model stopped; "length" is max_tokens cutting it off.
            finish_reason: str | None = None

            # Event-based streaming: unlike ``run_stream`` (which treats the
            # first text output as THE answer and stops), the event stream
            # crosses tool boundaries, so a model that narrates before
            # calling a tool - "let me pull that together" then run_code -
            # streams its preamble, runs the tool, and keeps talking.
            # The turn's user rides a ContextVar for the whole stream:
            # a memory write lands mid-stream, inside a tool call, and
            # has no other way to know whose fact it is.

            with (
                memory_user(
                    user_id,
                    owner_user_id=owner_user_id,
                    # The agent the turn resolved to: a follow-up naming none
                    # still acts as the one the conversation is held with.
                    agent_slug=setup.agent_config.slug,
                    conversation_id=conversation.id,
                    subject=subject,
                    admin=admin,
                ),
                reading_stage() as staged_readings,
                card_stage() as drawn_cards,
                script_reads(sandboxed_tools(agent_config)) as reads,
            ):
                async with agent.run_stream_events(
                    build_user_content(conversation_context, attachments)
                ) as events:
                    async for event in interleave(events, reads):
                        text_chunk = ""
                        if isinstance(event, Heard):
                            # A read the running script made, as it starts.
                            yield tool_notice(
                                event.name,
                                args=event.args,
                                message_id=message_id,
                                conversation_id=conversation.id,
                                stream_delta=stream_delta,
                                inside=True,
                            )
                            continue
                        if isinstance(event, PartStartEvent) and isinstance(
                            event.part, ThinkingPart
                        ):
                            yield thinking_notice(
                                message_id=message_id,
                                conversation_id=conversation.id,
                                stream_delta=stream_delta,
                            )
                            continue
                        if isinstance(event, PartStartEvent) and isinstance(
                            event.part, TextPart
                        ):
                            text_chunk = event.part.content
                        elif isinstance(event, PartDeltaEvent) and isinstance(
                            event.delta, TextPartDelta
                        ):
                            text_chunk = event.delta.content_delta
                        elif isinstance(event, FunctionToolCallEvent):
                            # Text streamed before a tool call is running
                            # commentary ("let me check..."), not the answer.
                            # Reset accumulation so the saved message and final
                            # chunk carry only what follows the last tool call,
                            # and notify the UI which tool is running.
                            streaming_conv.accumulated_content = ""
                            record_tool_call(tool_trace, event)
                            yield tool_notice(
                                event.part.tool_name,
                                args=event.part.args,
                                message_id=message_id,
                                conversation_id=conversation.id,
                                stream_delta=stream_delta,
                            )
                            continue
                        elif isinstance(event, FunctionToolResultEvent):
                            # A completing run_code call keeps its sandbox-
                            # dispatched calls (the trail showed each live).
                            finished = record_tool_result(tool_trace, event)
                            # Cards a script drew ride that script's entry.
                            attach_cards(finished, drawn_cards)
                            continue
                        elif isinstance(event, AgentRunResultEvent):
                            finish_reason = getattr(
                                getattr(event.result, "response", None),
                                "finish_reason",
                                None,
                            )
                            # The shared extractor: cache-read and
                            # cache-write tokens ride along for pricing.
                            stream_usage = self._extract_usage(event.result)

                        if not text_chunk:
                            continue

                        # Accumulate content
                        total_content = streaming_conv.accumulate_content(
                            text_chunk, is_delta=True
                        )

                        # Yield streaming message chunk
                        yield StreamingMessage(
                            content=text_chunk if stream_delta else total_content,
                            is_final=False,
                            is_delta=stream_delta,
                            message_id=message_id,
                            conversation_id=conversation.id,
                            metadata={
                                "provider": current.provider,
                                "model": current.model,
                                "stream_delta": stream_delta,
                            },
                        )

            end_time = datetime.now(UTC)
            response_time_ms = (end_time - start_time).total_seconds() * 1000

            # Add final message to conversation using accumulated streaming content
            final_content = streaming_conv.accumulated_content or "No content received"
            ai_message = conversation.add_message(
                MessageRole.ASSISTANT, final_content, message_id=message_id
            )

            # Store conversation metadata
            ai_message.metadata["conversation_id"] = conversation.id
            if tool_trace:
                # Persisted with the message, so a conversation reopened
                # from history can still expand what each run did.
                ai_message.metadata["tool_trace"] = tool_trace

            # The model that answered: an agent's pin, else the global. It
            # is what the turn is priced at and what the message reports.
            answered_by = agent_config.model_id or current.model
            # One price lookup: the ledger row's cost is the message's.
            cost = await self._record_usage(
                chat_action(agent_config.slug),
                stream_usage,
                user_id,
                duration_ms=response_time_ms,
                conversation_id=conversation.id,
                model=answered_by,
            )
            # Extractions recorded mid-run outlive the image AND the
            # thread: they belong to the user, so a new conversation
            # opens still holding them.
            await merge_staged_readings(
                user_id, staged_readings, legacy=conversation.metadata.get("readings")
            )
            final_metadata = await reply_metadata(
                conversation.id,
                provider=current.provider,
                model=answered_by,
                response_time_ms=response_time_ms,
                tool_trace=tool_trace,
                finish_reason=finish_reason,
                usage=stream_usage,
                cost=cost,
                agent_config=agent_config,
            )
            # What the final frame reports is what the message keeps, so a
            # conversation reopened from history shows the same model and
            # cost the live turn did.
            ai_message.metadata.update(final_metadata)

            # Finalize conversation (update metadata and save)
            await self._finalize_conversation(conversation, response_time_ms)

            yield StreamingMessage(
                content=final_content,
                is_final=True,
                is_delta=False,
                message_id=message_id,
                conversation_id=conversation.id,
                metadata=final_metadata,
            )

        except (ModelRetry, UnexpectedModelBehavior) as e:
            error_msg = f"AI provider streaming error: {e}"
            logger.error(error_msg)
            raise ProviderError(error_msg) from e

        except ProviderNotInstalledError:
            # Re-raise without wrapping - CLI will handle display
            raise
        except AIServiceError:
            # ConversationError and friends carry meaning for callers (the
            # API router maps them to distinct status codes); wrapping them
            # would collapse that distinction.
            raise
        except Exception as e:
            error_msg = f"Streaming failed: {e}"
            logger.exception(error_msg)
            raise AIServiceError(error_msg) from e
