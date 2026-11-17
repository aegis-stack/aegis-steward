"""``AIService``, composed from one mixin per concern, chained so each
layer may call the ones beneath it:

    AIServiceBase        state: settings, config, conversation manager
      └─ UsageMixin      token extraction, pricing, usage rollups
         └─ ContextsMixin   empty: RAG's retrieval, when installed
            └─ PromptMixin    persona overlay + per-request runtime construction
               └─ TurnMixin      the agent for a turn, typed or spoken
                  └─ ChatMixin      a turn's conversation setup and teardown
                     └─ StreamingMixin  the turn: stream_chat, and chat run to its end
                        └─ VoiceMixin     STT -> chat -> TTS
    StatusMixin          conversations, status, validation (base only)

The composition below is the whole class - it declares no methods of its
own. Callers import it from the facade: ``from app.services.ai.service
import AIService``.
"""

from app.services.ai.service.status import StatusMixin
from app.services.ai.service.voice import VoiceMixin


class AIService(VoiceMixin, StatusMixin):
    """
    Core AI service for chat functionality.

    Handles chat completions, conversation management, and provider abstraction.
    """
