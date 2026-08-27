"""@闲聊短期去重与群聊节奏辅助。"""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pallas.product.llm.session_store import LlmChatTurn

_DIRECT_REPEATED_OPENERS = (
    "哈喽",
    "其实",
    "这倒是",
    "怎么说呢",
    "感觉",
    "我觉得",
    "确实",
    "一般来说",
    "行行行",
    "好好好",
    "还行吧",
    "行啊",
    "行吧",
    "行，",
)
_LAUGH_OPENER_RE = re.compile(r"^(哈哈+|呵呵+|嘿嘿+)")
_SIGH_OPENER_RE = re.compile(r"^(欸|哎|唉|呃|额)+")
_ANIMAL_OPENER_RE = re.compile(r"^(哞~|喵~|喵呜~|哞呜~)")
_TILDE_OPENER_RE = re.compile(r"^([\u4e00-\u9fff]{1,2})~")
_KAOMOJI_SUFFIX_RE = re.compile(r"\(\*[^)]{1,16}\*\)\s*$")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")
_ECHO_QUESTION_RE = re.compile(r"^[\u4e00-\u9fffA-Za-z0-9]{1,8}[？?]")

_ATTITUDE_SKELETON_PATTERNS = (
    ("想得美", re.compile(r"想得美")),
    ("少来", re.compile(r"少来(?:这套|这个)")),
    ("别吵/别哭/别闹", re.compile(r"别(?:吵|哭|闹|催|乱叫|烦我)")),
    ("自己…去", re.compile(r"自己.{0,4}去")),
    ("欠收拾", re.compile(r"欠收拾")),
    ("嘴欠/欠", re.compile(r"嘴欠|欠")),
)
_ATTITUDE_SKELETON_MIN_OCCURRENCES = 2
_ATTITUDE_SKELETON_WINDOW = 6

_USER_WAIT_SUFFIXES = ("?", "？", "...", "…", "、")
_USER_WAIT_TOKENS = ("等等", "等下", "先别", "我补一句", "还有", "然后")
_STRUCTURE_MARKERS = ("先", "别", "可以", "不用", "慢慢", "一下", "这事", "你先")
_GENERIC_PREFIX_MIN_LEN = 3
_GENERIC_PREFIX_MAX_LEN = 4
_MOTIF_WINDOW = 6
_MOTIF_MIN_DOCS = 2
_MOTIF_LIMIT = 4
_MOTIF_NGRAM_MIN = 2
_MOTIF_NGRAM_MAX = 4
_MOTIF_STOPWORDS = frozenset({
    "我们",
    "你们",
    "他们",
    "这个",
    "那个",
    "什么",
    "怎么",
    "不是",
    "就是",
    "可以",
    "没有",
    "还是",
    "一个",
    "自己",
    "然后",
    "因为",
    "所以",
    "如果",
    "已经",
    "真的",
    "有点",
    "一下",
    "这样",
    "那样",
    "这么",
    "那么",
    "怎样",
    "为何",
    "为啥",
    "知道",
    "觉得",
    "感觉",
    "其实",
    "不过",
    "但是",
    "而且",
    "或者",
    "牛牛",
    "博士",
    "帕拉斯",
    "今天",
    "明天",
    "昨天",
    "现在",
    "时候",
    "东西",
    "地方",
    "问题",
    "事情",
})


def should_wait_for_more(user_text: str, *, is_to_me: bool = False) -> bool:
    if is_to_me:
        return False
    text = str(user_text or "").strip()
    if not text:
        return False
    if any(text.endswith(token) for token in _USER_WAIT_SUFFIXES):
        return True
    return any(token in text[-8:] for token in _USER_WAIT_TOKENS)


def has_kaomoji_suffix(text: str) -> bool:
    return bool(_KAOMOJI_SUFFIX_RE.search(str(text or "").strip()))


