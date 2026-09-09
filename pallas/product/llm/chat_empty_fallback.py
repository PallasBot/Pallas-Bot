"""llm_chat 空回复静默相关常量。"""

from __future__ import annotations

# 硬触发：用户明确点名/续聊；ambient 空输出可静默
HARD_SPEAK_TRIGGERS = frozenset({"to_me", "mention", "followup"})
