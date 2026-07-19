"""代理 AI 服务模型管理 API，供 WebUI 与超管口令使用。"""

from __future__ import annotations

from typing import Any

from nonebot import logger

from pallas.core.shared.utils import HTTPXClient

from .config import LlmConfig, get_llm_config, llm_server_base_url
from .startup_probe import probe_ai_service_health
from .task_metrics import cluster_llm_task_metrics_snapshot, llm_task_metrics_snapshot, today_key


def load_llm_daily_stats_range(*, start_day: str, end_day: str) -> tuple[list[dict[str, Any]], str, str]:
    from pallas.product.llm.llm_daily_stats_store import load_range

    return load_range(start_day=start_day, end_day=end_day)


def write_llm_daily_stats_side(day: str, side: str, snapshot: dict[str, Any]) -> None:
    from pallas.product.llm.llm_daily_stats_store import write_day_side

    write_day_side(day, side, snapshot)


def _ai_snapshot_collecting(snapshot: dict[str, Any] | None) -> bool:
    if not isinstance(snapshot, dict):
        return False
    by_task = snapshot.get("by_task")
    if isinstance(by_task, dict) and bool(by_task):
        return True
    tokens = snapshot.get("tokens")
    if isinstance(tokens, dict):
        return any(int(tokens.get(key) or 0) > 0 for key in ("prompt_tokens", "completion_tokens", "total_tokens"))
    return False


def _normalize_ai_task_stats_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    raw = snapshot if isinstance(snapshot, dict) else {}
    by_task = raw.get("by_task") if isinstance(raw.get("by_task"), dict) else {}
    totals = raw.get("totals") if isinstance(raw.get("totals"), dict) else {}
    tokens_raw = raw.get("tokens") if isinstance(raw.get("tokens"), dict) else {}
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
    provider_stats = raw.get("provider_stats") if isinstance(raw.get("provider_stats"), dict) else {}
    model_stats = raw.get("model_stats") if isinstance(raw.get("model_stats"), dict) else {}
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
        "failure_counts": dict(failure_counts),
        "provider_stats": dict(provider_stats),
        "model_stats": dict(model_stats),
        "tokens": {
            "source": str(tokens_raw.get("source") or raw.get("source") or "ai"),
            "day_key": str(tokens_raw.get("day_key") or raw.get("day_key") or ""),
            "updated_at": tokens_raw.get("updated_at"),
            "prompt_tokens": int(tokens_raw.get("prompt_tokens") or 0),
            "completion_tokens": int(tokens_raw.get("completion_tokens") or 0),
            "total_tokens": int(tokens_raw.get("total_tokens") or 0),
            "by_task": tokens_raw.get("by_task") if isinstance(tokens_raw.get("by_task"), dict) else {},
            "by_provider": tokens_raw.get("by_provider") if isinstance(tokens_raw.get("by_provider"), dict) else {},
            "by_model": tokens_raw.get("by_model") if isinstance(tokens_raw.get("by_model"), dict) else {},
        },
    }


def _normalized_classification_table(raw: Any) -> dict[str, dict[str, int]]:
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, dict[str, int]] = {}
    for key, row in raw.items():
        if not isinstance(row, dict):
            continue
        normalized[str(key)] = {
            "ok": int(row.get("ok") or 0),
            "fail": int(row.get("fail") or 0),
        }
    return normalized


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
        "provider_stats": _normalized_classification_table(classification.get("provider_stats")),
        "model_stats": _normalized_classification_table(classification.get("model_stats")),
    }


