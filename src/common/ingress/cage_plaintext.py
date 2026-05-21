"""八角笼入口明文识别（供 ingress 门控与 duel 共用，勿依赖 plugins）。"""

from __future__ import annotations

import re

_CAGE_CMD_RE = re.compile(r"^八角笼(?:牛|斗)(?:\s*(\d{1,2}\s*(?:幕|回合)))?\s*$")


def is_cage_plaintext(text: str) -> bool:
    """八角笼牛/八角笼斗，可选末尾 N幕/N回合。"""
    return bool(_CAGE_CMD_RE.match((text or "").strip()))
