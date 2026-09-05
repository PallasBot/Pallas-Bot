"""Distribution 名称规范化与来源前缀判定。"""

from __future__ import annotations

import re

PluginSourceKind = str  # "core" | "bundled" | "official" | "community" | "nonebot" | "local"


def normalize_distribution_name(name: str) -> str:
    """按 PyPI 规范统一 distribution 名称。"""
    return re.sub(r"[-_.]+", "-", str(name or "").strip().lower())


def classify_distribution_source(name: str) -> PluginSourceKind | None:
    normalized = normalize_distribution_name(name)
    if normalized.startswith("pallas-plugin-"):
        return "official"
    if normalized.startswith("nonebot-plugin-"):
        return "nonebot"
    return None
