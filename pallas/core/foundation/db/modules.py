import time
from datetime import datetime, timedelta

import pymongo
from beanie import Document
from pydantic import BaseModel, Field, PrivateAttr
from pymongo import IndexModel

DISABLED_PLUGINS_AUDIT_CAP = 500


def append_disabled_plugins_audit(
    existing: list[dict] | None,
    *,
    old_disabled: list[str],
    new_disabled: list[str],
    operator: str | int | None,
    ts: int | None = None,
) -> list[dict]:
    """对比新旧禁用列表，逐插件追加 enable/disable 审计条目并截断到上限。"""
    entries = [dict(e) for e in (existing or [])]
    now = int(ts or time.time())
    op = "" if operator is None else str(operator)
    old_set = set(old_disabled or [])
    new_set = set(new_disabled or [])
    entries.extend(
        {"plugin": name, "action": "disable", "operator": op, "ts": now} for name in sorted(new_set - old_set)
    )
    entries.extend(
        {"plugin": name, "action": "enable", "operator": op, "ts": now} for name in sorted(old_set - new_set)
    )
    if len(entries) > DISABLED_PLUGINS_AUDIT_CAP:
        entries = entries[-DISABLED_PLUGINS_AUDIT_CAP:]
    return entries


class SingProgress(BaseModel):
    complete: bool = False
    song_id: str = ""
    chunk_index: int = 0
    key: int = 0

    def __init__(self, **data):
        if "song_id" in data and isinstance(data["song_id"], int):
            data["song_id"] = str(data["song_id"])
        super().__init__(**data)


class BotConfigModule(Document):
    account: int = Field(...)
    admins: list[int] = Field(default_factory=list)
    auto_accept_friend: bool = Field(default=False)
    auto_accept_group: bool = Field(default=False)
    security: bool = Field(default=False)
    # BSON 要求 string key；读写侧统一 str(group_id)，兼容历史 int key
    taken_name: dict[str, int] = Field(default_factory=dict)
    drunk: dict[int, float] = Field(default_factory=dict)
    disabled_plugins: list[str] = Field(default_factory=list)
    disabled_plugins_audit: list[dict] = Field(default_factory=list)
    community_roster_show_qq: bool = Field(default=True)
    persona: dict | None = Field(default=None)
    group_style_enabled: bool = Field(default=True)
    plugin_storage: dict = Field(default_factory=dict)

    class Settings:
        name = "config"
        collection = "config"
        use_cache = True
        cache_expiration_time = timedelta(seconds=60)
        cache_capacity = 10000


class GroupConfigModule(Document):
    group_id: int = Field(...)
    roulette_mode: int = 1
    banned: bool = False
    sing_progress: SingProgress | None = None
    disabled_plugins: list[str] = Field(default_factory=list)
    disabled_plugins_audit: list[dict] = Field(default_factory=list)
    blocked_user_ids: list[int] = Field(default_factory=list)
    style_profile: dict | None = Field(default=None)
    plugin_storage: dict = Field(default_factory=dict)

    class Settings:
        name = "group_config"
        collection = "group_config"
        use_cache = True
        cache_expiration_time = timedelta(seconds=60)
        cache_capacity = 10000


class UserConfigModule(Document):
    user_id: int = Field(...)
    banned: bool = False
    banned_by: str = ""
    banned_at: int = 0
    maa_devices: dict = Field(default_factory=dict)
    maa_active_device: str = ""
    maa_stage_plan: list[str] = Field(default_factory=list)
    plugin_storage: dict = Field(default_factory=dict)

    class Settings:
        name = "user_config"
        collection = "user_config"


class Message(Document):
    group_id: int = Field(...)
    user_id: int = Field(...)
    bot_id: int = Field(...)
    raw_message: str = Field(...)
    is_plain_text: bool = True
    plain_text: str = Field(...)
    keywords: str = Field(...)
    sender_name: str = Field(default="")
    message_id: int | None = Field(default=None)
    reply_to_message_id: int | None = Field(default=None)
    suppressed_by_rage: bool = False
    time: int = Field(default_factory=lambda: int(time.time()))

    class Settings:
        name = "message"
        collection = "message"
        indexes = [
            IndexModel([("time", pymongo.DESCENDING)], name="time_index"),
            IndexModel(
                [("group_id", 1), ("bot_id", 1), ("message_id", 1)],
                name="uq_message_group_bot_message_id",
                unique=True,
                partialFilterExpression={"message_id": {"$type": "int"}},
            ),
        ]