def _motif_ngrams_for_text(text: str) -> set[str]:
    grams: set[str] = set()
    for run in _CJK_RUN_RE.findall(str(text or "")):
        max_n = min(_MOTIF_NGRAM_MAX, len(run))
        for size in range(_MOTIF_NGRAM_MIN, max_n + 1):
            for index in range(len(run) - size + 1):
                gram = run[index : index + size]
                if gram in _MOTIF_STOPWORDS:
                    continue
                if any(stop in gram and stop != gram for stop in ("什么", "怎么", "怎样")):
                    continue
                grams.add(gram)
    return grams


def extract_recent_motifs(texts: list[str]) -> list[str]:
    """从近窗 assistant 回复里统计重复中文片段，自动当成本轮母题（无需手维黑名单）。"""
    recent_texts = [str(item or "").strip() for item in texts[-_MOTIF_WINDOW:] if str(item or "").strip()]
    if len(recent_texts) < _MOTIF_MIN_DOCS:
        return []

    doc_freq: Counter[str] = Counter()
    for text in recent_texts:
        for gram in _motif_ngrams_for_text(text):
            doc_freq[gram] += 1

    candidates = [(gram, count) for gram, count in doc_freq.items() if count >= _MOTIF_MIN_DOCS]
    # 先高文档频，再偏长，抓住「牛角」这类真正发粘核心
    candidates.sort(key=lambda item: (-item[1], -len(item[0]), item[0]))
    picked: list[str] = []
    for gram, _count in candidates:
        if any(gram in chosen or chosen in gram for chosen in picked):
            continue
        picked.append(gram)
        if len(picked) >= _MOTIF_LIMIT:
            break
    return picked


def count_echo_question_openers(texts: list[str]) -> int:
    return sum(1 for text in texts if _ECHO_QUESTION_RE.match(str(text or "").strip()))


def repeated_assistant_openers(turns: list[LlmChatTurn], *, limit: int = 3) -> list[str]:
    seen: list[str] = []
    for turn in reversed(turns):
        if turn.role != "assistant":
            continue
        text = str(turn.content or "").strip()
        if not text:
            continue
        opener = classify_repeated_opener(text)
        if opener and opener not in seen:
            seen.append(opener)
        if len(seen) >= limit:
            break
    return seen


def classify_repeated_opener(text: str) -> str:
    from pallas.product.persona.soft_agree_fillers import match_soft_agree_opener

    plain = str(text or "").strip()
    if not plain:
        return ""
    animal = _ANIMAL_OPENER_RE.match(plain)
    if animal:
        return animal.group(1)
    if _LAUGH_OPENER_RE.match(plain):
        return "哈哈类"
    if _SIGH_OPENER_RE.match(plain):
        return "语气词类"
    soft = match_soft_agree_opener(plain)
    if soft:
        return soft
    direct = next((item for item in _DIRECT_REPEATED_OPENERS if plain.startswith(item)), "")
    if direct:
        return direct
    return normalize_generic_prefix(plain)


def normalize_generic_prefix(text: str) -> str:
    plain = str(text or "").strip()
    if len(plain) < _GENERIC_PREFIX_MIN_LEN:
        return ""
    tilde = _TILDE_OPENER_RE.match(plain)
    if tilde:
        prefix = tilde.group(0)
        if len(prefix) >= _GENERIC_PREFIX_MIN_LEN:
            return prefix
    prefix_chars: list[str] = []
    for char in plain:
        if char in "，,。！？!?~～…：:；;、()[]【】<>《》\"'“”‘’ ":
            break
        prefix_chars.append(char)
        if len(prefix_chars) >= _GENERIC_PREFIX_MAX_LEN:
            break
    prefix = "".join(prefix_chars).strip()
    if len(prefix) < _GENERIC_PREFIX_MIN_LEN:
        return ""
    if prefix.isdigit() or not any("\u4e00" <= char <= "\u9fff" for char in prefix):
        return ""
    if prefix in {"我是", "你是", "这个", "那个", "不是", "就是"}:
        return ""
    return prefix


