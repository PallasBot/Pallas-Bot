"""发送前轻量后处理：可选错别字与末尾句号处理。"""

from __future__ import annotations

import random

# 常见近音/形近替换，刻意保守，避免引入额外依赖
_TYPO_MAP: dict[str, tuple[str, ...]] = {
    "的": ("得", "地"),
    "了": ("啦", "嘞"),
    "是": ("事", "似"),
    "在": ("再",),
    "有": ("又",),
    "和": ("合", "河"),
    "就": ("旧",),
    "都": ("兜",),
    "会": ("回",),
    "还": ("孩",),
    "吧": ("罢",),
    "吗": ("嘛",),
    "呢": ("呐",),
}


def trim_terminal_period(text: str, *, trim_rate: float = 0.9, rng_seed: int | None = None) -> str:
    """Occasionally omit only the terminal period on a short casual statement."""
    plain = str(text or "").strip()
    if len(plain) > 24 or not plain.endswith("。") or "。" in plain[:-1]:
        return plain
    rate = max(0.0, min(1.0, float(trim_rate)))
    if rate <= 0 or random.Random(rng_seed).random() >= rate:
        return plain
    return plain[:-1]


def apply_chinese_typo(text: str, *, error_rate: float = 0.01, rng_seed: int | None = None) -> str:
    plain = str(text or "")
    if not plain:
        return plain
    rate = max(0.0, min(1.0, float(error_rate)))
    if rate <= 0:
        return plain
    rng = random.Random(rng_seed)
    chars = list(plain)
    for idx, ch in enumerate(chars):
        alts = _TYPO_MAP.get(ch)
        if not alts:
            continue
        if rng.random() < rate:
            chars[idx] = rng.choice(alts)
    return "".join(chars)


def apply_reply_postprocess(
    text: str,
    *,
    enabled: bool = False,
    typo_enabled: bool = False,
    typo_rate: float = 0.01,
    trim_terminal_period_enabled: bool = True,
    trim_terminal_period_rate: float = 0.9,
    rng_seed: int | None = None,
) -> str:
    plain = str(text or "").strip()
    if not plain:
        return ""
    processed = plain
    if trim_terminal_period_enabled:
        processed = trim_terminal_period(
            processed,
            trim_rate=trim_terminal_period_rate,
            rng_seed=rng_seed,
        )
    if not enabled:
        return processed
    if typo_enabled:
        processed = apply_chinese_typo(processed, error_rate=typo_rate, rng_seed=rng_seed)
    return processed