class BackgroundJob(Document):
    job_id: str = Field(...)
    kind: str = Field(...)
    payload: dict = Field(default_factory=dict)
    idempotency_key: str = Field(...)
    status: str = Field(default="pending")
    attempts: int = Field(default=0)
    available_at: float = Field(default_factory=time.time)
    leased_until: float | None = Field(default=None)
    lease_owner: str | None = Field(default=None)
    lease_id: str | None = Field(default=None)
    last_error: str | None = Field(default=None)
    created_at: float = Field(default_factory=time.time)
    finished_at: float | None = Field(default=None)

    class Settings:
        name = "background_jobs"
        collection = "background_jobs"
        indexes = [
            IndexModel([("job_id", pymongo.ASCENDING)], name="job_id_unique", unique=True),
            IndexModel([("idempotency_key", pymongo.ASCENDING)], name="idempotency_unique", unique=True),
            IndexModel(
                [
                    ("status", pymongo.ASCENDING),
                    ("available_at", pymongo.ASCENDING),
                    ("leased_until", pymongo.ASCENDING),
                ],
                name="claim_index",
            ),
        ]


class Ban(BaseModel):
    keywords: str = Field(...)
    group_id: int = Field(...)
    reason: str = Field(...)
    time: int = Field(default_factory=lambda: int(time.time()))


class Answer(BaseModel):
    _topical: int = PrivateAttr(default=0)
    keywords: str = Field(...)
    group_id: int = Field(...)
    count: int = 1
    time: int = Field(default_factory=lambda: int(time.time()))
    messages: list[str] = Field(default_factory=list)


class Context(Document):
    keywords: str = Field(...)
    time: int = Field(default_factory=lambda: int(time.time()))
    trigger_count: int = Field(default=1, alias="count")
    answers: list[Answer] = Field(default_factory=list)
    ban: list[Ban] = Field(default_factory=list)
    clear_time: int = 0

    class Settings:
        name = "context"
        collection = "context"
        indexes = [
            IndexModel([("keywords", pymongo.HASHED)], name="keywords_index"),
            IndexModel([("count", pymongo.DESCENDING)], name="count_index"),
            IndexModel([("time", pymongo.DESCENDING)], name="time_index"),
            IndexModel(
                [("answers.group_id", pymongo.TEXT), ("answers.keywords", pymongo.TEXT)],
                name="answers_index",
                default_language="none",
            ),
        ]


class BlackList(Document):
    """复读机回复黑名单。

    与 ACL 黑名单（acl_rules / admin_members）是不同概念；命名同名是历史遗留。
    别名 RepeaterReplyBan 已被引入用于去除歧义，使用方建议改用别名。Mongo collection 与 PG 表
    重命名为 repeater_reply_ban 属于独立迁移工单，不在本次 ACL 任务内。
    """

    group_id: int = Field(...)
    answers: list[str] = Field(default_factory=list)
    answers_reserve: list[str] = Field(default_factory=list)

    class Settings:
        name = "blacklist"
        collection = "blacklist"
        indexes = [IndexModel([("group_id", pymongo.HASHED)], name="group_index")]


RepeaterReplyBan = BlackList


class SchemaMigration(Document):
    """启动期幂等的 schema 迁移步骤登记表；已应用的步骤不再重复执行。"""

    step: str = Field(..., unique=True)
    applied_at: int = Field(default_factory=lambda: int(time.time()))

    class Settings:
        name = "schema_migrations"
        collection = "schema_migrations"
        indexes = [IndexModel([("step", pymongo.HASHED)], name="step_index")]


