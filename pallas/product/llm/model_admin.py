"""模型管理：Ollama 运行态与本地分档由 Bot 直连；Provider CRUD 走 providers_store。"""

from __future__ import annotations

from typing import Any

from nonebot import logger

from .config import LlmConfig, get_llm_config
from .task_metrics import cluster_llm_task_metrics_snapshot, llm_task_metrics_snapshot, today_key


def load_llm_daily_stats_range(*, start_day: str, end_day: str) -> tuple[list[dict[str, Any]], str, str]:
    from pallas.product.llm.llm_daily_stats_store import load_range

    return load_range(start_day=start_day, end_day=end_day)


def write_llm_daily_stats_side(day: str, side: str, snapshot: dict[str, Any]) -> None:
    from pallas.product.llm.llm_daily_stats_store import write_day_side

    write_day_side(day, side, snapshot)


def _tokens_snapshot_from_ledger(ledger_tokens: dict[str, Any]) -> dict[str, Any]:
    """账本日汇总 → ai.tokens 形状。"""
    return {
        "source": "ledger",
        "day_key": str(ledger_tokens.get("day_key") or ""),
        "prompt_tokens": int(ledger_tokens.get("prompt_tokens") or 0),
        "completion_tokens": int(ledger_tokens.get("completion_tokens") or 0),
        "cache_read_tokens": int(ledger_tokens.get("cache_read_tokens") or 0),
        "cache_write_tokens": int(ledger_tokens.get("cache_write_tokens") or 0),
        "total_tokens": int(ledger_tokens.get("total_tokens") or 0),
        "cost_total": float(ledger_tokens.get("cost_total") or 0),
        "cost_currency": str(ledger_tokens.get("cost_currency") or ""),
        "by_task": ledger_tokens.get("by_task") if isinstance(ledger_tokens.get("by_task"), dict) else {},
        "by_provider": ledger_tokens.get("by_provider") if isinstance(ledger_tokens.get("by_provider"), dict) else {},
        "by_model": ledger_tokens.get("by_model") if isinstance(ledger_tokens.get("by_model"), dict) else {},
        "by_hour": {},
    }


def _dimension_stats_from_ledger_breakdown(raw: Any) -> dict[str, dict[str, Any]]:
    """账本分桶 → provider_stats / model_stats 形状（仅有成功记账的请求次数）。"""
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(raw, dict):
        return out
    for key, metrics in raw.items():
        name = str(key or "").strip()
        if not name or not isinstance(metrics, dict):
            continue
        requests = int(metrics.get("requests") or 0)
        if requests <= 0:
            continue
        out[name] = {
            "requests": requests,
            "succeeded": requests,
            "failed": 0,
            "total_latency_ms": 0,
            "avg_latency_ms": None,
            "recent_failure_class": None,
        }
    return out


