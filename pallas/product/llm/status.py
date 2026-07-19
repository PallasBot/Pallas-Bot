"""LLM 运维状态摘要。"""

from __future__ import annotations

from typing import Any

from pallas.product.llm.config import LlmConfig, get_llm_config
from pallas.product.llm.model_admin import fetch_llm_task_stats, fetch_model_admin_status
from pallas.product.llm.task_metrics import llm_task_metrics_snapshot


def gate_skip_total(snapshot: dict[str, Any]) -> int:
    by_task = snapshot.get("by_task")
    if not isinstance(by_task, dict):
        return 0
    total = 0
    for row in by_task.values():
        if isinstance(row, dict):
            total += int(row.get("reply_gate_skip") or 0)
    return total


def gate_defer_total(snapshot: dict[str, Any]) -> int:
    by_task = snapshot.get("by_task")
    if not isinstance(by_task, dict):
        return 0
    total = 0
    for row in by_task.values():
        if isinstance(row, dict):
            total += int(row.get("reply_gate_defer") or 0)
    return total


async def build_llm_status_text(*, cfg: LlmConfig | None = None) -> str:
    c = cfg or get_llm_config()
    lines: list[str] = []
    try:
        admin = await fetch_model_admin_status(cfg=c)
    except Exception as exc:
        lines.append(f"模型状态：读取失败（{exc}）")
        admin = {}
    else:
        model = str(admin.get("model") or "未配置").strip()
        reachable = "可达" if admin.get("ai_reachable") else "不可达"
        lines.append(f"模型：{model}（AI {reachable}）")
        if admin.get("categorizer_enabled"):
            lines.append(f"请求分类：{admin.get('categorizer_model') or '小模型'}")
        if admin.get("moe_tier_routing"):
            lines.append("按难度选模型：已启用")

    bot_stats = llm_task_metrics_snapshot()
    lines.extend([
        f"今日任务（Bot）：提交成功 {bot_stats['totals'].get('submit_ok', 0)}",
        f"门控：跳过 {gate_skip_total(bot_stats)}，CD 排队 {gate_defer_total(bot_stats)}",
        (
            "开关："
            f"门控={'开' if c.llm_reply_gate_enabled else '关'}，"
            f"CD合并={'开' if c.llm_chat_queue_merge else '关'}，"
            f"记忆RAG={'开' if c.llm_memory_rag_enabled else '关'}，"
            "群内旧事=teach+群环境提炼"
        ),
    ])

    try:
        merged = await fetch_llm_task_stats(cfg=c)
    except Exception as exc:
        lines.append(f"AI 统计：读取失败（{exc}）")
        return "\n".join(lines)

    ai_body = merged.get("ai") if isinstance(merged.get("ai"), dict) else {}
    tokens = ai_body.get("tokens") if isinstance(ai_body.get("tokens"), dict) else {}
    if tokens:
        lines.append(
            "今日 Token（AI）："
            f"{int(tokens.get('total_tokens') or 0)} "
            f"（输入 {int(tokens.get('prompt_tokens') or 0)} / "
            f"输出 {int(tokens.get('completion_tokens') or 0)}）"
        )
    ai_totals = ai_body.get("totals") if isinstance(ai_body.get("totals"), dict) else {}
    if ai_totals:
        lines.append(f"AI 任务：成功 {int(ai_totals.get('task_ok') or 0)}，失败 {int(ai_totals.get('task_fail') or 0)}")
    if not merged.get("ai_reachable"):
        err = str(merged.get("error") or "不可达").strip()
        lines.append(f"AI 统计：{err}")
    return "\n".join(lines)
