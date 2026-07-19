"""WebUI 枚举选项展示用中文（内部键不变）。

通用配置 API 的 enum 字段应通过 field_meta / attach_choice_labels 附带 choice_labels；
WebUI 仅在缺失时回退到本地 FALLBACK 映射（见 Pallas-Bot-WebUI configFieldLabels.ts）。
"""

from __future__ import annotations

from typing import Any

# 跨字段复用的枚举值 → 展示文案。
GLOBAL_CHOICE_LABELS: dict[str, str] = {
    "auto": "自动",
    "true": "开启",
    "false": "关闭",
    "prefetch": "后台预取（推荐）",
    "sync": "当场联网查询",
    "local,community": "先本机，再共享池",
    "local": "只用本机",
    "local_first": "本地优先",
    "merge_counts": "合并使用次数",
    "local_only": "仅使用本机语料",
    "session": "本 worker 连接",
    "fleet": "协议实例名册",
    "connected": "全集群曾连 WS",
    "60": "1 分钟",
    "120": "2 分钟",
    "300": "5 分钟",
    "600": "10 分钟",
    "900": "15 分钟",
    "1800": "30 分钟",
    "3600": "1 小时",
}

# 键为 Pydantic / WebUI 字段名；值为 {内部枚举值: 展示文案}（可覆盖 GLOBAL）。
FIELD_CHOICE_LABELS: dict[str, dict[str, str]] = {
    "llm_repeater_mode": {
        "off": "关闭 AI 接话",
        "select": "命中语料时 AI 选句（推荐）",
        "select_polish_lite": "选句为主，少数回复轻润色",
        "select_fallback": "选句，语料缺失时现编",
        "fallback": "仅语料缺失时 AI 现编",
    },
    "llm_vector_retrieve": {
        "keyword": "仅关键词（默认）",
        "hybrid": "关键词 + 向量（推荐）",
        "embedding": "纯向量",
        "vector": "纯向量（同 embedding）",
    },
    "pallas_image_runtime_mode": {
        "ai_service_runtime": "AI 服务统一执行（推荐）",
        "plugin_runtime": "插件直连图像网关",
    },
}


def field_choice_labels(field_name: str, choices: list[str]) -> dict[str, str] | None:
    field_map = FIELD_CHOICE_LABELS.get(field_name, {})
    labels: dict[str, str] = {}
    for choice in choices:
        if choice in field_map:
            labels[choice] = field_map[choice]
        elif choice in GLOBAL_CHOICE_LABELS:
            labels[choice] = GLOBAL_CHOICE_LABELS[choice]
    return labels or None


def attach_choice_labels(row: dict[str, Any]) -> None:
    choices = row.get("choices")
    if not choices:
        return
    name = str(row.get("name") or "")
    labels = field_choice_labels(name, [str(c) for c in choices])
    if labels:
        row["choice_labels"] = labels
