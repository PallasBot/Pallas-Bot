"""帮助图插件分组标签（extra.help_tag）。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

# 缺省分组；未声明 help_tag 的插件归入此桶
DEFAULT_HELP_TAG = "other"

# 已知标签展示名；未知 tag 用原字符串大写/原样
HELP_TAG_LABELS: dict[str, str] = {
    "core": "内核",
    "chat": "聊天",
    "fun": "娱乐",
    "tool": "工具",
    "ai": "AI",
    "admin": "管理",
    "other": "其他",
}

# 分组排序；未列入的 tag 按首次出现插在「其他」前
DEFAULT_HELP_TAG_ORDER: tuple[str, ...] = (
    "core",
    "chat",
    "ai",
    "fun",
    "tool",
    "admin",
    "other",
)


def normalize_help_tag(raw: object) -> str:
    text = str(raw or "").strip().lower()
    return text or DEFAULT_HELP_TAG


def help_tag_label(tag: str) -> str:
    key = normalize_help_tag(tag)
    if key in HELP_TAG_LABELS:
        return HELP_TAG_LABELS[key]
    return key.upper() if key.isascii() and key.islower() else key


def plugin_help_tag(plugin: Any) -> str:
    meta = getattr(plugin, "metadata", None)
    extra = getattr(meta, "extra", None) if meta is not None else None
    if isinstance(extra, dict):
        return normalize_help_tag(extra.get("help_tag"))
    return DEFAULT_HELP_TAG


def resolve_help_tag_overrides() -> dict[str, str]:
    """help 插件配置中的分组覆盖（插件名 → tag）。"""
    try:
        from .config import get_help_config

        raw = getattr(get_help_config(), "help_tag_overrides", None) or {}
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        name = str(key or "").strip()
        if not name:
            continue
        out[name] = normalize_help_tag(value)
    return out


def resolve_plugin_help_tag(plugin: Any, *, overrides: dict[str, str] | None = None) -> str:
    """生效分组：WebUI/配置覆盖 > metadata.extra.help_tag > other。"""
    name = str(getattr(plugin, "name", "") or "").strip()
    table = overrides if overrides is not None else resolve_help_tag_overrides()
    candidates: list[str] = []
    if name:
        candidates.append(name)
    try:
        from .plugin_legacy_names import canonical_plugin_name

        canon = canonical_plugin_name(name) if name else ""
    except Exception:
        canon = ""
    if canon:
        candidates.append(canon)
    mod = getattr(plugin, "module", None)
    mod_name = str(getattr(mod, "__name__", "") or "").strip()
    if mod_name:
        pkg = mod_name.rsplit(".", 1)[-1]
        if pkg:
            candidates.append(pkg)
    seen: set[str] = set()
    for key in candidates:
        if not key or key in seen:
            continue
        seen.add(key)
        if key in table:
            return table[key]
    return plugin_help_tag(plugin)


def help_tag_sort_rank(tag: str, *, order: tuple[str, ...] = DEFAULT_HELP_TAG_ORDER) -> tuple[int, int, str]:
    """分组排序键：已知 tag → 未知 tag → other。"""
    key = normalize_help_tag(tag)
    if key == DEFAULT_HELP_TAG:
        return (2, 0, key)
    try:
        return (0, order.index(key), key)
    except ValueError:
        return (1, 0, key)


def group_rows_by_help_tag[T](
    rows: Iterable[T],
    *,
    tag_of: Callable[[T], str],
    order: tuple[str, ...] = DEFAULT_HELP_TAG_ORDER,
) -> list[tuple[str, list[T]]]:
    """按标签分桶，返回 [(tag, rows), ...]，顺序稳定。"""
    buckets: dict[str, list[T]] = {}
    seen_order: list[str] = []
    for row in rows:
        tag = normalize_help_tag(tag_of(row))
        if tag not in buckets:
            buckets[tag] = []
            seen_order.append(tag)
        buckets[tag].append(row)

    ordered: list[tuple[str, list[T]]] = []
    used: set[str] = set()
    for tag in order:
        if tag == DEFAULT_HELP_TAG:
            continue
        if tag in buckets:
            ordered.append((tag, buckets[tag]))
            used.add(tag)
    for tag in seen_order:
        if tag in used or tag == DEFAULT_HELP_TAG:
            continue
        ordered.append((tag, buckets[tag]))
        used.add(tag)
    if DEFAULT_HELP_TAG in buckets:
        ordered.append((DEFAULT_HELP_TAG, buckets[DEFAULT_HELP_TAG]))
    return ordered