def _latest_historical_ai_snapshot(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    for row in reversed(rows):
        ai = row.get("ai")
        if isinstance(ai, dict) and ai:
            return _normalize_historical_ai_snapshot(ai)
    return None


def ai_llm_api_base(cfg: LlmConfig | None = None) -> str:
    return f"{llm_server_base_url(cfg or get_llm_config()).rstrip('/')}/api/llm"


async def fetch_model_admin_status(*, cfg: LlmConfig | None = None, timeout_sec: float = 15.0) -> dict[str, Any]:
    c = cfg or get_llm_config()
    health = await probe_ai_service_health(timeout_sec=min(timeout_sec, 8.0))
    status: dict[str, Any] = {
        "model": "",
        "ai_reachable": bool(health.get("ok")),
        "llm_chat_enabled": c.llm_chat_enabled,
        "health_url": health.get("url", ""),
        "error": "" if health.get("ok") else str(health.get("error") or "AI 服务不可达"),
    }
    if not health.get("ok"):
        return status
    body = health.get("body")
    if isinstance(body, dict):
        llm_info = body.get("llm")
        if isinstance(llm_info, dict):
            status["provider_mode"] = str(llm_info.get("provider_mode") or "").strip()
            provider_status = llm_info.get("provider_status")
            if isinstance(provider_status, list):
                status["provider_status"] = provider_status
            task_routing = llm_info.get("task_routing")
            if isinstance(task_routing, dict):
                status["task_routing"] = task_routing
            status["categorizer_enabled"] = bool(llm_info.get("categorizer_enabled"))
            status["categorizer_model"] = str(llm_info.get("categorizer_model") or "").strip()
            status["tools_selective"] = bool(llm_info.get("tools_selective"))
            status["moe_tier_routing"] = bool(llm_info.get("moe_tier_routing"))
            status["local_multi_model_enabled"] = bool(llm_info.get("local_multi_model_enabled"))
            status["local_model_policy"] = str(llm_info.get("local_model_policy") or "").strip()
            local_task_models = llm_info.get("local_task_models")
            if isinstance(local_task_models, dict):
                status["local_task_models"] = {str(k): str(v) for k, v in local_task_models.items() if str(v).strip()}
            local_moe_models = llm_info.get("local_moe_models")
            if isinstance(local_moe_models, dict):
                status["local_moe_models"] = {str(k): str(v) for k, v in local_moe_models.items() if str(v).strip()}
    try:
        response = await HTTPXClient.get(f"{ai_llm_api_base(c)}/model", timeout=timeout_sec)
    except Exception as exc:
        status["ai_reachable"] = False
        status["error"] = str(exc)
        return status
    if response is None or response.status_code != 200:
        code = response.status_code if response is not None else None
        status["ai_reachable"] = False
        status["error"] = f"读取模型失败 HTTP {code}"
        return status
    try:
        payload = response.json()
    except Exception:
        status["ai_reachable"] = False
        status["error"] = "模型接口响应无效"
        return status
    model = str(payload.get("model") or "").strip()
    status["model"] = model
    num_gpu = payload.get("num_gpu")
    if isinstance(num_gpu, int):
        status["num_gpu"] = num_gpu
    elif isinstance(num_gpu, float) and num_gpu.is_integer():
        status["num_gpu"] = int(num_gpu)
    status["error"] = "" if model else "当前未配置模型"
    return status


async def get_runtime_model(*, cfg: LlmConfig | None = None, timeout_sec: float = 30.0) -> str:
    status = await fetch_model_admin_status(cfg=cfg, timeout_sec=timeout_sec)
    if not status.get("ai_reachable"):
        msg = str(status.get("error") or "AI 服务不可达")
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
    name = model.strip()
    if not name:
        raise ValueError("模型名不能为空")
    c = cfg or get_llm_config()
    response = await HTTPXClient.put(
        f"{ai_llm_api_base(c)}/model",
        json={"model": name, "pull": pull},
        timeout=timeout_sec,
    )
    if response is None:
        raise RuntimeError("切换模型请求失败")
    if response.status_code != 200:
        detail = (response.text or "")[:300]
        raise RuntimeError(f"切换模型失败 HTTP {response.status_code}: {detail}")
    payload = response.json()
    resolved = str(payload.get("model") or name).strip()
    num_gpu = payload.get("num_gpu")
    result: dict[str, Any] = {"model": resolved or name}
    if isinstance(num_gpu, int):
        result["num_gpu"] = num_gpu
    elif isinstance(num_gpu, float) and num_gpu.is_integer():
        result["num_gpu"] = int(num_gpu)
    logger.info("llm model switched via AI API: model={} pull={} num_gpu={}", resolved, pull, result.get("num_gpu"))
    return result


async def set_runtime_num_gpu(
    num_gpu: int,
    *,
    cfg: LlmConfig | None = None,
    timeout_sec: float = 60.0,
) -> dict[str, Any]:
    if num_gpu < 0:
        raise ValueError("GPU 层数不能为负数")
    c = cfg or get_llm_config()
    response = await HTTPXClient.post(
        f"{ai_llm_api_base(c)}/model/num-gpu",
        json={"num_gpu": num_gpu},
        timeout=timeout_sec,
    )
    if response is None:
        raise RuntimeError("设置 GPU 层数请求失败")
    if response.status_code != 200:
        detail = (response.text or "")[:300]
        raise RuntimeError(f"设置 GPU 层数失败 HTTP {response.status_code}: {detail}")
    payload = response.json()
    resolved = str(payload.get("model") or "").strip()
    result: dict[str, Any] = {}
    if resolved:
        result["model"] = resolved
    resolved_gpu = payload.get("num_gpu")
    if isinstance(resolved_gpu, int):
        result["num_gpu"] = resolved_gpu
    elif isinstance(resolved_gpu, float) and resolved_gpu.is_integer():
        result["num_gpu"] = int(resolved_gpu)
    else:
        result["num_gpu"] = num_gpu
    logger.info("llm num_gpu set via AI API: num_gpu={} model={}", result.get("num_gpu"), result.get("model"))
    return result


async def reload_runtime_model(*, cfg: LlmConfig | None = None, timeout_sec: float = 60.0) -> dict[str, Any]:
    c = cfg or get_llm_config()
    response = await HTTPXClient.post(
        f"{ai_llm_api_base(c)}/model/reload",
        json={},
        timeout=timeout_sec,
    )
    if response is None:
        raise RuntimeError("重载模型请求失败")
    if response.status_code != 200:
        detail = (response.text or "")[:300]
        raise RuntimeError(f"重载模型失败 HTTP {response.status_code}: {detail}")
    payload = response.json()
    resolved = str(payload.get("model") or "").strip()
    result: dict[str, Any] = {"model": resolved}
    num_gpu = payload.get("num_gpu")
    if isinstance(num_gpu, int):
        result["num_gpu"] = num_gpu
    elif isinstance(num_gpu, float) and num_gpu.is_integer():
        result["num_gpu"] = int(num_gpu)
    logger.info("llm model reloaded from env: model={} num_gpu={}", resolved, result.get("num_gpu"))
    return result


async def unload_runtime_model(*, cfg: LlmConfig | None = None, timeout_sec: float = 60.0) -> None:
    c = cfg or get_llm_config()
    response = await HTTPXClient.post(
        f"{ai_llm_api_base(c)}/unload",
        json={},
        timeout=timeout_sec,
    )
    if response is None:
        raise RuntimeError("卸载模型请求失败")
    if response.status_code != 200:
        detail = (response.text or "")[:300]
        raise RuntimeError(f"卸载模型失败 HTTP {response.status_code}: {detail}")
    logger.info("llm model unloaded via AI API")


async def fetch_providers_config(*, cfg: LlmConfig | None = None, timeout_sec: float = 15.0) -> dict[str, Any]:
    c = cfg or get_llm_config()
    response = await HTTPXClient.get(f"{ai_llm_api_base(c)}/providers", timeout=timeout_sec)
    if response is None:
        raise RuntimeError("读取提供方配置失败")
    if response.status_code != 200:
        detail = (response.text or "")[:300]
        raise RuntimeError(f"读取提供方配置失败 HTTP {response.status_code}: {detail}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("提供方配置响应无效")
    return payload


async def save_providers_config(
    document: dict[str, Any],
    *,
    cfg: LlmConfig | None = None,
    timeout_sec: float = 30.0,
) -> dict[str, Any]:
    c = cfg or get_llm_config()
    response = await HTTPXClient.put(
        f"{ai_llm_api_base(c)}/providers",
        json=document,
        timeout=timeout_sec,
    )
    if response is None:
        raise RuntimeError("保存提供方配置失败")
    if response.status_code != 200:
        detail = (response.text or "")[:300]
        raise RuntimeError(f"保存提供方配置失败 HTTP {response.status_code}: {detail}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("保存提供方配置响应无效")
    logger.info("llm providers saved: file={}", payload.get("providers_file"))
    return payload


async def fetch_provider_models(
    provider_id: str,
    *,
    cfg: LlmConfig | None = None,
    timeout_sec: float = 15.0,
) -> dict[str, Any]:
    from urllib.parse import quote

    c = cfg or get_llm_config()
    pid = quote(str(provider_id), safe="")
    response = await HTTPXClient.get(f"{ai_llm_api_base(c)}/providers/{pid}/models", timeout=timeout_sec)
    if response is None:
        raise RuntimeError("拉取模型列表失败")
    if response.status_code != 200:
        detail = (response.text or "")[:300]
        raise RuntimeError(f"拉取模型列表失败 HTTP {response.status_code}: {detail}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("模型列表响应无效")
    return payload


async def fetch_local_routing_config(
    *,
    cfg: LlmConfig | None = None,
    timeout_sec: float = 15.0,
) -> dict[str, Any]:
    c = cfg or get_llm_config()
    response = await HTTPXClient.get(f"{ai_llm_api_base(c)}/local-routing", timeout=timeout_sec)
    if response is None:
        raise RuntimeError("读取本地模型路由配置失败")
    if response.status_code != 200:
        detail = (response.text or "")[:300]
        raise RuntimeError(f"读取本地模型路由配置失败 HTTP {response.status_code}: {detail}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("本地模型路由配置响应无效")
    return payload


async def save_local_routing_config(
    document: dict[str, Any],
    *,
    cfg: LlmConfig | None = None,
    timeout_sec: float = 30.0,
) -> dict[str, Any]:
    c = cfg or get_llm_config()
    response = await HTTPXClient.put(
        f"{ai_llm_api_base(c)}/local-routing",
        json=document,
        timeout=timeout_sec,
    )
    if response is None:
        raise RuntimeError("保存本地模型路由配置失败")
    if response.status_code != 200:
        detail = (response.text or "")[:300]
        raise RuntimeError(f"保存本地模型路由配置失败 HTTP {response.status_code}: {detail}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("保存本地模型路由配置响应无效")
    logger.info("llm local routing config saved: env={}", payload.get("env_file"))
    return payload


async def probe_provider(
    provider_id: str,
    *,
    cfg: LlmConfig | None = None,
    timeout_sec: float = 15.0,
) -> dict[str, Any]:
    from urllib.parse import quote

    c = cfg or get_llm_config()
    pid = quote(str(provider_id), safe="")
    response = await HTTPXClient.post(f"{ai_llm_api_base(c)}/providers/{pid}/test", json={}, timeout=timeout_sec)
    if response is None:
        raise RuntimeError("连通性测试失败")
    if response.status_code != 200:
        detail = (response.text or "")[:300]
        raise RuntimeError(f"连通性测试失败 HTTP {response.status_code}: {detail}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("连通性测试响应无效")
    return payload


async def fetch_llm_task_stats(
    *,
    cfg: LlmConfig | None = None,
    timeout_sec: float = 8.0,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    from datetime import date, timedelta

    c = cfg or get_llm_config()
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
        "ai_reachable": False,
        "persistence": {
            "store_file": "llm_daily_stats.json",
            "bot_collecting": bool(bot_snap.get("by_task")),
            "bot_day_key": bot_snap.get("day_key") or today_key(),
        },
    }
    try:
        response = await HTTPXClient.get(f"{ai_llm_api_base(c)}/stats", timeout=timeout_sec)
    except Exception as exc:
        payload["error"] = str(exc)
    else:
        if response is None or response.status_code != 200:
            code = response.status_code if response is not None else None
            payload["error"] = f"读取 AI 统计失败 HTTP {code}"
        else:
            try:
                body = response.json()
            except Exception:
                payload["error"] = "AI 统计响应无效"
            else:
                if isinstance(body, dict):
                    payload["ai"] = _normalize_ai_task_stats_snapshot(body)
                    payload["ai_reachable"] = True
                    try:
                        ai_day = str(payload["ai"].get("day_key") or bot_snap.get("day_key") or today_key())
                        write_llm_daily_stats_side(ai_day, "ai", {**payload["ai"], "reachable": True})
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
    today_bot = bot_snap if isinstance(bot_snap, dict) else None
    today_ai = payload.get("ai") if isinstance(payload.get("ai"), dict) and payload.get("ai") else None
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
    if not payload.get("ai"):
        fallback_ai = _latest_historical_ai_snapshot(list(by_date.values()))
        if fallback_ai is not None:
            payload["ai"] = fallback_ai
    if start_d <= date.fromisoformat(clock_today) <= end_d:
        row = by_date.setdefault(clock_today, {"date": clock_today, "bot": None, "ai": None})
        if today_bot:
            row["bot"] = today_bot
        if today_ai:
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
