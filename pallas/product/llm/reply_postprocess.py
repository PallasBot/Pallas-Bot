"""发送前轻量后处理：可选错别字与拆条（默认关）。"""

from __future__ import annotations

import random
import re

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

_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])")


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


def split_reply_segments(text: str, *, max_chars: int = 36) -> list[str]:
    plain = str(text or "").strip()
    if not plain:
        return []
    limit = max(4, int(max_chars))
    rough = [part.strip() for part in _SPLIT_RE.split(plain) if part and part.strip()]
    if not rough:
        rough = [plain]
    out: list[str] = []
    buf = ""
    for part in rough:
        candidate = f"{buf}{part}" if buf else part
        if len(candidate) <= limit:
            buf = candidate
            continue
        if buf:
            out.append(buf)
        if len(part) <= limit:
            buf = part
            continue
        for start in range(0, len(part), limit):
            chunk = part[start : start + limit].strip()
            if chunk:
                out.append(chunk)
        buf = ""
    if buf:
        out.append(buf)
    return out or [plain]


def apply_reply_postprocess(
    text: str,
    *,
    enabled: bool = False,
    typo_enabled: bool = False,
    typo_rate: float = 0.01,
    split_enabled: bool = False,
    split_max_chars: int = 36,
    rng_seed: int | None = None,
) -> list[str]:
    plain = str(text or "").strip()
    if not plain:
        return []
    if not enabled:
        return [plain]
    processed = plain
    if typo_enabled:
        processed = apply_chinese_typo(processed, error_rate=typo_rate, rng_seed=rng_seed)
    if split_enabled:
        return split_reply_segments(processed, max_chars=split_max_chars)
    return [processed]
