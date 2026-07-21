from __future__ import annotations

from pallas.product.llm.kernel.models import ConversationMode, ConversationScene
from pallas.product.llm.scene_style import (
    format_scene_style_block,
    resolve_scene_style_constraints,
)


def test_banter_allows_balanced_drift_and_short_joke_style() -> None:
    c = resolve_scene_style_constraints(ConversationScene.BANTER, ConversationMode.NORMAL)
    assert c.drift_level == "balanced"
    assert c.disallow_drift is False
    assert "梗" in c.style_hint or "玩笑" in c.style_hint
    assert c.max_length <= 36


def test_group_threading_stays_strict_observer() -> None:
    c = resolve_scene_style_constraints(ConversationScene.GROUP_THREADING, ConversationMode.NORMAL)
    assert c.drift_level == "strict"
    assert c.disallow_drift is True
    assert "旁观" in c.style_hint or "锚点" in c.style_hint


def test_venting_prefers_ack_without_lecture() -> None:
    c = resolve_scene_style_constraints(ConversationScene.VENTING, ConversationMode.NORMAL)
    assert "情绪" in c.style_hint or "价值" in c.style_hint
    assert c.drift_level in {"strict", "balanced"}


def test_ghost_mode_keeps_strict_even_on_banter() -> None:
    c = resolve_scene_style_constraints(ConversationScene.BANTER, ConversationMode.GHOST)
    assert c.drift_level == "strict"
    assert c.disallow_drift is True
    assert c.max_length <= 18


def test_direct_chat_default_balanced() -> None:
    c = resolve_scene_style_constraints(
        ConversationScene.SMALLTALK,
        ConversationMode.NORMAL,
        direct_chat=True,
    )
    assert c.drift_level == "balanced"
    assert c.disallow_drift is False
    assert c.max_length >= 80


def test_format_scene_style_block_includes_drift() -> None:
    c = resolve_scene_style_constraints(ConversationScene.PROVOCATION, ConversationMode.NORMAL)
    block = format_scene_style_block(c)
    assert "【本轮场景口气】" in block
    assert c.style_hint[:8] in block
