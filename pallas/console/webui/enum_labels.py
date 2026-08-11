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
    "llm_vector_retrieve": {
        "keyword": "仅关键词",
        "hybrid": "关键词 + 向量（推荐）",
        "embedding": "纯向量",
        "vector": "纯向量（同 embedding）",
    },
    "llm_embedding_provider": {
        "": "自动（模型非 stub → 远程，否则占位）",
        "stub": "占位（关闭真实语义）",
        "openai": "远程（OpenAI 兼容 /embeddings）",
        "local": "本机（fastembed）",
    },
    "conversation_feature_level": {
        "": "自动推断（推荐）",
        "legacy_repeater": "仅语料规则（legacy）",
        "repeater_plus_decision": "语料 + 统一决策",
        "full_conversation_kernel": "决策 + 生成 + 反馈全链路",
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
        default = str(row.get("default"))
        if default in labels and "默认" not in labels[default]:
            labels[default] += "（默认）"
        row["choice_labels"] = labels