class AdminMember(Document):
    """管理员身份表：与 ACL 引擎配合；ACL 表存规则、admin_members 表存身份。"""

    scope: str = Field(...)  # "bot" | "all"
    bot_id: int | None = Field(default=None)  # scope=="bot" 时必填
    user_id: int = Field(...)
    note: str | None = Field(default=None)
    created_at: int = Field(default_factory=lambda: int(time.time()))
    updated_at: int = Field(default_factory=lambda: int(time.time()))

    class Settings:
        name = "admin_members"
        collection = "admin_members"
        indexes = [
            IndexModel(
                [("scope", pymongo.ASCENDING), ("bot_id", pymongo.ASCENDING), ("user_id", pymongo.ASCENDING)],
                name="scope_bot_user_unique",
                unique=True,
            ),
        ]


class PallasACL(Document):
    """Pallas-Bot ACL 表。subject 单值字符串，role 决定前缀形态：

    - role="用户"      → subject = "u:<user_id>"
    - role="群"        → subject = "g:<group_id>"
    - role="管理员"    → subject = "*" 或 "id:<user_id>"
    - role="所有"      → subject = None
    """

    role: str = Field(...)
    subject: str | None = Field(default=None)
    action: str = Field(...)
    target_scope: str = Field(...)
    target: str = Field(...)
    effect: str = Field(...)
    priority: int = Field(default=100)
    source: str = Field(default="user")  # "user" | "system"
    created_at: int = Field(default_factory=lambda: int(time.time()))
    updated_at: int = Field(default_factory=lambda: int(time.time()))

    class Settings:
        name = "acl_rules"
        collection = "acl_rules"
        indexes = [
            IndexModel(
                [
                    ("role", pymongo.HASHED),
                    ("subject", pymongo.HASHED),
                    ("action", pymongo.HASHED),
                    ("target_scope", pymongo.HASHED),
                    ("target", pymongo.HASHED),
                ],
                name="rule_signature_unique",
            ),
            IndexModel([("action", pymongo.HASHED)], name="action_index"),
        ]


class BaseImageCache(Document):
    date: int = Field(default_factory=lambda: int(str(datetime.now().date()).replace("-", "")))

    class Settings:
        use_state_management = True
        state_management_replace_objects = True

    async def save(self, *args, **kwargs):
        self.date = int(str(datetime.now().date()).replace("-", ""))
        return await super().save(*args, **kwargs)


class ImageCache(BaseImageCache):
    cq_code: str = Field(...)
    content_hash: str | None = None
    # 原生二进制已落文件（data/image_cache_blobs），DB 只留相对路径与字节数；blob_data 仅迁移期兼容旧行。
    blob_data: bytes | None = None
    blob_path: str | None = None
    blob_size: int | None = None
    ref_times: int = 1

    class Settings(BaseImageCache.Settings):
        name = "image_cache"
        collection = "image_cache"
        indexes = [
            IndexModel([("cq_code", pymongo.HASHED)], name="cq_code_index"),
            IndexModel([("content_hash", pymongo.HASHED)], name="content_hash_index"),
        ]


class StickerLabel(Document):
    """按原始内容哈希缓存的表情语义标签。"""

    content_hash: str = Field(...)
    is_sticker: bool = Field(...)
    confidence: float = Field(...)
    prompt_version: int = Field(...)
    labeled_at: int = Field(...)
    label_json: dict = Field(...)

    class Settings:
        name = "sticker_label"
        collection = "sticker_label"
        indexes = [
            IndexModel([("content_hash", pymongo.ASCENDING)], name="content_hash_unique", unique=True),
            IndexModel([("labeled_at", pymongo.DESCENDING), ("content_hash", pymongo.ASCENDING)], name="list_index"),
        ]


class UserStickerStat(Document):
    """群成员发送图片的次数统计，按内容哈希聚合，不带 bot 维度。"""

    group_id: int = Field(...)
    user_id: int = Field(...)
    content_hash: str = Field(...)
    send_count: int = Field(default=0)
    last_sent_at: int = Field(default=0)
    updated_at: int = Field(default=0)

    class Settings:
        name = "user_sticker_stat"
        collection = "user_sticker_stat"
        indexes = [
            IndexModel(
                [("group_id", pymongo.ASCENDING), ("user_id", pymongo.ASCENDING), ("content_hash", pymongo.ASCENDING)],
                name="group_user_hash_unique",
                unique=True,
            ),
            IndexModel([("send_count", pymongo.DESCENDING)], name="send_count_index"),
        ]


