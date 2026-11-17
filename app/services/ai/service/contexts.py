"""The per-request context builder. Nothing live rides the system
prompt (``PromptMixin._system_prompt_for``).
"""

from app.services.ai.service.usage import UsageMixin


class ContextsMixin(UsageMixin):
    """The context a turn retrieves before its model call."""
