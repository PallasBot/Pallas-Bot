"""Minimal decision context payload shared by repeater and llm_chat."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .models import ConversationMode, ConversationPath, ConversationScene, normalize_conversation_mode


class ConversationContext(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    path: ConversationPath
    plain_text: str = ""
    group_id: int | None = None
    bot_id: int | None = None
    user_id: int | None = None
    is_to_me: bool = False
    reply_mode: ConversationMode = ConversationMode.NORMAL
    scene: ConversationScene = ConversationScene.SMALLTALK
    unique_users: int = 0
    recent_message_count: int = 0
    has_candidate_pool: bool = False
    candidate_pool_size: int = 0
    candidate_style_score: float = 0.0
    has_recent_back_and_forth: bool = False
    bot_recently_replied: bool = False
    recent_texts: list[str] = Field(default_factory=list)
    has_multi_party_overlap: bool = False
    hosted_activity: bool = False

    @classmethod
    def for_repeater(
        cls,
        *,
        plain_text: str,
        group_id: int,
        bot_id: int,
        user_id: int,
        reply_mode: str,
        unique_users: int,
        recent_message_count: int,
        has_candidate_pool: bool,
        candidate_pool_size: int,
        candidate_style_score: float,
        has_recent_back_and_forth: bool,
        bot_recently_replied: bool,
        is_to_me: bool = False,
        scene: ConversationScene | None = None,
    ) -> ConversationContext:
        return cls(
            path=ConversationPath.REPEATER_ASSIST,
            plain_text=plain_text,
            group_id=group_id,
            bot_id=bot_id,
            user_id=user_id,
            is_to_me=is_to_me,
            reply_mode=normalize_conversation_mode(reply_mode),
            scene=scene or ConversationScene.SMALLTALK,
            unique_users=unique_users,
            recent_message_count=recent_message_count,
            has_candidate_pool=has_candidate_pool,
            candidate_pool_size=candidate_pool_size,
            candidate_style_score=candidate_style_score,
            has_recent_back_and_forth=has_recent_back_and_forth,
            bot_recently_replied=bot_recently_replied,
        )

    @classmethod
    def for_direct_chat(
        cls,
        *,
        plain_text: str,
        group_id: int | None,
        bot_id: int,
        user_id: int,
        scene: ConversationScene,
        recent_texts: list[str] | None = None,
        has_multi_party_overlap: bool = False,
    ) -> ConversationContext:
        return cls(
            path=ConversationPath.LLM_CHAT_DIRECT,
            plain_text=plain_text,
            group_id=group_id,
            bot_id=bot_id,
            user_id=user_id,
            is_to_me=True,
            scene=scene,
            recent_texts=list(recent_texts or []),
            has_multi_party_overlap=has_multi_party_overlap,
        )