def _merge_dimension_stats_prefer_complete(live: Any, from_ledger: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """实时缺桶或次数偏少时，用账本请求次数补全。"""
    out: dict[str, Any] = dict(live) if isinstance(live, dict) else {}
    for key, row in from_ledger.items():
        cur = out.get(key) if isinstance(out.get(key), dict) else None
        led_req = int(row.get("requests") or 0)
        if not cur:
            out[key] = dict(row)
            continue
        live_req = int(cur.get("requests") or 0)
        if led_req <= live_req:
            continue
        failed = int(cur.get("failed") or 0)
        succeeded = int(cur.get("succeeded") or 0)
        if failed > 0 and succeeded + failed == live_req:
            # 保留失败计数，把差额记为成功
            succeeded = max(succeeded, led_req - failed)
        else:
            succeeded = max(succeeded, led_req)
        out[key] = {
            **cur,
            "requests": led_req,
            "succeeded": succeeded,
            "failed": failed,
            "avg_latency_ms": (int(cur.get("total_latency_ms") or 0) / led_req) if led_req > 0 else None,
        }
    return out


def _enrich_ai_snapshot_from_ledger(
    ai: dict[str, Any] | None,
    *,
    day_key: str,
) -> dict[str, Any] | None:
    """当日 token / 提供方调用优先用请求账本补全（跨重启更完整），保留实时 by_hour。"""
    if not isinstance(ai, dict):
        return ai
    try:
        from pallas.product.llm.usage_ledger import aggregate_day_from_ledger

        ledger = aggregate_day_from_ledger(day_key)
    except Exception:
        return ai
    if not isinstance(ledger, dict):
        return ai
    tokens = _tokens_snapshot_from_ledger(ledger)
    live = ai.get("tokens") if isinstance(ai.get("tokens"), dict) else {}
    by_hour = live.get("by_hour") if isinstance(live.get("by_hour"), dict) else None
    if by_hour:
        tokens = {**tokens, "by_hour": by_hour}
    provider_stats = _merge_dimension_stats_prefer_complete(
        ai.get("provider_stats"),
        _dimension_stats_from_ledger_breakdown(ledger.get("by_provider")),
    )
    model_stats = _merge_dimension_stats_prefer_complete(
        ai.get("model_stats"),
        _dimension_stats_from_ledger_breakdown(ledger.get("by_model")),
    )
    return {
        **ai,
        "tokens": tokens,
        "provider_stats": provider_stats,
        "model_stats": model_stats,
    }


# 兼容旧名
_prefer_ledger_tokens_on_ai = _enrich_ai_snapshot_from_ledger


def _overlay_ledger_on_history_rows(
    rows: list[dict[str, Any]],
    *,
    start_day: str,
    end_day: str,
) -> list[dict[str, Any]]:
    """优先用请求级账本覆盖日 token；无账本时丢弃明显脏的日汇总。"""
    from pallas.product.llm.usage_ledger import aggregate_ledger_range, tokens_look_corrupt

    try:
        ledger_by_day = aggregate_ledger_range(start_day=start_day, end_day=end_day)
    except Exception:
        ledger_by_day = {}
    out: list[dict[str, Any]] = []
    for hist_row in rows:
        if not isinstance(hist_row, dict):
            continue
        row = dict(hist_row)
        row_date = str(row.get("date") or "").strip()[:10]
        ai = dict(row["ai"]) if isinstance(row.get("ai"), dict) else {}
        ledger = ledger_by_day.get(row_date) if row_date else None
        if isinstance(ledger, dict):
            tokens = _tokens_snapshot_from_ledger(ledger)
            provider_stats = _merge_dimension_stats_prefer_complete(
                ai.get("provider_stats"),
                _dimension_stats_from_ledger_breakdown(ledger.get("by_provider")),
            )
            model_stats = _merge_dimension_stats_prefer_complete(
                ai.get("model_stats"),
                _dimension_stats_from_ledger_breakdown(ledger.get("by_model")),
            )
            ai = {
                **ai,
                "tokens": tokens,
                "provider_stats": provider_stats,
                "model_stats": model_stats,
                "source": ai.get("source") or "bot",
            }
            row["ai"] = ai
            out.append(row)
            continue
        tokens = ai.get("tokens") if isinstance(ai.get("tokens"), dict) else None
        if tokens_look_corrupt(tokens):
            # 保留 gates/rag/images 等，仅清空异常 token
            ai = {
                **ai,
                "tokens": {
                    "source": "sanitized",
                    "day_key": row_date,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "cache_read_tokens": 0,
                    "cache_write_tokens": 0,
                    "total_tokens": 0,
                    "cost_total": 0.0,
                    "cost_currency": "",
                    "by_task": {},
                    "by_provider": {},
                    "by_model": {},
                    "by_hour": {},
                },
            }
            row["ai"] = ai
        out.append(row)
    # 账本有、日 JSON 无的日期也补上
    known = {str(r.get("date") or "").strip()[:10] for r in out}
    for day_key, ledger in sorted(ledger_by_day.items()):
        if day_key in known or not isinstance(ledger, dict):
            continue
        out.append({
            "date": day_key,
            "bot": None,
            "ai": {
                "source": "bot",
                "day_key": day_key,
                "tokens": _tokens_snapshot_from_ledger(ledger),
                "provider_stats": _dimension_stats_from_ledger_breakdown(ledger.get("by_provider")),
                "model_stats": _dimension_stats_from_ledger_breakdown(ledger.get("by_model")),
            },
        })
    out.sort(key=lambda r: str(r.get("date") or ""))
    return out


def _ai_snapshot_collecting(snapshot: dict[str, Any] | None) -> bool:
    if not isinstance(snapshot, dict):
        return False
    by_task = snapshot.get("by_task")
    if isinstance(by_task, dict) and bool(by_task):
        return True
    tokens = snapshot.get("tokens")
    if isinstance(tokens, dict):
        if any(
            int(tokens.get(key) or 0) > 0
            for key in (
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "cache_read_tokens",
                "cache_write_tokens",
            )
        ):
            return True
    provider_stats = snapshot.get("provider_stats")
    if isinstance(provider_stats, dict) and bool(provider_stats):
        return True
    model_stats = snapshot.get("model_stats")
    if isinstance(model_stats, dict) and bool(model_stats):
        return True
    images = snapshot.get("images")
    if isinstance(images, dict):
        return (
            any(int(images.get(key) or 0) > 0 for key in ("ok_count", "fail_count", "image_count"))
            or bool(images.get("by_model"))
            or bool(images.get("by_provider"))
        )
    rag = snapshot.get("rag")
    if isinstance(rag, dict):
        if int(rag.get("hit_count") or 0) > 0 or int(rag.get("miss_count") or 0) > 0:
            return True
    memory_rag = snapshot.get("memory_rag")
    if isinstance(memory_rag, dict):
        return int(memory_rag.get("hit_count") or 0) > 0 or int(memory_rag.get("miss_count") or 0) > 0
    return False


def _normalize_images_slice(raw: Any, *, day_key: str = "", source: str = "draw_plugin") -> dict[str, Any]:
    images_raw = raw if isinstance(raw, dict) else {}
    return {
        "source": str(images_raw.get("source") or source),
        "day_key": str(images_raw.get("day_key") or day_key or ""),
        "updated_at": images_raw.get("updated_at"),
        "ok_count": int(images_raw.get("ok_count") or 0),
        "fail_count": int(images_raw.get("fail_count") or 0),
        "image_count": int(images_raw.get("image_count") or 0),
        "cost_total": float(images_raw.get("cost_total") or 0),
        "cost_currency": str(images_raw.get("cost_currency") or ""),
        "by_gateway": images_raw.get("by_gateway") if isinstance(images_raw.get("by_gateway"), dict) else {},
        "by_provider": images_raw.get("by_provider") if isinstance(images_raw.get("by_provider"), dict) else {},
        "by_model": images_raw.get("by_model") if isinstance(images_raw.get("by_model"), dict) else {},
    }


def _normalize_rag_slice(raw: Any, *, day_key: str = "", source: str = "bot") -> dict[str, Any]:
    rag_raw = raw if isinstance(raw, dict) else {}
    hit = int(rag_raw.get("hit_count") or 0)
    miss = int(rag_raw.get("miss_count") or 0)
    total = hit + miss
    rate = float(rag_raw.get("hit_rate") or 0)
    if total > 0 and rate <= 0:
        rate = round(100.0 * hit / total, 1)
    by_document = rag_raw.get("by_document") if isinstance(rag_raw.get("by_document"), dict) else {}
    by_source = rag_raw.get("by_source") if isinstance(rag_raw.get("by_source"), dict) else {}
    return {
        "source": str(rag_raw.get("source") or source),
        "day_key": str(rag_raw.get("day_key") or day_key or ""),
        "updated_at": rag_raw.get("updated_at"),
        "hit_count": hit,
        "miss_count": miss,
        "hit_rate": rate,
        "by_document": {str(k): int(v or 0) for k, v in by_document.items() if str(k).strip()},
        "by_source": {str(k): int(v or 0) for k, v in by_source.items() if str(k).strip()},
    }


def _normalize_gates_slice(raw: Any) -> dict[str, int]:
    gates = raw if isinstance(raw, dict) else {}
    return {
        "skip": int(gates.get("skip") or 0),
        "defer": int(gates.get("defer") or 0),
        "proceed": int(gates.get("proceed") or 0),
    }


def _gates_from_bot_snapshot(bot_snap: dict[str, Any] | None) -> dict[str, int]:
    raw = bot_snap if isinstance(bot_snap, dict) else {}
    totals = raw.get("totals") if isinstance(raw.get("totals"), dict) else {}
    skip = int(totals.get("reply_gate_skip") or 0)
    defer = int(totals.get("reply_gate_defer") or 0)
    proceed = int(totals.get("reply_gate_proceed") or 0)
    if skip or defer or proceed:
        return {"skip": skip, "defer": defer, "proceed": proceed}
    by_task = raw.get("by_task") if isinstance(raw.get("by_task"), dict) else {}
    for row in by_task.values():
        if not isinstance(row, dict):
            continue
        skip += int(row.get("reply_gate_skip") or 0)
        defer += int(row.get("reply_gate_defer") or 0)
        proceed += int(row.get("reply_gate_proceed") or 0)
    return {"skip": skip, "defer": defer, "proceed": proceed}


def _normalize_ai_task_stats_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    raw = snapshot if isinstance(snapshot, dict) else {}
    by_task = raw.get("by_task") if isinstance(raw.get("by_task"), dict) else {}
    totals = raw.get("totals") if isinstance(raw.get("totals"), dict) else {}
    tokens_raw = raw.get("tokens") if isinstance(raw.get("tokens"), dict) else {}
    images_raw = raw.get("images") if isinstance(raw.get("images"), dict) else {}
    rag_raw = raw.get("rag") if isinstance(raw.get("rag"), dict) else {}
    memory_rag_raw = raw.get("memory_rag") if isinstance(raw.get("memory_rag"), dict) else {}
    gates_raw = raw.get("gates") if isinstance(raw.get("gates"), dict) else {}
    task_ok = int(totals.get("task_ok") or 0)
    task_fail = int(totals.get("task_fail") or 0)
    if task_ok == 0 and task_fail == 0:
        for row in by_task.values():
            if not isinstance(row, dict):
                continue
            task_ok += int(row.get("task_ok") or 0)
            task_fail += int(row.get("task_fail") or 0)
    state_counts = raw.get("state_counts") if isinstance(raw.get("state_counts"), dict) else {}
    failure_counts = raw.get("failure_counts") if isinstance(raw.get("failure_counts"), dict) else {}
    provider_stats = _normalize_dimension_stats(raw.get("provider_stats"))
    model_stats = _normalize_dimension_stats(raw.get("model_stats"))
    if task_ok == 0 and task_fail == 0:
        for row in provider_stats.values():
            task_ok += int(row.get("succeeded") or 0)
            task_fail += int(row.get("failed") or 0)
    day_key = str(raw.get("day_key") or "")
    by_hour = tokens_raw.get("by_hour") if isinstance(tokens_raw.get("by_hour"), dict) else {}
    try:
        from pallas.product.llm.token_cost import enrich_tokens_cost_fields

        tokens_enriched = enrich_tokens_cost_fields(tokens_raw)
    except Exception:
        tokens_enriched = dict(tokens_raw)
    return {
        **raw,
        "by_task": by_task,
        "totals": totals,
        "state_counts": {
            "queued": int(state_counts.get("queued") or 0),
            "running": int(state_counts.get("running") or 0),
            "succeeded": int(state_counts.get("succeeded") or task_ok),
            "failed": int(state_counts.get("failed") or task_fail),
        },
        "failure_counts": {str(k): int(v or 0) for k, v in failure_counts.items()},
        "provider_stats": provider_stats,
        "model_stats": model_stats,
        "tokens": {
            "source": str(tokens_enriched.get("source") or raw.get("source") or "ai"),
            "day_key": str(tokens_enriched.get("day_key") or day_key or ""),
            "updated_at": tokens_enriched.get("updated_at"),
            "prompt_tokens": int(tokens_enriched.get("prompt_tokens") or 0),
            "completion_tokens": int(tokens_enriched.get("completion_tokens") or 0),
            "cache_read_tokens": int(tokens_enriched.get("cache_read_tokens") or 0),
            "cache_write_tokens": int(tokens_enriched.get("cache_write_tokens") or 0),
            "total_tokens": int(tokens_enriched.get("total_tokens") or 0)
            or (int(tokens_enriched.get("prompt_tokens") or 0) + int(tokens_enriched.get("completion_tokens") or 0)),
            "cost_total": float(tokens_enriched.get("cost_total") or 0),
            "cost_currency": str(tokens_enriched.get("cost_currency") or ""),
            "by_task": tokens_enriched.get("by_task") if isinstance(tokens_enriched.get("by_task"), dict) else {},
            "by_provider": tokens_enriched.get("by_provider")
            if isinstance(tokens_enriched.get("by_provider"), dict)
            else {},
            "by_model": tokens_enriched.get("by_model") if isinstance(tokens_enriched.get("by_model"), dict) else {},
            "by_hour": by_hour,
        },
        "images": _normalize_images_slice(images_raw, day_key=day_key),
        "rag": _normalize_rag_slice(rag_raw, day_key=day_key, source=str(raw.get("source") or "bot")),
        "memory_rag": _normalize_rag_slice(memory_rag_raw, day_key=day_key, source=str(raw.get("source") or "bot")),
        "gates": _normalize_gates_slice(gates_raw),
    }


def _normalize_dimension_stats(raw: Any) -> dict[str, dict[str, Any]]:
    """统一 provider/model 维度统计为控制台字段（requests/succeeded/failed/avg_latency_ms）。"""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, row in raw.items():
        if not isinstance(row, dict):
            continue
        name = str(key or "").strip()
        if not name:
            continue
        succeeded = int(row.get("succeeded") or row.get("ok") or 0)
        failed = int(row.get("failed") or row.get("fail") or 0)
        requests = int(row.get("requests") or 0) or (succeeded + failed)
        total_latency = int(row.get("total_latency_ms") or 0)
        avg_raw = row.get("avg_latency_ms")
        if avg_raw is None and requests > 0 and total_latency > 0:
            avg: float | None = total_latency / requests
        elif avg_raw is None:
            avg = None
        else:
            try:
                avg = float(avg_raw)
            except (TypeError, ValueError):
                avg = None
        recent = str(row.get("recent_failure_class") or "").strip()
        out[name] = {
            "requests": requests,
            "succeeded": succeeded,
            "failed": failed,
            "total_latency_ms": total_latency,
            "avg_latency_ms": avg,
            "recent_failure_class": recent or None,
        }
    return out


def _normalize_historical_ai_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    normalized = _normalize_ai_task_stats_snapshot(snapshot)
    classification = snapshot.get("classification") if isinstance(snapshot, dict) else None
    if normalized["failure_counts"] or normalized["provider_stats"] or normalized["model_stats"]:
        return normalized
    if not isinstance(classification, dict):
        return normalized
    return {
        **normalized,
        "failure_counts": (
            dict(classification.get("failure_counts")) if isinstance(classification.get("failure_counts"), dict) else {}
        ),
        "provider_stats": _normalize_dimension_stats(classification.get("provider_stats")),
        "model_stats": _normalize_dimension_stats(classification.get("model_stats")),
    }


def _latest_historical_ai_snapshot(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    for row in reversed(rows):
        ai = row.get("ai")
        if isinstance(ai, dict) and ai:
            return _normalize_historical_ai_snapshot(ai)
    return None


def _bot_tokens_have_usage(tokens: dict[str, Any] | None) -> bool:
    if not isinstance(tokens, dict):
        return False
    return bool(
        int(tokens.get("total_tokens") or 0) > 0
        or int(tokens.get("cache_read_tokens") or 0) > 0
        or int(tokens.get("cache_write_tokens") or 0) > 0
        or tokens.get("by_task")
        or tokens.get("by_model")
        or tokens.get("by_provider")
    )


def _ai_has_live_llm_metrics(snapshot: dict[str, Any] | None) -> bool:
    """是否已有 live LLM 侧指标（不含 images；画画用量不应挡住历史 token 回退）。"""
    if not isinstance(snapshot, dict) or not snapshot:
        return False
    tokens = snapshot.get("tokens")
    if isinstance(tokens, dict) and _bot_tokens_have_usage(tokens):
        return True
    by_task = snapshot.get("by_task")
    if isinstance(by_task, dict) and bool(by_task):
        return True
    state_counts = snapshot.get("state_counts") if isinstance(snapshot.get("state_counts"), dict) else {}
    if any(int(state_counts.get(key) or 0) > 0 for key in ("queued", "running", "succeeded", "failed")):
        return True
    if isinstance(snapshot.get("provider_stats"), dict) and bool(snapshot.get("provider_stats")):
        return True
    if isinstance(snapshot.get("model_stats"), dict) and bool(snapshot.get("model_stats")):
        return True
    if isinstance(snapshot.get("failure_counts"), dict) and bool(snapshot.get("failure_counts")):
        return True
    return False


def _resolve_local_provider_base(*, cfg: LlmConfig | None = None) -> str:
    from pallas.product.llm.providers_store import find_provider, load_providers_document, resolve_provider_base_url

    doc = load_providers_document()
    for row in doc.get("providers") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("kind") or "").strip().lower() != "local":
            continue
        if row.get("enabled", True) is False:
            continue
        url = resolve_provider_base_url(row)
        if url:
            return url
    local = find_provider("local", doc=doc)
    if local is not None:
        url = resolve_provider_base_url(local)
        if url:
            return url
    return _resolve_local_ollama_base_url("", cfg=cfg)


async def fetch_model_admin_status(*, cfg: LlmConfig | None = None, timeout_sec: float = 15.0) -> dict[str, Any]:
    from pallas.product.llm.local_routing_store import export_local_routing_for_api, load_local_routing_document
    from pallas.product.llm.ollama_admin import get_runtime_model_name, get_runtime_num_gpu, ping_ollama
    from pallas.product.llm.providers_store import export_providers_for_api

    c = cfg or get_llm_config()
    local_doc = load_local_routing_document()
    exported = export_local_routing_for_api(doc=local_doc)
    providers_export = export_providers_for_api()
    base = _resolve_local_provider_base(cfg=c)
    reachable = await ping_ollama(base, timeout_sec=min(timeout_sec, 5.0)) if base else False
    model = get_runtime_model_name(fallback=str(local_doc.get("llm_model") or "").strip())
    status: dict[str, Any] = {
        "model": model,
        "ai_reachable": reachable,
        "ollama_reachable": reachable,
        "llm_chat_enabled": c.llm_chat_enabled,
        "health_url": f"{base.rstrip('/')}/api/tags" if base else "",
        "error": "" if reachable else ("缺少本地 Ollama Base URL" if not base else "本地 Ollama 不可达"),
        "local_multi_model_enabled": bool(local_doc.get("local_multi_model_enabled")),
        "local_task_models": dict(exported.get("task_models") or {}),
        "local_moe_models": dict(exported.get("moe_models") or {}),
        "moe_tier_routing": bool(local_doc.get("local_multi_model_enabled")),
        "provider_status": providers_export.get("providers") if isinstance(providers_export, dict) else [],
        "task_routing": (providers_export.get("routing") or {}).get("tasks")
        if isinstance(providers_export, dict)
        else {},
    }
    num_gpu = get_runtime_num_gpu()
    if num_gpu is not None:
        status["num_gpu"] = num_gpu
    if reachable and not model:
        status["error"] = "当前未配置模型"
    return status


async def get_runtime_model(*, cfg: LlmConfig | None = None, timeout_sec: float = 30.0) -> str:
    status = await fetch_model_admin_status(cfg=cfg, timeout_sec=timeout_sec)
    if not status.get("ollama_reachable") and not status.get("ai_reachable"):
        msg = str(status.get("error") or "本地 Ollama 不可达")
        raise RuntimeError(msg)
    model = str(status.get("model") or "").strip()
    if not model:
        raise RuntimeError("当前未配置模型")
    return model


async def switch_runtime_model(
    model: str,
    *,
    pull: bool = True,
    cfg: LlmConfig | None = None,
    timeout_sec: float = 600.0,
) -> dict[str, Any]:
    from pallas.product.llm.local_routing_store import load_local_routing_document, save_local_routing_document
    from pallas.product.llm.ollama_admin import (
        get_runtime_num_gpu,
        pull_ollama_model,
        set_runtime_model_name,
    )
    from pallas.product.llm.provider_client import LlmProviderError

    name = model.strip()
    if not name:
        raise ValueError("模型名不能为空")
    c = cfg or get_llm_config()
    base = _resolve_local_provider_base(cfg=c)
    if not base:
        raise RuntimeError("缺少本地 Ollama Base URL")
    if pull:
        try:
            await pull_ollama_model(base, name, timeout_sec=timeout_sec)
        except LlmProviderError as exc:
            raise RuntimeError(f"拉取模型失败: {exc}") from exc
    set_runtime_model_name(name)
    doc = load_local_routing_document()
    doc["llm_model"] = name
    save_local_routing_document(doc)
    result: dict[str, Any] = {"model": name}
    num_gpu = get_runtime_num_gpu()
    if num_gpu is not None:
        result["num_gpu"] = num_gpu
    logger.info("llm model switched via Bot Ollama: model={} pull={} num_gpu={}", name, pull, result.get("num_gpu"))
    return result


async def set_runtime_num_gpu(
    num_gpu: int,
    *,
    cfg: LlmConfig | None = None,
    timeout_sec: float = 60.0,
) -> dict[str, Any]:
    from pallas.product.llm.ollama_admin import get_runtime_model_name, set_runtime_num_gpu_value

    del timeout_sec
    if num_gpu < 0:
        raise ValueError("GPU 层数不能为负数")
    c = cfg or get_llm_config()
    set_runtime_num_gpu_value(num_gpu)
    from pallas.product.llm.local_routing_store import load_local_routing_document

    model = get_runtime_model_name(fallback=str(load_local_routing_document().get("llm_model") or "").strip())
    result: dict[str, Any] = {"num_gpu": num_gpu}
    if model:
        result["model"] = model
    logger.info("llm num_gpu set via Bot: num_gpu={} model={}", num_gpu, model)
    _ = c
    return result


async def reload_runtime_model(*, cfg: LlmConfig | None = None, timeout_sec: float = 60.0) -> dict[str, Any]:
    from pallas.product.llm.local_routing_store import load_local_routing_document
    from pallas.product.llm.ollama_admin import get_runtime_num_gpu, set_runtime_model_name

    del timeout_sec
    c = cfg or get_llm_config()
    doc = load_local_routing_document()
    model = str(doc.get("llm_model") or "").strip()
    if model:
        set_runtime_model_name(model)
    result: dict[str, Any] = {"model": model}
    num_gpu = get_runtime_num_gpu()
    if num_gpu is not None:
        result["num_gpu"] = num_gpu
    logger.info("llm model reloaded from local routing: model={} num_gpu={}", model, result.get("num_gpu"))
    _ = c
    return result


async def unload_runtime_model(*, cfg: LlmConfig | None = None, timeout_sec: float = 60.0) -> None:
    from pallas.product.llm.local_routing_store import load_local_routing_document
    from pallas.product.llm.ollama_admin import get_runtime_model_name, unload_ollama_model
    from pallas.product.llm.provider_client import LlmProviderError

    c = cfg or get_llm_config()
    base = _resolve_local_provider_base(cfg=c)
    if not base:
        raise RuntimeError("缺少本地 Ollama Base URL")
    model = get_runtime_model_name(fallback=str(load_local_routing_document().get("llm_model") or "").strip())
    try:
        await unload_ollama_model(base, model, timeout_sec=timeout_sec)
    except LlmProviderError as exc:
        raise RuntimeError(f"卸载模型失败: {exc}") from exc
    logger.info("llm model unloaded via Bot Ollama: model={}", model)


async def fetch_local_routing_config(
    *,
    cfg: LlmConfig | None = None,
    timeout_sec: float = 15.0,
) -> dict[str, Any]:
    del cfg, timeout_sec
    from pallas.product.llm.local_routing_store import export_local_routing_for_api

    return export_local_routing_for_api()


async def save_local_routing_config(
    document: dict[str, Any],
    *,
    cfg: LlmConfig | None = None,
    timeout_sec: float = 30.0,
) -> dict[str, Any]:
    del cfg, timeout_sec
    from pallas.product.llm.local_routing_store import save_local_routing_document
    from pallas.product.llm.ollama_admin import set_runtime_model_name

    payload = save_local_routing_document(document if isinstance(document, dict) else {})
    model = str(payload.get("llm_model") or "").strip()
    if model:
        set_runtime_model_name(model)
    logger.info("llm local routing config saved: path={}", payload.get("env_file"))
    return payload


async def fetch_providers_config(*, cfg: LlmConfig | None = None, timeout_sec: float = 15.0) -> dict[str, Any]:
    del cfg, timeout_sec
    from pallas.product.llm.providers_store import export_providers_for_api

    return export_providers_for_api()


async def save_providers_config(
    document: dict[str, Any],
    *,
    cfg: LlmConfig | None = None,
    timeout_sec: float = 30.0,
) -> dict[str, Any]:
    del cfg, timeout_sec
    from pallas.product.llm.config import clear_llm_config_cache
    from pallas.product.llm.providers_store import save_providers_document
    from pallas.product.llm.task_routing import clear_task_route_cache

    payload = save_providers_document(document)
    clear_llm_config_cache()
    clear_task_route_cache()
    return payload


async def upsert_provider_config(
    provider: dict[str, Any],
    *,
    cfg: LlmConfig | None = None,
    timeout_sec: float = 30.0,
) -> dict[str, Any]:
    del cfg, timeout_sec
    from pallas.product.llm.config import clear_llm_config_cache
    from pallas.product.llm.providers_store import upsert_provider_row
    from pallas.product.llm.task_routing import clear_task_route_cache

    payload = upsert_provider_row(provider)
    clear_llm_config_cache()
    clear_task_route_cache()
    return payload


def _resolve_local_ollama_base_url(base_url: str = "", *, cfg: LlmConfig | None = None) -> str:
    from pallas.core.foundation.config.repo_settings import repo_env_raw_value

    raw = (base_url or "").strip()
    if raw:
        return raw
    for key in ("LLM_BACKEND_URL", "OLLAMA_URL", "OLLAMA_HOST"):
        val = str(repo_env_raw_value(key) or "").strip()
        if val:
            return val
    c = cfg or get_llm_config()
    kernel = str(c.llm_base_url or "").strip()
    if kernel:
        return kernel
    return "http://127.0.0.1:11434"


async def fetch_provider_models(
    provider_id: str,
    *,
    base_url: str = "",
    api_key: str = "",
    api_key_env: str = "",
    kind: str = "",
    request_method: str = "",
    cfg: LlmConfig | None = None,
    timeout_sec: float = 15.0,
) -> dict[str, Any]:
    """Bot 直连上游发现模型列表，不经 AI Runtime。"""
    import os

    from pallas.product.llm.provider_client import (
        LlmProviderError,
        list_ollama_tag_models,
        list_openai_compatible_models,
        resolve_request_method,
    )
    from pallas.product.llm.providers_store import provider_request_method

    c = cfg or get_llm_config()
    pid = str(provider_id or "").strip() or "remote"
    kind_norm = (kind or "").strip().lower()
    if not kind_norm:
        kind_norm = "local" if pid == "local" else "remote"

    key = (api_key or "").strip()
    env_name = (api_key_env or "").strip()
    if not key and env_name:
        key = str(os.environ.get(env_name) or "").strip()

    url = (base_url or "").strip()
    method = str(request_method or "").strip()
    stored = None
    if not url or not key or not method:
        from pallas.product.llm.providers_store import (
            find_provider,
            resolve_provider_api_key,
            resolve_provider_base_url,
        )

        stored = find_provider(pid)
        if stored is not None:
            url = url or resolve_provider_base_url(stored)
            key = key or resolve_provider_api_key(stored)
            if not kind and str(stored.get("kind") or "").strip():
                kind_norm = str(stored.get("kind") or "").strip().lower() or kind_norm
            if not method:
                method = provider_request_method(stored)

    if kind_norm == "local":
        url = _resolve_local_ollama_base_url(url, cfg=c)
        try:
            models = await list_ollama_tag_models(url, timeout_sec=timeout_sec)
        except LlmProviderError as exc:
            return {
                "provider_id": pid,
                "ok": False,
                "models": [],
                "source": "ollama",
                "error": str(exc),
            }
        return {
            "provider_id": pid,
            "ok": True,
            "models": models,
            "source": "ollama",
            "error": "",
        }

    if not url:
        url = str(c.llm_base_url or "").strip()
        if not key:
            key = str(c.llm_api_key or "").strip()
    if not url:
        return {
            "provider_id": pid,
            "ok": False,
            "models": [],
            "source": "openai",
            "error": "缺少 Base URL，请填写后刷新",
        }
    if not key:
        return {
            "provider_id": pid,
            "ok": False,
            "models": [],
            "source": "openai",
            "error": "缺少 API Key，请填写后刷新（已保存密钥时请重新输入一次）",
        }

    effective_method = resolve_request_method(method, url)
    source = "anthropic" if effective_method == "anthropic_messages" else "openai"
    try:
        models = await list_openai_compatible_models(
            url,
            key,
            timeout_sec=timeout_sec,
            request_method=effective_method,
        )
    except LlmProviderError as exc:
        return {
            "provider_id": pid,
            "ok": False,
            "models": [],
            "source": source,
            "error": str(exc),
        }
    return {
        "provider_id": pid,
        "ok": True,
        "models": models,
        "source": source,
        "error": "",
    }


async def probe_provider(
    provider_id: str,
    *,
    cfg: LlmConfig | None = None,
    timeout_sec: float = 15.0,
) -> dict[str, Any]:
    import time

    from pallas.product.llm.providers_store import find_provider, resolve_provider_api_key, resolve_provider_base_url

    del cfg
    pid = str(provider_id or "").strip()
    row = find_provider(pid)
    if row is None:
        return {
            "provider_id": pid,
            "reachable": False,
            "latency_ms": None,
            "error": "提供方不存在或已禁用",
        }
    kind = str(row.get("kind") or "remote").strip().lower()
    started = time.monotonic()
    discovered = await fetch_provider_models(
        pid,
        base_url=resolve_provider_base_url(row),
        api_key=resolve_provider_api_key(row),
        api_key_env=str(row.get("api_key_env") or "").strip(),
        kind=kind,
        request_method=str(row.get("request_method") or "").strip(),
        timeout_sec=timeout_sec,
    )
    latency_ms = int((time.monotonic() - started) * 1000)
    ok = bool(discovered.get("ok"))
    return {
        "provider_id": pid,
        "reachable": ok,
        "latency_ms": latency_ms if ok else None,
        "error": "" if ok else str(discovered.get("error") or "不可达"),
        "models": discovered.get("models") if ok else [],
    }


async def fetch_llm_task_stats(
    *,
    cfg: LlmConfig | None = None,
    timeout_sec: float = 8.0,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    """聚合 Bot 任务计数与内核本地 token 计量（LLM 已下沉，不再请求 AI Runtime /api/llm/stats）。"""
    from datetime import date, timedelta

    _ = (cfg, timeout_sec)
    try:
        from pallas.core.platform.shard import context as shard_ctx

        bot_snap = (
            cluster_llm_task_metrics_snapshot()
            if shard_ctx.sharding_active() and shard_ctx.is_hub()
            else llm_task_metrics_snapshot()
        )
    except Exception:
        bot_snap = llm_task_metrics_snapshot()
    payload: dict[str, Any] = {
        "bot": bot_snap,
        "ai": {},
        # LLM 计量在 Bot 内核；字段名保留兼容控制台，表示内核计量可读。
        "ai_reachable": True,
        "persistence": {
            "store_file": "llm_daily_stats.json",
            "bot_collecting": bool(bot_snap.get("by_task")),
            "bot_day_key": bot_snap.get("day_key") or today_key(),
        },
    }
    try:
        from pallas.core.platform.shard import context as shard_ctx
        from pallas.product.llm.token_metrics import (
            cluster_llm_token_metrics_snapshot,
            flush_stats_sync,
            llm_token_metrics_snapshot,
        )

        flush_stats_sync()
        if shard_ctx.sharding_active() and shard_ctx.is_hub():
            bot_tokens = cluster_llm_token_metrics_snapshot()
        else:
            bot_tokens = llm_token_metrics_snapshot(include_persisted=True)
    except Exception as exc:
        bot_tokens = {}
        payload["ai_reachable"] = False
        payload["error"] = f"读取 Bot 本地 token 计量失败: {exc}"

    if _bot_tokens_have_usage(bot_tokens):
        merged_ai = {
            "tokens": bot_tokens,
            "day_key": bot_tokens.get("day_key") or bot_snap.get("day_key") or today_key(),
            "source": "bot",
        }
        payload["ai"] = _normalize_ai_task_stats_snapshot(merged_ai)
        try:
            write_llm_daily_stats_side(
                str(payload["ai"].get("day_key") or bot_snap.get("day_key") or today_key()),
                "ai",
                {**payload["ai"], "reachable": True},
            )
        except Exception:
            pass

    try:
        from pallas.core.platform.shard import context as shard_ctx
        from pallas.product.llm.provider_request_metrics import (
            cluster_llm_provider_request_metrics_snapshot,
            flush_provider_request_stats_sync,
            llm_provider_request_metrics_snapshot,
        )

        flush_provider_request_stats_sync()
        if shard_ctx.sharding_active() and shard_ctx.is_hub():
            request_snap = cluster_llm_provider_request_metrics_snapshot()
        else:
            request_snap = llm_provider_request_metrics_snapshot(include_persisted=True)
    except Exception:
        request_snap = {}
    if isinstance(request_snap, dict) and (request_snap.get("provider_stats") or request_snap.get("model_stats")):
        ai_body = payload.get("ai") if isinstance(payload.get("ai"), dict) else {}
        day = str(ai_body.get("day_key") or request_snap.get("day_key") or bot_snap.get("day_key") or today_key())
        merged_ai = {
            **ai_body,
            "day_key": day,
            "source": ai_body.get("source") or "bot",
            "provider_stats": request_snap.get("provider_stats") or {},
            "model_stats": request_snap.get("model_stats") or {},
            "failure_counts": request_snap.get("failure_counts") or ai_body.get("failure_counts") or {},
        }
        payload["ai"] = _normalize_ai_task_stats_snapshot(merged_ai)
        try:
            write_llm_daily_stats_side(day, "ai", {**payload["ai"], "reachable": True})
        except Exception:
            pass

    try:
        from pallas.core.platform.shard import context as shard_ctx
        from pallas.product.llm.rag_metrics import (
            cluster_llm_rag_metrics_snapshot,
            flush_rag_stats_sync,
            llm_rag_metrics_snapshot,
        )

        flush_rag_stats_sync()
        if shard_ctx.sharding_active() and shard_ctx.is_hub():
            rag_snap = cluster_llm_rag_metrics_snapshot()
        else:
            rag_snap = llm_rag_metrics_snapshot(include_persisted=True)
    except Exception:
        rag_snap = {}
    if isinstance(rag_snap, dict) and (
        int(rag_snap.get("hit_count") or 0) > 0 or int(rag_snap.get("miss_count") or 0) > 0
    ):
        ai_body = payload.get("ai") if isinstance(payload.get("ai"), dict) else {}
        day = str(ai_body.get("day_key") or rag_snap.get("day_key") or bot_snap.get("day_key") or today_key())
        merged_ai = {
            **ai_body,
            "day_key": day,
            "source": ai_body.get("source") or "bot",
            "rag": rag_snap,
        }
        payload["ai"] = _normalize_ai_task_stats_snapshot(merged_ai)
        try:
            write_llm_daily_stats_side(day, "ai", {**payload["ai"], "reachable": True})
        except Exception:
            pass

    try:
        from pallas.core.platform.shard import context as shard_ctx
        from pallas.product.llm.memory_rag_metrics import (
            cluster_llm_memory_rag_metrics_snapshot,
            flush_memory_rag_stats_sync,
            llm_memory_rag_metrics_snapshot,
        )

        flush_memory_rag_stats_sync()
        if shard_ctx.sharding_active() and shard_ctx.is_hub():
            memory_rag_snap = cluster_llm_memory_rag_metrics_snapshot()
        else:
            memory_rag_snap = llm_memory_rag_metrics_snapshot(include_persisted=True)
    except Exception:
        memory_rag_snap = {}
    if isinstance(memory_rag_snap, dict) and (
        int(memory_rag_snap.get("hit_count") or 0) > 0 or int(memory_rag_snap.get("miss_count") or 0) > 0
    ):
        ai_body = payload.get("ai") if isinstance(payload.get("ai"), dict) else {}
        day = str(ai_body.get("day_key") or memory_rag_snap.get("day_key") or bot_snap.get("day_key") or today_key())
        merged_ai = {
            **ai_body,
            "day_key": day,
            "source": ai_body.get("source") or "bot",
            "memory_rag": memory_rag_snap,
        }
        payload["ai"] = _normalize_ai_task_stats_snapshot(merged_ai)
        try:
            write_llm_daily_stats_side(day, "ai", {**payload["ai"], "reachable": True})
        except Exception:
            pass

    gates = _gates_from_bot_snapshot(bot_snap if isinstance(bot_snap, dict) else None)
    if gates["skip"] or gates["defer"] or gates["proceed"]:
        ai_body = payload.get("ai") if isinstance(payload.get("ai"), dict) else {}
        day = str(ai_body.get("day_key") or bot_snap.get("day_key") or today_key())
        merged_ai = {
            **ai_body,
            "day_key": day,
            "source": ai_body.get("source") or "bot",
            "gates": gates,
        }
        payload["ai"] = _normalize_ai_task_stats_snapshot(merged_ai)
        try:
            write_llm_daily_stats_side(day, "ai", {**payload["ai"], "reachable": True})
        except Exception:
            pass

    payload["persistence"]["ai_collecting"] = _ai_snapshot_collecting(
        payload.get("ai") if isinstance(payload.get("ai"), dict) else None
    )
    payload["persistence"]["ai_reachable"] = bool(payload.get("ai_reachable"))

    clock_today = today_key()
    end_d = date.fromisoformat(clock_today)
    start_d = end_d - timedelta(days=89)
    if end:
        try:
            end_d = date.fromisoformat(str(end).strip()[:10])
        except ValueError:
            pass
    if start:
        try:
            start_d = date.fromisoformat(str(start).strip()[:10])
        except ValueError:
            pass
    if start_d > end_d:
        start_d, end_d = end_d, start_d
    hist_rows, h_start, h_end = load_llm_daily_stats_range(start_day=start_d.isoformat(), end_day=end_d.isoformat())
    hist_rows = _overlay_ledger_on_history_rows(
        hist_rows,
        start_day=start_d.isoformat(),
        end_day=end_d.isoformat(),
    )
    today_bot = bot_snap if isinstance(bot_snap, dict) else None
    by_date = {}
    for hist_row in hist_rows:
        row_date = str(hist_row.get("date") or "").strip()[:10]
        if not row_date:
            continue
        row = {
            "date": row_date,
            "bot": hist_row.get("bot") if isinstance(hist_row.get("bot"), dict) else None,
            "ai": _normalize_historical_ai_snapshot(hist_row.get("ai"))
            if isinstance(hist_row.get("ai"), dict)
            else None,
        }
        by_date[row_date] = row
    if not _ai_has_live_llm_metrics(payload.get("ai") if isinstance(payload.get("ai"), dict) else None):
        fallback_ai = _latest_historical_ai_snapshot(list(by_date.values()))
        if fallback_ai is not None:
            existing = payload.get("ai") if isinstance(payload.get("ai"), dict) else {}
            keep_images = existing.get("images") if isinstance(existing.get("images"), dict) else None
            merged_fallback = dict(fallback_ai)
            if keep_images:
                merged_fallback["images"] = keep_images
            payload["ai"] = _normalize_ai_task_stats_snapshot(merged_fallback)

    try:
        from pallas_plugin_draw.draw_stats_store import draw_stats_snapshot, flush_draw_stats_sync

        flush_draw_stats_sync()
        draw_images = draw_stats_snapshot(include_persisted=True)
    except Exception:
        draw_images = {}
    if isinstance(draw_images, dict) and (
        int(draw_images.get("ok_count") or 0) > 0
        or int(draw_images.get("fail_count") or 0) > 0
        or draw_images.get("by_model")
        or draw_images.get("by_provider")
    ):
        ai_body = payload.get("ai") if isinstance(payload.get("ai"), dict) else {}
        day = str(ai_body.get("day_key") or draw_images.get("day_key") or bot_snap.get("day_key") or today_key())
        merged_ai = {
            **ai_body,
            "day_key": day,
            "source": ai_body.get("source") or "bot",
            "images": draw_images,
        }
        payload["ai"] = _normalize_ai_task_stats_snapshot(merged_ai)
        try:
            write_llm_daily_stats_side(day, "ai", {**payload["ai"], "reachable": True})
        except Exception:
            pass
        payload["persistence"]["ai_collecting"] = _ai_snapshot_collecting(
            payload.get("ai") if isinstance(payload.get("ai"), dict) else None
        )

    today_ai = payload.get("ai") if isinstance(payload.get("ai"), dict) and payload.get("ai") else None
    # 实时内存在重启后可能缺提供方；当日 token 以账本为准，避免盖掉 history 里的 ledger 分桶
    if isinstance(today_ai, dict):
        today_ai = _enrich_ai_snapshot_from_ledger(today_ai, day_key=clock_today) or today_ai
        payload["ai"] = today_ai
    if start_d <= date.fromisoformat(clock_today) <= end_d:
        row = by_date.setdefault(clock_today, {"date": clock_today, "bot": None, "ai": None})
        if today_bot:
            row["bot"] = today_bot
        if today_ai:
            prev_ai = row.get("ai") if isinstance(row.get("ai"), dict) else None
            if prev_ai:
                # 日汇总里更完整的 rag/token 等不要被重启后偏少的实时快照盖掉
                from pallas.product.llm.llm_daily_stats_store import merge_side_snapshot

                today_ai = merge_side_snapshot(prev_ai, today_ai)
                payload["ai"] = today_ai
            row["ai"] = today_ai
    merged_hist = sorted(by_date.values(), key=lambda r: str(r.get("date", "")))
    payload["history"] = {
        "start": h_start,
        "end": h_end,
        "query_start": start_d.isoformat(),
        "query_end": end_d.isoformat(),
        "rows": merged_hist,
        "server_date": clock_today,
    }
    return payload