def repeated_attitude_skeletons(texts: list[str]) -> list[str]:
    """从近窗回复里统计反复出现的「嘴硬/拒绝」态度动作模板，避免回顶句式粘样。"""
    recent = [str(item or "").strip() for item in texts[-_ATTITUDE_SKELETON_WINDOW:] if str(item or "").strip()]
    if len(recent) < _ATTITUDE_SKELETON_MIN_OCCURRENCES:
        return []

    counts: Counter[str] = Counter()
    for text in recent:
        for label, pattern in _ATTITUDE_SKELETON_PATTERNS:
            if pattern.search(text):
                counts[label] += 1
    picked = [label for label, count in counts.items() if count >= _ATTITUDE_SKELETON_MIN_OCCURRENCES]
    return picked


def recent_assistant_endings(turns: list[LlmChatTurn], *, limit: int = 3) -> list[str]:
    seen: list[str] = []
    for turn in reversed(turns):
        if turn.role != "assistant":
            continue
        text = str(turn.content or "").strip()
        if not text or has_kaomoji_suffix(text):
            continue
        compact = text.rstrip("。！？!?~～…，,、 ")
        if not compact:
            continue
        ending = compact[-4:]
        if len(ending) < 2 or ending in seen:
            continue
        seen.append(ending)
        if len(seen) >= limit:
            break
    return seen


def build_recent_reply_ending_hint(turns: list[LlmChatTurn]) -> str:
    assistant_texts = [str(turn.content or "").strip() for turn in turns if turn.role == "assistant" and turn.content]
    if len(assistant_texts) >= 3:
        kaomoji_count = sum(1 for text in assistant_texts[-3:] if has_kaomoji_suffix(text))
        if kaomoji_count >= 2:
            return ""
    endings = recent_assistant_endings(turns)
    if not endings:
        return ""
    return "\n【收尾变化参考】这轮可优先试试这些自然收口：" + "、".join(endings) + "。"


