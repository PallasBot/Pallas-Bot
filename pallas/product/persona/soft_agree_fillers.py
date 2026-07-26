"""万能软答应 / 空填充：不当作账号口癖，并用于去重与空回复兜底。

「行行行」「还行吧」一类是模板起手，不是可学习的情境口癖。
"""

from __future__ import annotations

# 整词：口癖抽取 / 注入时拒绝
WEAK_CATCHPHRASE_SAYINGS: frozenset[str] = frozenset({
    "行行行",
    "好好好",
    "还行吧",
    "还行吧。",
    "行啊",
    "行吧",
    "行",
    "嗯",
    "嗯？",
    "嗯。",
    "啊",
    "啊？",
    "哦",
    "哦？",
    "哈",
    "哈哈",
    "额",
    "额？",
    "咋了",  # 空回复兜底用语，勿学成口癖
})

# 开头：短期去重提示用（长短按匹配优先）
SOFT_AGREE_OPENERS: tuple[str, ...] = (
    "行行行",
    "好好好",
    "还行吧",
    "行啊",
    "行吧",
    "行，",
    "行。",
)

# 硬触发空输出时用；须不在 FILLER_ONLY_REPLIES，避免过滤后再被填回同一垫词
LLM_CHAT_EMPTY_FALLBACK_TEXT = "咋了"


def is_weak_catchphrase_saying(saying: str) -> bool:
    plain = " ".join(str(saying or "").split()).strip()
    if not plain:
        return False
    compact = plain.rstrip("。.!！?？~～…")
    return plain in WEAK_CATCHPHRASE_SAYINGS or compact in WEAK_CATCHPHRASE_SAYINGS


def match_soft_agree_opener(text: str) -> str:
    plain = str(text or "").strip()
    if not plain:
        return ""
    for opener in SOFT_AGREE_OPENERS:
        if plain.startswith(opener):
            return opener
    return ""
