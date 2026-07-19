"""skill_table 某一档→ 纯文本说明。无 NoneBot 依赖，供脚本与插件共用。"""

from __future__ import annotations

import re
from typing import Any

_PLACEHOLDER_RE = re.compile(r"\{([^}]*)\}")


def blackboard_list_to_dict(bb: Any) -> dict[str, float | str]:
    """blackboard 数组 → key 映射。"""
    out: dict[str, float | str] = {}
    if not isinstance(bb, list):
        return out
    for row in bb:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key", "") or "").strip()
        if not key:
            continue
        vs = row.get("valueStr")
        if vs is not None and str(vs).strip() != "":
            out[key] = str(vs)
            continue
        val = row.get("value")
        if isinstance(val, bool):
            out[key] = float(val)
        elif isinstance(val, (int, float)):
            out[key] = float(val)
        elif isinstance(val, str) and val.strip():
            out[key] = val
    return out


def format_blackboard_value(val: float | str, fmt: str) -> str:
    """按游戏内格式串把数值格式化成展示片段。"""
    if isinstance(val, str):
        return val
    fmt = (fmt or "").strip()
    if not fmt:
        return _format_plain_number(float(val))
    if fmt.endswith("%"):
        body = (fmt[:-1].strip() or "0").lstrip("+")
        dec = 0
        if "." in body:
            dec = len(body.split(".", 1)[1])
        try:
            pct = float(val) * 100.0
        except (TypeError, ValueError, OverflowError):
            return ""
        if dec == 0:
            return f"{int(round(pct))}%"
        s = f"{pct:.{dec}f}"
        if dec > 0:
            s = s.rstrip("0").rstrip(".")
        return f"{s}%"
    if "." in fmt:
        dec = len(fmt.split(".", 1)[1])
        try:
            s = f"{float(val):.{dec}f}"
        except (TypeError, ValueError, OverflowError):
            return ""
        return s.rstrip("0").rstrip(".") if dec > 0 else s
    try:
        return str(int(round(float(val))))
    except (TypeError, ValueError, OverflowError):
        return ""


def _format_plain_number(val: float) -> str:
    """无格式占位时的默认数字串。"""
    try:
        v = float(val)
    except (TypeError, ValueError, OverflowError):
        return ""
    if abs(v) < 1e-12:
        return "0"
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    s = f"{v:.12g}"
    return s


def substitute_skill_placeholders(description: str, bb_map: dict[str, float | str]) -> str:
    """把 {key} / {key:0%} 等替换为黑板数值。"""

    def repl(m: re.Match[str]) -> str:
        inner = (m.group(1) or "").strip()
        if not inner:
            return ""
        if ":" in inner:
            key, fmt = inner.split(":", 1)
        else:
            key, fmt = inner, ""
        key = key.strip()
        fmt = fmt.strip()
        if key not in bb_map:
            return ""
        raw = bb_map[key]
        if isinstance(raw, str):
            return raw
        return format_blackboard_value(float(raw), fmt)

    return _PLACEHOLDER_RE.sub(repl, description)


def strip_ark_rich_tags(s: str) -> str:
    """去掉 <...> 富文本壳，保留可见字。"""
    t = s.replace("\\n", " ")
    for _ in range(200):
        nxt = re.sub(r"<[^>]+>", "", t)
        if nxt == t:
            break
        t = nxt
    return t


def render_skill_level_plain(
    description: str,
    blackboard: Any,
    *,
    max_len: int = 240,
) -> str:
    """单档 description + blackboard → 一行纯文本。"""
    if not description or not isinstance(description, str):
        return ""
    bb = blackboard_list_to_dict(blackboard)
    merged = substitute_skill_placeholders(description, bb)
    plain = strip_ark_rich_tags(merged)
    plain = re.sub(r"\s+", " ", plain).strip()
    if not plain:
        return ""
    if "{" in plain or "<" in plain or re.search(r"@ba\.|\$ba\.", plain):
        return ""
    if len(plain) > max_len:
        return plain[: max_len - 1] + "…"
    return plain


def skill_last_level_plain(skill_row: dict[str, Any], *, max_len: int = 240) -> str:
    """skill_table 一条技能 → 取最后一档纯文本。"""
    levels = skill_row.get("levels")
    if not isinstance(levels, list) or not levels:
        return ""
    last = levels[-1]
    if not isinstance(last, dict):
        return ""
    desc = str(last.get("description", "") or "")
    return render_skill_level_plain(desc, last.get("blackboard"), max_len=max_len)
