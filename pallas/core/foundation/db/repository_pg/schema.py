"""PostgreSQL ORM 模型定义"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

_JsonB = JSONB().with_variant(JSON(), "sqlite")


class Base(DeclarativeBase):
    pass


class ContextAnswerRow(Base):
    __tablename__ = "context_answer"
    # keywords_hash 定长 md5 唯一索引
    __table_args__ = (
        UniqueConstraint("context_id", "group_id", "keywords_hash", name="uq_context_answer_ctx_group_kw"),
        Index("ix_context_answer_ctx_count_time", "context_id", "count", "time"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    context_id: Mapped[int] = mapped_column(ForeignKey("context.id", ondelete="CASCADE"), nullable=False)
    keywords: Mapped[str] = mapped_column(Text, nullable=False)
    keywords_hash: Mapped[str] = mapped_column(Text, nullable=False)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    time: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    messages: Mapped[list[ContextAnswerMessageRow]] = relationship(
        "ContextAnswerMessageRow", cascade="all, delete-orphan", lazy="noload"
    )


class ContextAnswerMessageRow(Base):
    __tablename__ = "context_answer_message"
    __table_args__ = (Index("ix_context_answer_message_answer_id_id", "answer_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    answer_id: Mapped[int] = mapped_column(
        ForeignKey("context_answer.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)


class ContextBanRow(Base):
    __tablename__ = "context_ban"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    context_id: Mapped[int] = mapped_column(ForeignKey("context.id", ondelete="CASCADE"), nullable=False, index=True)
    keywords: Mapped[str] = mapped_column(Text, nullable=False)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    time: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class ContextRow(Base):
    __tablename__ = "context"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    keywords: Mapped[str] = mapped_column(Text, nullable=False)
    # unique=True 已由 PG 自动建 btree，不再附加 index=True 以免冗余索引
    keywords_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    time: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    trigger_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    clear_time: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    answers: Mapped[list[ContextAnswerRow]] = relationship(
        "ContextAnswerRow", cascade="all, delete-orphan", lazy="noload"
    )
    ban: Mapped[list[ContextBanRow]] = relationship("ContextBanRow", cascade="all, delete-orphan", lazy="noload")


class MessageRow(Base):
    __tablename__ = "message"
    __table_args__ = (
        Index("ix_message_time", "time"),
        Index("ix_message_group_time", "group_id", "time"),
        Index("ix_message_group_user_time", "group_id", "user_id", "time"),
        # 消息幂等落库锚点：同 (group_id, bot_id, message_id) 只留一条。
        # message_id 为 NULL 的行不参与冲突（PG 中 NULL <> NULL，互不冲突）。
        Index("uq_message_group_bot_message_id", "group_id", "bot_id", "message_id", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    bot_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    raw_message: Mapped[str] = mapped_column(Text, nullable=False)
    is_plain_text: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    plain_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    keywords: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sender_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reply_to_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    suppressed_by_rage: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    time: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class BackgroundJobRow(Base):
    __tablename__ = "background_job"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_background_job_idempotency"),
        Index("ix_background_job_claim", "status", "available_at", "leased_until", "id"),
        Index("ix_background_job_delivery_claim", "kind", "status", "finished_at"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[Any] = mapped_column(_JsonB, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    leased_until: Mapped[float | None] = mapped_column(Float, nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    finished_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class BlackListRow(Base):
    __tablename__ = "blacklist"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    answers: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=list)
    answers_reserve: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=list)


class AdminMemberRow(Base):
    __tablename__ = "admin_members"
    __table_args__ = (
        UniqueConstraint("scope", "bot_id", "user_id", name="uq_admin_members_scope_bot_user"),
        Index("ix_admin_members_bot_user", "bot_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    bot_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class PallasACLRow(Base):
    __tablename__ = "acl_rules"
    __table_args__ = (
        UniqueConstraint(
            "role",
            "subject",
            "action",
            "target_scope",
            "target",
            name="uq_acl_rules_signature",
        ),
        Index("ix_acl_rules_action", "action"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_scope: Mapped[str] = mapped_column(Text, nullable=False)
    target: Mapped[str] = mapped_column(Text, nullable=False)
    effect: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="user")
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class SchemaMigrationRow(Base):
    __tablename__ = "schema_migrations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    step: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    applied_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class BotConfigRow(Base):
    __tablename__ = "bot_config"

    account: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    admins: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=list)
    auto_accept_friend: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_accept_group: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    security: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    taken_name: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=dict)
    drunk: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=dict)
    disabled_plugins: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=list)
    disabled_plugins_audit: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=list)
    community_roster_show_qq: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    persona: Mapped[Any] = mapped_column(_JsonB, nullable=True)
    group_style_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    plugin_storage: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=dict)


class GroupConfigRow(Base):
    __tablename__ = "group_config"

    group_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    roulette_mode: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    banned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sing_progress: Mapped[Any] = mapped_column(_JsonB, nullable=True)
    disabled_plugins: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=list)
    disabled_plugins_audit: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=list)
    blocked_user_ids: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=list)
    style_profile: Mapped[Any] = mapped_column(_JsonB, nullable=True)
    plugin_storage: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=dict)


class UserConfigRow(Base):
    __tablename__ = "user_config"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    banned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    banned_by: Mapped[str] = mapped_column(Text, nullable=False, default="")
    banned_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    maa_devices: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=dict)
    maa_active_device: Mapped[str] = mapped_column(Text, nullable=False, default="")
    maa_stage_plan: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=list)
    plugin_storage: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=dict)


class ImageCacheRow(Base):
    __tablename__ = "image_cache"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cq_code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    # 原生二进制 BYTEA。旧库 base64_data 由 init_pg → _ensure_pg_image_cache_blob_data 幂等迁移。
    blob_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # 二进制已落文件（data/image_cache_blobs），DB 只存相对路径与字节数。
    blob_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    blob_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ref_times: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    date: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)


class StickerLabelRow(Base):
    """按原始二进制内容哈希缓存的表情语义标签。"""

    __tablename__ = "sticker_label"

    content_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    is_sticker: Mapped[bool] = mapped_column(Boolean, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    prompt_version: Mapped[int] = mapped_column(Integer, nullable=False)
    labeled_at: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    label_json: Mapped[Any] = mapped_column(_JsonB, nullable=False)


class UserStickerStatRow(Base):
    """群成员发送图片的次数统计，按内容哈希聚合，不带 bot 维度。"""

    __tablename__ = "user_sticker_stat"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", "content_hash", name="uq_user_sticker_stat_group_user_hash"),
        Index("ix_user_sticker_stat_send_count", "send_count"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    send_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_sent_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class LlmChatMessageRow(Base):
    __tablename__ = "llm_chat_message"
    __table_args__ = (
        Index("ix_llm_chat_message_bot_group_time", "bot_id", "group_id", "created_at"),
        Index("ix_llm_chat_message_bot_group_user_time", "bot_id", "group_id", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bot_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class LlmMemoryEntryRow(Base):
    __tablename__ = "llm_memory_entry"
    __table_args__ = (Index("ix_llm_memory_entry_bot_group_time", "bot_id", "group_id", "updated_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bot_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    keywords: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="teach")
    importance: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    expires_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    visibility: Mapped[str] = mapped_column(Text, nullable=False, default="private")
    embedding_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    embedding_model: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class LlmRelationshipNoteRow(Base):
    """关系备注层：按 (bot, group, user) 维护稳定关系事实，带置信权重与衰减。"""

    __tablename__ = "llm_relationship_note"
    __table_args__ = (
        Index(
            "ix_llm_relationship_note_scope",
            "bot_id",
            "group_id",
            "user_id",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bot_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="teach")
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    warmth_delta: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    assertiveness_delta: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    affinity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    rage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rage_last_attack_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    rage_last_attack_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    rage_silenced_until: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    rage_silence_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class LlmMemoryEntityRow(Base):
    """记忆图谱实体（人/概念等）。"""

    __tablename__ = "llm_memory_entity"
    __table_args__ = (
        Index("uq_llm_memory_entity_scope_name", "scope_key", "name", unique=True),
        Index("ix_llm_memory_entity_bot_group_time", "bot_id", "group_id", "updated_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scope_key: Mapped[str] = mapped_column(Text, nullable=False)
    bot_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    kind: Mapped[str] = mapped_column(Text, nullable=False, default="concept")
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=None)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="manual")
    deleted_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=None)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class LlmMemoryEdgeRow(Base):
    """记忆图谱关系边。"""

    __tablename__ = "llm_memory_edge"
    __table_args__ = (
        Index("ix_llm_memory_edge_scope_valid", "scope_key", "valid_at"),
        Index("ix_llm_memory_edge_scope_source", "scope_key", "source_entity_id"),
        Index("ix_llm_memory_edge_scope_target", "scope_key", "target_entity_id"),
        Index("ix_llm_memory_edge_bot_group", "bot_id", "group_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scope_key: Mapped[str] = mapped_column(Text, nullable=False)
    bot_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    fact: Mapped[str] = mapped_column(Text, nullable=False)
    source_entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    target_entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    relation_type: Mapped[str] = mapped_column(Text, nullable=False, default="related_to")
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    mention_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    episode_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    valid_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    invalid_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=None)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="manual")
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class LlmMemoryCategoryRow(Base):
    """记忆图谱分类（分层语义树节点）。"""

    __tablename__ = "llm_memory_category"
    __table_args__ = (
        Index("uq_llm_memory_category_scope_layer_name", "scope_key", "layer", "name", unique=True),
        Index("ix_llm_memory_category_bot_group", "bot_id", "group_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scope_key: Mapped[str] = mapped_column(Text, nullable=False)
    bot_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    layer: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    parent_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=None)
    member_entity_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    source: Mapped[str] = mapped_column(Text, nullable=False, default="manual")
    deleted_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=None)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class LlmMemoryHierStatusRow(Base):
    """分层语义图重建状态（每 scope 一行）。"""

    __tablename__ = "llm_memory_hier_status"

    scope_key: Mapped[str] = mapped_column(Text, primary_key=True)
    bot_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    max_layer: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_rebuild_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    entity_count_at_rebuild: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    group_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