class LlmChatMessage(Document):
    bot_id: int = Field(...)
    group_id: int = Field(default=0)
    user_id: int = Field(...)
    role: str = Field(...)
    content: str = Field(...)
    created_at: int = Field(default_factory=lambda: int(time.time()))

    class Settings:
        name = "llm_chat_message"
        collection = "llm_chat_message"
        indexes = [
            IndexModel(
                [
                    ("bot_id", pymongo.ASCENDING),
                    ("group_id", pymongo.ASCENDING),
                    ("created_at", pymongo.ASCENDING),
                ],
                name="bot_group_time",
            ),
            IndexModel(
                [
                    ("bot_id", pymongo.ASCENDING),
                    ("group_id", pymongo.ASCENDING),
                    ("user_id", pymongo.ASCENDING),
                    ("created_at", pymongo.ASCENDING),
                ],
                name="bot_group_user_time",
            ),
        ]


class LlmMemoryEntry(Document):
    entry_id: int = Field(...)
    bot_id: int = Field(...)
    group_id: int = Field(default=0)
    keywords: str = Field(default="")
    content: str = Field(...)
    source: str = Field(default="teach")
    importance: float = Field(default=0.5)
    confidence: float = Field(default=0.5)
    expires_at: int = Field(default=0)
    visibility: str = Field(default="private")
    embedding_json: str | None = Field(default=None)
    embedding_model: str | None = Field(default=None)
    created_at: int = Field(default_factory=lambda: int(time.time()))
    updated_at: int = Field(default_factory=lambda: int(time.time()))

    class Settings:
        name = "llm_memory_entry"
        collection = "llm_memory_entry"
        indexes = [
            IndexModel([("entry_id", pymongo.ASCENDING)], name="entry_id_unique", unique=True),
            IndexModel(
                [
                    ("bot_id", pymongo.ASCENDING),
                    ("group_id", pymongo.ASCENDING),
                    ("updated_at", pymongo.ASCENDING),
                ],
                name="bot_group_time",
            ),
        ]


class LlmRelationshipNote(Document):
    note_id: int = Field(...)
    bot_id: int = Field(...)
    group_id: int = Field(default=0)
    user_id: int = Field(...)
    content: str = Field(...)
    source: str = Field(default="teach")
    weight: float = Field(default=1.0)
    warmth_delta: float = Field(default=0.0)
    assertiveness_delta: float = Field(default=0.0)
    affinity: float = Field(default=0.0)
    rage: int = Field(default=0)
    rage_last_attack_at: int = Field(default=0)
    rage_last_attack_message_id: int = Field(default=0)
    rage_silenced_until: int = Field(default=0)
    rage_silence_reason: str = Field(default="")
    created_at: int = Field(default_factory=lambda: int(time.time()))
    updated_at: int = Field(default_factory=lambda: int(time.time()))

    class Settings:
        name = "llm_relationship_note"
        collection = "llm_relationship_note"
        indexes = [
            IndexModel([("note_id", pymongo.ASCENDING)], name="note_id_unique", unique=True),
            IndexModel(
                [
                    ("bot_id", pymongo.ASCENDING),
                    ("group_id", pymongo.ASCENDING),
                    ("user_id", pymongo.ASCENDING),
                ],
                name="scope_unique",
                unique=True,
            ),
        ]


class LlmMemoryEntity(Document):
    entity_id: int = Field(...)
    scope_key: str = Field(...)
    bot_id: int = Field(...)
    group_id: int = Field(default=0)
    name: str = Field(...)
    summary: str = Field(default="")
    tags: list[str] = Field(default_factory=list)
    kind: str = Field(default="concept")
    user_id: int | None = Field(default=None)
    source: str = Field(default="manual")
    deleted_at: int | None = Field(default=None)
    created_at: int = Field(default_factory=lambda: int(time.time()))
    updated_at: int = Field(default_factory=lambda: int(time.time()))

    class Settings:
        name = "llm_memory_entity"
        collection = "llm_memory_entity"
        indexes = [
            IndexModel([("entity_id", pymongo.ASCENDING)], name="entity_id_unique", unique=True),
            IndexModel(
                [("scope_key", pymongo.ASCENDING), ("name", pymongo.ASCENDING)],
                name="scope_name_unique",
                unique=True,
            ),
            IndexModel(
                [
                    ("bot_id", pymongo.ASCENDING),
                    ("group_id", pymongo.ASCENDING),
                    ("updated_at", pymongo.ASCENDING),
                ],
                name="bot_group_time",
            ),
        ]


