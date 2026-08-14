"""Known lifecycle datasets and permanently protected database objects."""

from __future__ import annotations

from .lifecycle_models import (
    LifecycleDatasetDefinition,
    LifecycleObjectClassification,
    LifecyclePolicy,
)

GIB = 1024**3

DATASETS = {
    definition.dataset_id: definition
    for definition in (
        LifecycleDatasetDefinition(
            dataset_id="message_history",
            label="消息历史",
            objects=("message",),
            risk="high",
            default_policy=LifecyclePolicy(False, 180, 40 * GIB),
        ),
        LifecycleDatasetDefinition(
            dataset_id="repeater_context",
            label="复读上下文",
            objects=("context", "context_answer", "context_answer_message", "context_ban"),
            risk="high",
            default_policy=LifecyclePolicy(False, 180, None),
            supports_max_bytes=False,
        ),
        LifecycleDatasetDefinition(
            dataset_id="image_cache",
            label="图片缓存",
            objects=("image_cache",),
            risk="low",
            default_policy=LifecyclePolicy(True, 90, 20 * GIB),
        ),
        LifecycleDatasetDefinition(
            dataset_id="llm_chat",
            label="LLM 对话",
            objects=("llm_chat_message",),
            risk="medium",
            default_policy=LifecyclePolicy(False, 90, 10 * GIB),
        ),
        LifecycleDatasetDefinition(
            dataset_id="llm_memory",
            label="LLM 记忆",
            objects=(
                "llm_memory_category",
                "llm_memory_edge",
                "llm_memory_entity",
                "llm_memory_entry",
                "llm_memory_hier_status",
                "llm_relationship_note",
            ),
            risk="high",
            default_policy=LifecyclePolicy(False, None, None),
            supports_retention=False,
            supports_max_bytes=False,
        ),
        LifecycleDatasetDefinition(
            dataset_id="background_jobs",
            label="后台任务",
            objects=("background_job", "background_jobs"),
            risk="medium",
            default_policy=LifecyclePolicy(True, 30, 2 * GIB),
        ),
    )
}

PROTECTED_OBJECTS = frozenset({
    "acl_rules",
    "admin_members",
    "blacklist",
    "bot_config",
    "config",
    "group_config",
    "migration_state",
    "schema_migrations",
    "user_config",
})

_DATASET_BY_OBJECT = {
    object_name: dataset_id for dataset_id, definition in DATASETS.items() for object_name in definition.objects
}


def classify_object(object_name: str) -> LifecycleObjectClassification:
    name = str(object_name).strip()
    dataset_id = _DATASET_BY_OBJECT.get(name)
    if dataset_id is not None:
        return LifecycleObjectClassification(name, dataset_id, False, None)
    reason = "protected_permanent" if name in PROTECTED_OBJECTS else "protected_unknown"
    return LifecycleObjectClassification(name, None, True, reason)
