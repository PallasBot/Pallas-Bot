"""Runtime-facing LLM entrypoints for in-process chat plugins.

Chat plugins (``llm_chat``, ``repeater``) should prefer this facade for
kernel / delivery / tools imports instead of ops modules
(``model_admin``, ``providers_store``, ``webui_config``).
"""

import importlib
from typing import TYPE_CHECKING, Any

from pallas.product.llm.behavior import classify_behavior_scene
from pallas.product.llm.config import get_llm_config
from pallas.product.llm.kernel import (
    CandidateSource,
    ConversationAction,
    ConversationCandidate,
    ConversationContext,
    ConversationFeatureLevel,
    ConversationMode,
    ConversationPath,
    ConversationScene,
    DecisionConstraints,
    DecisionResult,
    DecisionTrace,
    FeedbackBiasSnapshot,
    GenerationPlan,
    GenerationStage,
    GenerationTask,
    MemoryAssetKind,
    MemoryReadPolicy,
    PromotionCandidate,
    behavior_scene_to_conversation_scene,
    build_conversation_kernel_status,
    build_repeater_generation_plan,
    can_apply_feedback_bias,
    can_collect_feedback,
    can_promote_writeback,
    can_read_behavioral_learning,
    can_read_persistent_memory,
    can_read_runtime_state,
    can_write_runtime_state_summary,
    decide_direct_chat_action,
    decide_repeater_action,
    empty_bias_snapshot,
    list_recent_conversation_traces,
    normalize_conversation_mode,
    plan_direct_chat_stages,
    plan_generation_stages,
    resolve_conversation_feature_level,
    resolve_memory_read_policy,
    runtime_state_summary_metadata,
)
from pallas.product.llm.knowledge.declare import knowledge_source_row
from pallas.product.llm.repeater_capabilities import resolve_repeater_capabilities
from pallas.product.llm.select import submit_repeater_corpus_select
from pallas.product.llm.status import build_llm_status_text
from pallas.product.llm.task_metrics import record_bot_llm_route, record_bot_llm_task
from pallas.product.llm.tools.declare import llm_command_tool_row
from pallas.product.llm.tools.startup import register_llm_tools_startup_hook

if TYPE_CHECKING:
    from pallas.product.llm.delivery import deliver_llm_callback_success, deliver_llm_chat_result

__all__ = [
    "CandidateSource",
    "ConversationAction",
    "ConversationCandidate",
    "ConversationContext",
    "ConversationFeatureLevel",
    "ConversationMode",
    "ConversationPath",
    "ConversationScene",
    "DecisionConstraints",
    "DecisionResult",
    "DecisionTrace",
    "FeedbackBiasSnapshot",
    "GenerationPlan",
    "GenerationStage",
    "GenerationTask",
    "MemoryAssetKind",
    "MemoryReadPolicy",
    "PromotionCandidate",
    "behavior_scene_to_conversation_scene",
    "build_conversation_kernel_status",
    "build_llm_status_text",
    "build_repeater_generation_plan",
    "can_apply_feedback_bias",
    "can_collect_feedback",
    "can_promote_writeback",
    "can_read_behavioral_learning",
    "can_read_persistent_memory",
    "can_read_runtime_state",
    "can_write_runtime_state_summary",
    "classify_behavior_scene",
    "decide_direct_chat_action",
    "decide_repeater_action",
    "deliver_llm_callback_success",
    "deliver_llm_chat_result",
    "empty_bias_snapshot",
    "get_llm_config",
    "knowledge_source_row",
    "list_recent_conversation_traces",
    "llm_command_tool_row",
    "normalize_conversation_mode",
    "plan_direct_chat_stages",
    "plan_generation_stages",
    "record_bot_llm_route",
    "record_bot_llm_task",
    "register_llm_tools_startup_hook",
    "resolve_conversation_feature_level",
    "resolve_memory_read_policy",
    "resolve_repeater_capabilities",
    "runtime_state_summary_metadata",
    "submit_repeater_corpus_select",
]

_LAZY_MODULES = {
    "deliver_llm_callback_success": ".delivery",
    "deliver_llm_chat_result": ".delivery",
}


def __getattr__(name: str) -> Any:
    module_path = _LAZY_MODULES.get(name)
    if module_path is not None:
        module = importlib.import_module(module_path, __name__)
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