class LlmMemoryEdge(Document):
    edge_id: int = Field(...)
    scope_key: str = Field(...)
    bot_id: int = Field(...)
    group_id: int = Field(default=0)
    fact: str = Field(...)
    source_entity_id: int = Field(...)
    target_entity_id: int = Field(...)
    relation_type: str = Field(default="related_to")
    weight: float = Field(default=1.0)
    mention_count: int = Field(default=1)
    episode_ids: list[str] = Field(default_factory=list)
    valid_at: int = Field(default_factory=lambda: int(time.time()))
    invalid_at: int | None = Field(default=None)
    source: str = Field(default="manual")
    created_at: int = Field(default_factory=lambda: int(time.time()))
    updated_at: int = Field(default_factory=lambda: int(time.time()))

    class Settings:
        name = "llm_memory_edge"
        collection = "llm_memory_edge"
        indexes = [
            IndexModel([("edge_id", pymongo.ASCENDING)], name="edge_id_unique", unique=True),
            IndexModel(
                [("scope_key", pymongo.ASCENDING), ("source_entity_id", pymongo.ASCENDING)],
                name="scope_source",
            ),
            IndexModel(
                [("scope_key", pymongo.ASCENDING), ("target_entity_id", pymongo.ASCENDING)],
                name="scope_target",
            ),
            IndexModel(
                [("bot_id", pymongo.ASCENDING), ("group_id", pymongo.ASCENDING)],
                name="bot_group",
            ),
        ]


class LlmMemoryCategory(Document):
    category_id: int = Field(...)
    scope_key: str = Field(...)
    bot_id: int = Field(...)
    group_id: int = Field(default=0)
    name: str = Field(...)
    summary: str = Field(default="")
    tags: list[str] = Field(default_factory=list)
    layer: int = Field(default=1)
    parent_id: int | None = Field(default=None)
    member_entity_ids: list[str] = Field(default_factory=list)
    source: str = Field(default="manual")
    deleted_at: int | None = Field(default=None)
    created_at: int = Field(default_factory=lambda: int(time.time()))
    updated_at: int = Field(default_factory=lambda: int(time.time()))

    class Settings:
        name = "llm_memory_category"
        collection = "llm_memory_category"
        indexes = [
            IndexModel([("category_id", pymongo.ASCENDING)], name="category_id_unique", unique=True),
            IndexModel(
                [
                    ("scope_key", pymongo.ASCENDING),
                    ("layer", pymongo.ASCENDING),
                    ("name", pymongo.ASCENDING),
                ],
                name="scope_layer_name_unique",
                unique=True,
            ),
            IndexModel(
                [("bot_id", pymongo.ASCENDING), ("group_id", pymongo.ASCENDING)],
                name="bot_group",
            ),
        ]


class LlmMemoryHierStatus(Document):
    scope_key: str = Field(...)
    bot_id: int = Field(...)
    group_id: int = Field(default=0)
    max_layer: int = Field(default=0)
    last_rebuild_at: int = Field(default=0)
    entity_count_at_rebuild: int = Field(default=0)
    group_summary: str = Field(default="")
    updated_at: int = Field(default_factory=lambda: int(time.time()))

    class Settings:
        name = "llm_memory_hier_status"
        collection = "llm_memory_hier_status"
        indexes = [
            IndexModel([("scope_key", pymongo.ASCENDING)], name="scope_key_unique", unique=True),
        ]


__all__ = [
    "SingProgress",
    "BotConfigModule",
    "GroupConfigModule",
    "UserConfigModule",
    "Message",
    "Ban",
    "Answer",
    "Context",
    "BlackList",
    "RepeaterReplyBan",
    "SchemaMigration",
    "AdminMember",
    "PallasACL",
    "ImageCache",
    "LlmChatMessage",
    "LlmMemoryEntry",
    "LlmRelationshipNote",
    "LlmMemoryEntity",
    "LlmMemoryEdge",
    "LlmMemoryCategory",
    "LlmMemoryHierStatus",
]
