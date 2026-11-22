"""AI service facade: what callers outside it import (``app.services.shared.facade``)."""

# ruff: noqa: F401

from typing import TYPE_CHECKING

from app.services.shared import facade

if TYPE_CHECKING:
    from app.services.ai.domains.chat import cards, memory_changes
    from app.services.ai.domains.chat.agent_loader import (
        CODE_MODE_TOOL_CALLS_LIMIT,
        DEFAULT_AGENT_SLUG,
        AgentConfig,
        agent_capabilities,
        resolve_agent,
    )
    from app.services.ai.domains.chat.agent_registry import (
        AgentNotFoundError,
        InvalidAgentUpdateError,
        list_agents,
        prompt_history,
        seed_agent,
        serialize_agent,
        update_agent,
    )
    from app.services.ai.domains.chat.attachments import (
        MAX_ATTACHMENTS,
        ChatAttachment,
        LiftedTurn,
        composer,
        keeps_pastes,
        lift_turn,
    )
    from app.services.ai.domains.chat.context_modules import (
        InvalidContextModuleError,
        get_context_entry,
        list_context_modules,
        module_sources,
        serialize_context_module,
        set_context_entry,
        update_context_module,
    )
    from app.services.ai.domains.chat.fetchers import FetchContext, register_fetcher
    from app.services.ai.domains.chat.module_context import render_context_modules
    from app.services.ai.domains.chat.pastes import (
        Paste,
        document_paste_id,
        document_text,
        keep_paste,
        paste_id,
        pastes_of,
        read_paste,
        read_picture,
        store_paste,
    )
    from app.services.ai.domains.chat.path_card import PathCard
    from app.services.ai.domains.chat.prompts import (
        DEFAULT_SYSTEM_PROMPT,
        build_system_prompt,
    )
    from app.services.ai.domains.chat.queries import conversation_stats
    from app.services.ai.domains.chat.sentiment import (
        SentimentMix,
        score_unscored_conversations,
        sentiment_mix,
        sentiment_stats,
    )
    from app.services.ai.domains.chat.summary import fold_conversation, write_summary
    from app.services.ai.domains.chat.tools import resolve_tools
    from app.services.ai.domains.chat.user_memory import (
        DEFAULT_MEMORY_USER_ID,
        MEMORY_CATEGORIES,
        delete_user_fact,
        list_user_facts,
        update_user_fact,
    )
    from app.services.ai.domains.llm import active_model
    from app.services.ai.domains.llm.base import ProviderError as ProviderSetupError
    from app.services.ai.domains.llm.config import get_ai_config
    from app.services.ai.domains.llm.etl import (
        CatalogStats,
        SyncResult,
        get_catalog_stats,
        sync_llm_catalog,
        sync_source,
    )
    from app.services.ai.domains.llm.etl.queries import (
        catalog_is_populated,
        local_models_present,
    )
    from app.services.ai.domains.llm.llm_service import (
        CurrentLLMConfig,
        LLMListResult,
        ModalityListResult,
        SetModelResult,
        VendorListResult,
        clear_active_model,
        get_current_config,
        get_model_info,
        list_modalities,
        list_models,
        list_vendors,
        set_active_model,
        unusable_reason,
    )
    from app.services.ai.domains.llm.provider_management import (
        PROVIDER_API_KEY_URLS,
        ProviderReadiness,
        check_provider_dependency_installed,
        get_env_var_name,
        get_existing_api_key,
        get_missing_dependency,
        get_valid_provider_names,
        install_provider_dependency,
        provider_readiness,
        update_env_file,
        usable_providers,
        validate_provider_name,
    )
    from app.services.ai.domains.llm.providers import (
        ProviderNotInstalledError,
        get_agent,
        model_for,
    )
    from app.services.ai.domains.llm.queries import (
        org_icons,
        recent_model_ids,
        usage_by_model,
    )
    from app.services.ai.domains.llm.waiting import waiting_reason
    from app.services.ai.domains.llm.writer import write, writer
    from app.services.ai.domains.spend import queries as spend_queries
    from app.services.ai.domains.spend import report as spend_report
    from app.services.ai.domains.spend.recording import (
        calculate_cost,
        chat_action,
        extract_usage,
        record_usage,
    )
    from app.services.ai.domains.spend.schemas import (
        ActionSpend,
        CallSpend,
        KindModelSpend,
        ModelSpend,
        SpendLedger,
    )
    from app.services.ai.domains.spend.windows import spend_since, spend_windows
    from app.services.ai.domains.voice import (
        AudioFormat,
        AudioInput,
        ModelInfo,
        ProviderInfo,
        SpeechRequest,
        SpeechResult,
        STTProvider,
        TTSProvider,
        TTSService,
        VoiceInfo,
        VoicePreviewRequest,
        VoiceSettingsResponse,
        call_setup,
        design,
        get_current_voice_config,
        get_stt_models,
        get_stt_providers,
        get_tts_models,
        get_tts_providers,
        get_tts_voices,
        get_voice,
        live_engines,
        profiles,
        pronunciations,
        realtime_calls,
        speaking_model,
        uninstalled,
    )
    from app.services.ai.domains.voice.cascade.connection import (
        stages as call_stages,
    )
    from app.services.ai.domains.voice.live_voice import live_voice
    from app.services.ai.domains.voice.models import server_url
    from app.services.ai.domains.voice.overview import (
        VoiceOverview,
        switch_voice,
        use_voice,
        voice_overview,
    )
    from app.services.ai.domains.voice.spoken import (
        Pronunciation,
        pronunciation_list,
        register_pronunciation,
        saved_keys,
        to_spoken,
    )
    from app.services.ai.domains.voice.tts.service import unsaid
    from app.services.ai.jobs import fold_conversation_job, read_photo_job
    from app.services.ai.models import (
        AIProvider,
        MessageRole,
        StreamingMessage,
        get_free_providers,
        get_provider_capabilities,
    )
    from app.services.ai.models.agents import (
        Agent,
        AgentPromptChange,
        AgentTool,
        ContextModule,
        Tool,
    )
    from app.services.ai.models.llm import (
        LargeLanguageModel,
        LLMDeployment,
        LLMModality,
        LLMOrg,
        LLMPrice,
    )
    from app.services.ai.models.provider_names import LOCAL_PROVIDERS, provider_label
    from app.services.ai.models.voice import (
        LiveEngine,
        VoiceProfile,
        VoicePronunciation,
    )
    from app.services.ai.service.ai_service import AIService
    from app.services.ai.service.base import (
        AIServiceError,
        ConversationError,
        ProviderError,
    )

__getattr__, __all__ = facade.lazy(__name__, __file__)
