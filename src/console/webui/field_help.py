"""通用配置字段说明三段式拼接。"""

from __future__ import annotations


def field_help(purpose: str, how: str, note: str = "") -> str:
    p = purpose.strip().rstrip("。")
    h = how.strip().rstrip("。")
    parts = [f"用途：{p}。", f"填写：{h}。"]
    if note.strip():
        parts.append(f"说明：{note.strip().rstrip('。')}。")
    return "\n".join(parts)


def normalize_field_description(desc: str) -> str:
    """插件等旧式单行 description 转为与通用配置一致的三段说明。"""
    d = (desc or "").strip()
    if not d:
        return ""
    if d.startswith("用途："):
        return d
    return field_help(d, "按字段类型填写；JSON 类须合法", "")
