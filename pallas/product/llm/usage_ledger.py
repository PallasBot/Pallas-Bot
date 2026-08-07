"""LLM 请求级 usage 账本（按日 JSONL，含 token 与费用）。"""

from __future__ import annotations

import json
import threading
import time
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from pathlib import Path

_LOCK = threading.Lock()
_MAX_RETAIN_DAYS = 120
# 单日总量超过该值视为脏数据（旧 AI 侧曾灌入百亿级）
_MAX_SANE_DAY_TOKENS = 50_000_000


def usage_ledger_dir() -> Path:
    from pallas.core.foundation.paths import plugin_data_dir

    return plugin_data_dir("pb_webui", create=True) / "llm_usage"


def _part_suffix() -> str:
    try:
        from pallas.core.platform.shard import context as shard_ctx

        if shard_ctx.sharding_active() and shard_ctx.is_worker():
            return f".w{int(shard_ctx.shard_id())}"
    except Exception:
        pass
    return ""


def ledger_path_for_day(day: str) -> Path:
    day_key = str(day or "").strip()[:10]
    return usage_ledger_dir() / f"{day_key}{_part_suffix()}.jsonl"


def append_usage_record(
    *,
    task: str | None,
    provider: str | None,
    model: str | None,
    prompt_tokens: int,
    completion_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    cost: float = 0.0,
    currency: str = "",
    day_key: str | None = None,
    ts: float | None = None,
) -> None:
    """追加一条请求级用量；失败静默（不影响热路径）。"""
    prompt = max(0, int(prompt_tokens))
    completion = max(0, int(completion_tokens))
    cache_read = max(0, int(cache_read_tokens))
    cache_write = max(0, int(cache_write_tokens))
    if prompt == 0 and completion == 0 and cache_read == 0 and cache_write == 0:
        return
    try:
        from pallas.product.llm.token_cost import normalize_cost_currency
        from pallas.product.llm.token_metrics import today_key

        day = str(day_key or today_key()).strip()[:10]
        if len(day) < 10:
            return
        row = {
            "ts": float(ts if ts is not None else time.time()),
            "day": day,
            "task": str(task or "llm_chat").strip().lower() or "llm_chat",
            "provider": str(provider or "").strip().lower(),
            "model": str(model or "").strip(),
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "cache_read_tokens": cache_read,
            "cache_write_tokens": cache_write,
            "cost": round(float(cost or 0.0), 6),
            "currency": normalize_cost_currency(currency),
        }
        path = ledger_path_for_day(day)
        line = json.dumps(row, ensure_ascii=False) + "\n"
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)
    except Exception:
        pass


def monthly_model_tokens(provider: str | None, model: str | None, *, ts: float | None = None) -> int:
    """返回上海自然月内已成功落盘的单模型 Token 总量。"""
    provider_key = str(provider or "").strip().lower()
    model_key = str(model or "").strip()
    if not provider_key or not model_key:
        return 0
    month = datetime.fromtimestamp(ts if ts is not None else time.time(), tz=ZoneInfo("Asia/Shanghai")).strftime(
        "%Y-%m"
    )
    total = 0
    try:
        for path in usage_ledger_dir().glob("*.jsonl"):
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    try:
                        row = json.loads(line)
                        row_month = datetime.fromtimestamp(
                            float(row.get("ts") or 0), tz=ZoneInfo("Asia/Shanghai")
                        ).strftime("%Y-%m")
                    except (TypeError, ValueError, json.JSONDecodeError):
                        continue
                    if (
                        row_month != month
                        or str(row.get("provider") or "").strip().lower() != provider_key
                        or str(row.get("model") or "").strip() != model_key
                    ):
                        continue
                    total += sum(
                        max(0, int(row.get(key) or 0))
                        for key in ("prompt_tokens", "completion_tokens", "cache_read_tokens", "cache_write_tokens")
                    )
    except OSError:
        return 0
    return total


def _iter_day_files(day: str) -> list[Path]:
    day_key = str(day or "").strip()[:10]
    if len(day_key) < 10:
        return []
    root = usage_ledger_dir()
    if not root.is_dir():
        return []
    return sorted(path for path in root.glob(f"{day_key}*.jsonl") if path.is_file())


def _empty_day_bucket() -> dict[str, Any]:
    return {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "total_tokens": 0,
        "cost_total": 0.0,
        "cost_currency": "",
        "request_count": 0,
        "by_task": {},
        "by_provider": {},
        "by_model": {},
        "by_hour": {},
        "source": "ledger",
    }


