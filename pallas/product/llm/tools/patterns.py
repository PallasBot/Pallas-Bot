"""多域结构召回：动词+量词等口语结构 → tool domain。"""

from __future__ import annotations

import re

# (regex, domain)；用 search，不要求整句匹配
_STRUCTURE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # 点歌/放歌：放首铁花飞、来一首、播一下歌
    (re.compile(r"(放|来|播|唱|点|整)\s*一?\s*首"), "sing"),
    (re.compile(r"(放|播|听)\s*一?\s*(下|个)?\s*.{0,16}?(歌|曲)"), "sing"),
    # 喝酒：来杯、干一杯（醒酒仍走关键词）
    (re.compile(r"(来|干|喝)\s*一?\s*(杯|口|瓶)"), "drink"),
    # 画画：来张、画一幅
    (re.compile(r"(来|画|抽)\s*一?\s*(张|幅)"), "draw"),
    # 帮助：怎么用、如何玩
    (re.compile(r"(怎么|如何)\s*.{0,8}?(用|玩|开)"), "help"),
    # 轮盘
    (re.compile(r"(开|玩|来)\s*一?\s*(把|局)?\s*.{0,6}?轮盘"), "roulette"),
    (re.compile(r"(开|补)\s*一?\s*枪"), "roulette"),
    # 决斗
    (re.compile(r"(来|开)\s*一?\s*(场|局)?\s*.{0,6}?决斗"), "duel"),
    # 做梦
    (re.compile(r"(做|说)\s*一?\s*(个|场)?\s*.{0,4}?梦"), "dream"),
    # 卧底
    (re.compile(r"(开|玩|来)\s*一?\s*(局|把)?\s*.{0,6}?卧底"), "who_is_spy"),
    # 占卜
    (re.compile(r"(抽|来)\s*一?\s*(张|副)?\s*.{0,4}?(牌|塔罗)"), "arcana"),
    # 表情
    (re.compile(r"(做|来)\s*一?\s*(个|张)?\s*.{0,4}?(表情|meme)"), "memes"),
    # 记忆（builtin）
    (re.compile(r"(记|记住|忘掉|回忆)\s*.{0,12}?(事|说过|以前)"), "memory"),
    # 找工具
    (re.compile(r"(有|能)\s*.{0,6}?(什么|哪些)\s*.{0,6}?工具"), "tools"),
)


def domains_from_structure(user_text: str) -> frozenset[str]:
    text = (user_text or "").strip().lower()
    if not text:
        return frozenset()
    hits: set[str] = set()
    for pattern, domain in _STRUCTURE_PATTERNS:
        if pattern.search(text):
            hits.add(domain)
    return frozenset(hits)
