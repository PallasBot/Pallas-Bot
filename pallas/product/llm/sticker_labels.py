"""表情语义标签的受控模型。"""

from __future__ import annotations

import hashlib
import time

from pydantic import BaseModel, Field, field_validator

EMOTION_VOCABULARY = (
    "开心",
    "难过",
    "生气",
    "惊讶",
    "害羞",
    "无语",
    "委屈",
    "得意",
    "期待",
    "疑惑",
)
ACTION_VOCABULARY = ("微笑", "大笑", "哭", "挥手", "点赞", "拥抱", "点头", "摇头", "卖萌", "鼓掌")
TONE_VOCABULARY = ("可爱", "友好", "调侃", "夸张", "撒娇", "安慰", "礼貌", "阴阳怪气")

_MAX_CONTROLLED_LABELS = 4
_MAX_USAGE_ITEMS = 3
_MAX_TEXT_LENGTH = 160


def content_hash_for_bytes(content: bytes) -> str:
    """返回原始下载字节的 SHA256；不依赖 CQ、文件名或显示帧。"""
    return hashlib.sha256(content).hexdigest()


def _label_values(value: object) -> tuple[object, ...]:
    if value is None or value is False or value == 0:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (tuple, list, set)):
        return tuple(value)
    raise ValueError("label values must be a string, tuple, list, or set")


def _normalize_controlled(values: object, vocabulary: tuple[str, ...]) -> tuple[str, ...]:
    supplied = {str(value).strip() for value in _label_values(values)}
    return tuple(label for label in vocabulary if label in supplied)[:_MAX_CONTROLLED_LABELS]


def _normalize_text_items(values: object) -> tuple[str, ...]:
    seen: set[str] = set()
    normalized: list[str] = []
    for value in _label_values(values):
        text = str(value).strip()[:_MAX_TEXT_LENGTH]
        if text and text not in seen:
            seen.add(text)
            normalized.append(text)
        if len(normalized) >= _MAX_USAGE_ITEMS:
            break
    return tuple(normalized)


class StickerSemanticLabel(BaseModel):
    content_hash: str
    is_sticker: bool
    emotions: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    tones: tuple[str, ...] = ()
    intensity: int = Field(default=0, ge=0, le=3)
    usage: tuple[str, ...] = ()
    avoid: tuple[str, ...] = ()
    caption: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    model: str = ""
    prompt_version: int = Field(default=0, ge=0)
    labeled_at: int = Field(default_factory=lambda: int(time.time()), ge=0)

    @field_validator("content_hash")
    @classmethod
    def validate_content_hash(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("content_hash must be a lowercase SHA256 hex digest")
        return value

    @field_validator("emotions", mode="before")
    @classmethod
    def normalize_emotions(cls, value: object) -> tuple[str, ...]:
        return _normalize_controlled(value, EMOTION_VOCABULARY)

    @field_validator("actions", mode="before")
    @classmethod
    def normalize_actions(cls, value: object) -> tuple[str, ...]:
        return _normalize_controlled(value, ACTION_VOCABULARY)

    @field_validator("tones", mode="before")
    @classmethod
    def normalize_tones(cls, value: object) -> tuple[str, ...]:
        return _normalize_controlled(value, TONE_VOCABULARY)

    @field_validator("usage", "avoid", mode="before")
    @classmethod
    def normalize_text_items(cls, value: object) -> tuple[str, ...]:
        return _normalize_text_items(value)

    @field_validator("caption", "model", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> str:
        return str(value or "").strip()[:_MAX_TEXT_LENGTH]


def needs_relabel(
    label: StickerSemanticLabel | None,
    *,
    prompt_version: int,
    min_confidence: float,
) -> bool:
    """缺失、低置信度或旧 prompt 的标签都应重新标注。"""
    return label is None or label.confidence < min_confidence or label.prompt_version < prompt_version
