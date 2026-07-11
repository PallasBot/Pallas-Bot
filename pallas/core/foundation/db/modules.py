import time
from datetime import datetime, timedelta

import pymongo
from beanie import Document
from pydantic import BaseModel, Field, PrivateAttr
from pymongo import IndexModel


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
    taken_name: dict[int, int] = Field(default_factory=dict)
    drunk: dict[int, float] = Field(default_factory=dict)
    disabled_plugins: list[str] = Field(default_factory=list)
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
    time: int = Field(default_factory=lambda: int(time.time()))

    class Settings:
        name = "message"
        collection = "message"
        indexes = [IndexModel([("time", pymongo.DESCENDING)], name="time_index")]


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
                [
                    ("scope", pymongo.HASHED),
                    ("bot_id", pymongo.HASHED),
                    ("user_id", pymongo.HASHED),
                ],
                name="scope_bot_user_unique",
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
    # 原生二进制 blob（PG BYTEA / Mongo Binary）。在 PG 后端通过 SQLAlchemy LargeBinary 映射；
    # 这里只声明语义类型，具体 DDL 由各 repository 的 ORM 模型负责。
    blob_data: bytes | None = None
    ref_times: int = 1

    class Settings(BaseImageCache.Settings):
        name = "image_cache"
        collection = "image_cache"
        indexes = [IndexModel([("cq_code", pymongo.HASHED)], name="cq_code_index")]


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
]