def build_recent_reply_variation_hint(turns: list[LlmChatTurn]) -> str:
    assistant_texts = [str(turn.content or "").strip() for turn in turns if turn.role == "assistant" and turn.content]
    if not assistant_texts:
        return ""

    hints: list[str] = []
    motifs = extract_recent_motifs(assistant_texts)
    if motifs:
        hints.append("最近几轮别老围着这些短窗母题打转：" + "、".join(motifs) + "；换隐喻或直接短怼")
    attitude_skeletons = repeated_attitude_skeletons(assistant_texts)
    if attitude_skeletons:
        hints.append("最近回顶/拒绝句式用太多，换个温和的说法：" + "、".join(attitude_skeletons))
    openers = repeated_assistant_openers(turns)
    if openers:
        hints.append("最近几轮别再用这些开头：" + "、".join(openers))
        try:
            from pallas.product.persona.affect_kernel import (
                build_persona_affect_contract,
                build_variation_hint_from_contract,
            )

            affect_hint = build_variation_hint_from_contract(
                build_persona_affect_contract(repeated_openers=openers),
            )
            if affect_hint and affect_hint not in hints:
                hints.append(affect_hint.removeprefix("【开头去重】"))
        except Exception:
            pass

    # 同一开头连用 ≥2 次时加重提示（去重指令常被维护者样本盖过）
    recent4 = assistant_texts[-4:]
    opener_counts: dict[str, int] = {}
    for text in recent4:
        opener = classify_repeated_opener(text)
        if not opener:
            continue
        opener_counts[opener] = opener_counts.get(opener, 0) + 1
    sticky = [opener for opener, count in opener_counts.items() if count >= 2]
    if sticky:
        hints.insert(0, "严禁再用这些已重复的开头：" + "、".join(sticky) + "；换完全不同的起手")
        from pallas.product.persona.soft_agree_fillers import SOFT_AGREE_OPENERS

        if any(item in SOFT_AGREE_OPENERS for item in sticky):
            hints.insert(1, "别用行行行/好好好/还行吧起手，直接接话题")

    if count_echo_question_openers(recent4) >= 2:
        hints.insert(0, "最近老用「复读对方词？」起手，这轮直接接话，别再复读反问")

    recent = assistant_texts[-3:]
    from pallas.product.persona.soft_agree_fillers import match_soft_agree_opener

    soft_recent = sum(1 for text in recent if match_soft_agree_opener(text))
    if soft_recent >= 2:
        hints.append("最近软答应起手太多，这轮直接接话，不要行行行/还行吧")
    animal_openers = sum(1 for text in recent if _ANIMAL_OPENER_RE.match(text))
    if animal_openers >= 2:
        hints.append("最近开头动物口癖太多，别再用哞~/喵~ 起手")

    kaomoji_count = sum(1 for text in recent if has_kaomoji_suffix(text))
    if kaomoji_count >= 2:
        hints.append("最近句尾颜文字太像模板，这轮别加 (*…*) 这类 ASCII 表情")

    recent_lengths = [len(text) for text in assistant_texts[-3:]]
    if recent_lengths and min(recent_lengths) >= 28:
        hints.append("最近解释偏满，这轮优先短一点，像顺手接一句")
    elif len(assistant_texts) >= 3:
        structural_texts = assistant_texts[-3:]
        if min(len(text) for text in structural_texts) >= 14:
            shared_markers = sum(
                1 for marker in _STRUCTURE_MARKERS if sum(1 for text in structural_texts if marker in text) >= 2
            )
            if shared_markers >= 3:
                hints.append("最近解释偏满，这轮优先短一点，像顺手接一句")

    if len(assistant_texts) >= 3:
        structural_texts = assistant_texts[-3:]
        shared_markers = [
            marker for marker in _STRUCTURE_MARKERS if sum(1 for text in structural_texts if marker in text) >= 2
        ]
        if len(shared_markers) >= 4:
            hints.append("最近句式有点一个模子，少用“先判断一下、再补解释”的答法")

    endings = [text[-1] for text in assistant_texts[-3:] if text]
    if len(endings) >= 3 and len(set(endings)) == 1:
        hints.append("最近收尾太像模板，换个自然收口")

    if not hints:
        return ""
    return "【本轮表达去重】\n- " + "\n- ".join(hints[:5])


def build_variation_hint_from_recent_texts(recent_texts: list[str]) -> str:
    texts = [str(item or "").strip() for item in recent_texts if str(item or "").strip()]
    if not texts:
        return ""

    hints: list[str] = []
    motifs = extract_recent_motifs(texts)
    if motifs:
        hints.append("最近几轮别老围着这些短窗母题打转：" + "、".join(motifs) + "；换隐喻或直接短怼")
    openers: list[str] = []
    for text in reversed(texts[-6:]):
        opener = classify_repeated_opener(text)
        if opener and opener not in openers:
            openers.append(opener)
        if len(openers) >= 3:
            break
    if openers:
        hints.append("最近几轮别再用这些开头：" + "、".join(openers))

    recent = texts[-3:]
    if count_echo_question_openers(texts[-4:]) >= 2:
        hints.insert(0, "最近老用「复读对方词？」起手，这轮直接接话，别再复读反问")
    animal_openers = sum(1 for text in recent if _ANIMAL_OPENER_RE.match(text))
    if animal_openers >= 2:
        hints.append("最近开头动物口癖太多，别再用哞~/喵~ 起手")

    kaomoji_count = sum(1 for text in recent if has_kaomoji_suffix(text))
    if kaomoji_count >= 2:
        hints.append("最近句尾颜文字太像模板，这轮别加 (*…*) 这类 ASCII 表情")

    if recent and min(len(text) for text in recent) >= 28:
        hints.append("最近解释偏满，这轮优先短一点，像顺手接一句")

    endings = [text[-1] for text in recent if text]
    if len(endings) >= 3 and len(set(endings)) == 1:
        hints.append("最近收尾太像模板，换个自然收口")

    if not hints:
        return ""
    return "【本轮表达去重】\n- " + "\n- ".join(hints[:4])