def _bump_breakdown(
    dst: dict[str, dict[str, Any]],
    key: str,
    *,
    prompt: int,
    completion: int,
    cache_read: int,
    cache_write: int,
    cost: float,
) -> None:
    name = str(key or "").strip()
    if not name:
        return
    row = dst.setdefault(
        name,
        {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "cost_total": 0.0,
            "requests": 0,
        },
    )
    row["prompt_tokens"] = int(row.get("prompt_tokens") or 0) + prompt
    row["completion_tokens"] = int(row.get("completion_tokens") or 0) + completion
    row["cache_read_tokens"] = int(row.get("cache_read_tokens") or 0) + cache_read
    row["cache_write_tokens"] = int(row.get("cache_write_tokens") or 0) + cache_write
    row["cost_total"] = round(float(row.get("cost_total") or 0.0) + cost, 6)
    row["requests"] = int(row.get("requests") or 0) + 1


def aggregate_day_from_ledger(day: str) -> dict[str, Any] | None:
    """汇总某日账本；无记录返回 None。"""
    files = _iter_day_files(day)
    if not files:
        return None
    bucket = _empty_day_bucket()
    currency = ""
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            prompt = max(0, int(row.get("prompt_tokens") or 0))
            completion = max(0, int(row.get("completion_tokens") or 0))
            cache_read = max(0, int(row.get("cache_read_tokens") or 0))
            cache_write = max(0, int(row.get("cache_write_tokens") or 0))
            try:
                cost = round(float(row.get("cost") or 0.0), 6)
            except (TypeError, ValueError):
                cost = 0.0
            if cost != cost or cost < 0:
                cost = 0.0
            if not currency:
                currency = str(row.get("currency") or "").strip().upper()
            bucket["prompt_tokens"] += prompt
            bucket["completion_tokens"] += completion
            bucket["cache_read_tokens"] += cache_read
            bucket["cache_write_tokens"] += cache_write
            bucket["cost_total"] = round(float(bucket["cost_total"]) + cost, 6)
            bucket["request_count"] += 1
            _bump_breakdown(
                bucket["by_task"],
                str(row.get("task") or "llm_chat"),
                prompt=prompt,
                completion=completion,
                cache_read=cache_read,
                cache_write=cache_write,
                cost=cost,
            )
            _bump_breakdown(
                bucket["by_provider"],
                str(row.get("provider") or ""),
                prompt=prompt,
                completion=completion,
                cache_read=cache_read,
                cache_write=cache_write,
                cost=cost,
            )
            _bump_breakdown(
                bucket["by_model"],
                str(row.get("model") or ""),
                prompt=prompt,
                completion=completion,
                cache_read=cache_read,
                cache_write=cache_write,
                cost=cost,
            )
            try:
                ts = float(row.get("ts") or 0)
            except (TypeError, ValueError):
                ts = 0.0
            if ts > 0:
                hour_key = time.strftime("%H", time.localtime(ts))
                _bump_breakdown(
                    bucket["by_hour"],
                    hour_key,
                    prompt=prompt,
                    completion=completion,
                    cache_read=cache_read,
                    cache_write=cache_write,
                    cost=cost,
                )
    if int(bucket["request_count"]) <= 0:
        return None
    bucket["total_tokens"] = int(bucket["prompt_tokens"]) + int(bucket["completion_tokens"])
    bucket["cost_currency"] = currency
    bucket["day_key"] = str(day).strip()[:10]
    for label in ("by_task", "by_provider", "by_model", "by_hour"):
        for values in bucket[label].values():
            values["total_tokens"] = int(values.get("prompt_tokens") or 0) + int(values.get("completion_tokens") or 0)
    return bucket


def aggregate_ledger_range(*, start_day: str, end_day: str) -> dict[str, dict[str, Any]]:
    """返回 day -> tokens 快照（仅账本有数据的日期）。"""
    try:
        sd = date.fromisoformat(str(start_day).strip()[:10])
        ed = date.fromisoformat(str(end_day).strip()[:10])
    except ValueError:
        return {}
    if sd > ed:
        sd, ed = ed, sd
    out: dict[str, dict[str, Any]] = {}
    cur = sd
    while cur <= ed:
        key = cur.isoformat()
        bucket = aggregate_day_from_ledger(key)
        if bucket is not None:
            out[key] = bucket
        cur += timedelta(days=1)
    return out


def tokens_look_corrupt(tokens: dict[str, Any] | None) -> bool:
    """日汇总 token 是否明显异常（避免脏历史污染 7d/30d）。"""
    if not isinstance(tokens, dict):
        return False
    prompt = int(tokens.get("prompt_tokens") or 0)
    completion = int(tokens.get("completion_tokens") or 0)
    total = int(tokens.get("total_tokens") or 0) or (prompt + completion)
    return total > _MAX_SANE_DAY_TOKENS


def trim_old_ledger_files(*, retain_days: int = _MAX_RETAIN_DAYS) -> int:
    """删除过旧账本文件；返回删除数量。"""
    root = usage_ledger_dir()
    if not root.is_dir():
        return 0
    cutoff = date.today() - timedelta(days=max(1, int(retain_days)))
    removed = 0
    for path in root.glob("*.jsonl"):
        name = path.name
        day_part = name.split(".", 1)[0][:10]
        try:
            day = date.fromisoformat(day_part)
        except ValueError:
            continue
        if day < cutoff:
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
    return removed
