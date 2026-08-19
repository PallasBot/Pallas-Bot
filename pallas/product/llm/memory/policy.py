"""群内旧事（episode_notes）准入与归一化策略。"""

from __future__ import annotations

import re

from pallas.product.persona.prompt_guard import sanitize_prompt_block

_EPISODE_NOTE_KIND = "episode_note"
_MIN_VALUE_LEN = 4
_REJECT_SUBSTRINGS = ("今天烦", "好烦", "烦死", "不开心", "难受", "emo")
_MEMORY_INSTRUCTION_RE = (
    "以后叫",
    "今后叫",
    "以后说",
    "今后说",
    "以后回复",
    "今后回复",
    "以后",
    "今后",
    "扮演",
    "忽略之前",
    "无视之前",
    "系统提示",
    "提示词",
)

# 寒暄 / 语气词 / 无信息碎片：任何一条命中即视为不值得沉淀
_EPHEMERAL_MARKERS = (
    "哈哈",
    "哈哈哈",
    "hhhh",
    "草",
    "666",
    "好",
    "好的",
    "收到",
    "嗯嗯",
    "晚安",
    "早安",
    "早",
    "拜拜",
    "再见",
    "谢谢",
    "谢谢啊",
    "在吗",
    "在不在",
    "咋了",
    "没事",
    "无所谓",
    "还行",
    "可以",
    "对啊",
    "真的",
    "确实",
    "笑死",
    "蚌埠住了",
    "绷不住",
    "乐",
    "典",
    "？",
    "？？",
    "？？？",
    "牛逼",
    "牛啊",
    "离谱",
    "啊？",
    "啥",
    "什么",
    "哈哈哈",
    "笑了",
)

# 临时 / 不确定 / 玩笑 / 猜测信号：命中则降级，不当作稳定事件
_TRANSIENT_WORDS = (
    "可能",
    "大概",
    "似乎",
    "好像",
    "感觉",
    "据说",
    "听说明",
    "估计",
    "也许",
    "可能吧",
    "应该是",
    "今晚",
    "明天",
    "今天",
    "最近",
    "临时",
    "暂时",
    "开玩笑",
    "只是说说",
    "随便说说",
)

# 实体 / 事件信号：命中才认为「可能有记忆价值」
# 聚焦明确事件/承诺/安排/人物变化，避免宽泛单字误伤
_HIGH_SIGNAL_RE = re.compile(
    r"(?:"
    r"周五|周六|周日|周[一二三四五六天]|周[末一到日]|"
    r"\d{4}[-/年]\d{1,2}|今天|明天|昨晚|上次|"
    r"叫[^哈哈哈]|是我的|叫[^哈哈]|记得|约好|说好|答应|报名|参加|"
    r"群主|管理|新成员|欢迎|退群|改名|活动|比赛|开黑|组队|"
    r"买了|换了|搬了|辞职|入职|分手|结婚了|退坑|入坑"
    r")"
)


def strip_teach_prefix(text: str) -> str:
    raw = (text or "").strip()
    for prefix in ("记住：", "记住:", "请你记住", "要记住", "帮我记住"):
        if raw.startswith(prefix):
            return raw[len(prefix) :].strip()
    return raw


def is_ephemeral_text(text: str) -> bool:
    """纯寒暄 / 语气词 / 无信息碎片：命中即不沉淀。"""
    body = strip_teach_prefix(text).strip()
    if not body:
        return True
    if len(body) <= 8 and any(marker in body for marker in _EPHEMERAL_MARKERS):
        return True
    return False


def has_event_signal(text: str) -> bool:
    """是否含实体 / 事件 / 承诺 / 明确安排信号。"""
    body = strip_teach_prefix(text)
    if not body:
        return False
    if len(body) >= 16:
        return True
    return bool(_HIGH_SIGNAL_RE.search(body))


def has_transient_signal(text: str) -> bool:
    """是否含临时 / 不确定 / 玩笑信号。"""
    body = strip_teach_prefix(text)
    return any(token in body for token in _TRANSIENT_WORDS)


def episode_note_has_group_value(text: str) -> bool:
    body = strip_teach_prefix(text)
    if len(body) < _MIN_VALUE_LEN:
        return False
    lowered = body.lower()
    if any(token in body for token in _REJECT_SUBSTRINGS):
        return False
    if any(token in body for token in _MEMORY_INSTRUCTION_RE):
        return False
    if body.startswith("我") and len(body) <= 6:
        return False
    if lowered in {"记一下", "这个", "那个"}:
        return False
    if is_ephemeral_text(body):
        return False
    return True


def classify_memory_candidate(text: str) -> str | None:
    body = strip_teach_prefix(text)
    if body == "这个梗":
        return _EPISODE_NOTE_KIND
    if not episode_note_has_group_value(text):
        return None
    return _EPISODE_NOTE_KIND


def normalize_episode_note(text: str, *, max_len: int) -> str:
    body = sanitize_prompt_block(strip_teach_prefix(text), max_len=max_len).strip()
    return body.rstrip("。！？!?；;，,、").strip()
