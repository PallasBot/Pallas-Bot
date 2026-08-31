#!/usr/bin/env python3
"""跨进程运行态观测：聚合既有观测源，输出脱敏快照/查询，并带 TTL 清理。

阶段 3「运行态反馈」的本地查询入口。不引入重观测平台，而是复用既有
startup report、LLM runtime debug（request snapshot / trace）与 ingress
metrics history，把它们聚合成统一关联 ID / 阶段 / 耗时 / 失败分类的脱敏视图。

隐私约束：默认不输出消息正文、prompt、token 与密钥；需要原始正文调试时
显式传 ``--raw``（仅限本地排障，不进入长期产物）。
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

# 观测快照的 TTL（秒）：临时观测存储只保留有限窗口，避免长期堆积。
OBSERVE_RETENTION_SEC = 7 * 24 * 60 * 60

# 脱敏掩码与需要脱敏的字段键。
REDACTION_MASK = "[REDACTED]"
_REDACTED_KEYS = frozenset({
    "system_prompt",
    "messages",
    "reply",
    "message",
    "prompt",
    "task",
    "last_user_message",
    "system_prompt_preview",
})


def _redact(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return REDACTION_MASK
    if isinstance(value, dict):
        return {
            key: (REDACTION_MASK if key in _REDACTED_KEYS else _redact(item, depth=depth + 1))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item, depth=depth + 1) for item in value]
    return value


def _startup_report_snapshot() -> dict[str, Any]:
    try:
        from pallas.core.foundation.startup_report import startup_report_snapshot

        return startup_report_snapshot()
    except Exception as exc:  # pragma: no cover - 依赖缺失时降级
        return {"error": f"startup_report unavailable: {type(exc).__name__}"}


def _llm_runtime_bundle(request_id: str) -> dict[str, Any]:
    try:
        from pallas.product.llm.runtime_debug import load_runtime_debug_bundle

        return load_runtime_debug_bundle(request_id=request_id)
    except Exception as exc:  # pragma: no cover
        return {"error": f"llm runtime debug unavailable: {type(exc).__name__}"}


def _ensure_nonebot() -> None:
    """确保 NoneBot 已初始化，避免导入 pb_webui 包时触发 startup 失败。"""
    try:
        import nonebot

        nonebot.get_driver()
    except Exception:
        import nonebot

        nonebot.init()


def _ingress_metrics(window_sec: int, bucket_sec: int) -> dict[str, Any]:
    try:
        _ensure_nonebot()
        from packages.pb_webui.ingress_metrics_history import read_ingress_metrics_history

        return read_ingress_metrics_history(window_sec=window_sec, bucket_sec=bucket_sec)
    except Exception as exc:  # pragma: no cover
        return {"error": f"ingress metrics unavailable: {type(exc).__name__}"}


def _route_candidate_history() -> dict[str, Any]:
    try:
        _ensure_nonebot()
        from packages.pb_webui.ingress_metrics_history import read_route_candidate_history

        return read_route_candidate_history()
    except Exception as exc:  # pragma: no cover
        return {"error": f"route candidate history unavailable: {type(exc).__name__}"}


def _list_request_ids() -> list[str]:
    """从 LLM runtime debug 的 request snapshot 文件收集关联 ID。"""
    try:
        from pallas.product.llm.runtime_debug import request_snapshot_path

        path = request_snapshot_path()
    except Exception:
        return []
    if not path.is_file():
        return []
    ids: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        request_id = str(row.get("request_id") or "").strip()
        if request_id and request_id not in ids:
            ids.append(request_id)
    return ids


def _failure_classification(bundle: dict[str, Any]) -> dict[str, Any]:
    """从 LLM runtime bundle 提取失败分类（阶段/耗时/错误类）。"""
    trace = bundle.get("trace") if isinstance(bundle.get("trace"), dict) else {}
    snapshot = bundle.get("snapshot") if isinstance(bundle.get("snapshot"), dict) else {}
    stages = trace.get("stages") if isinstance(trace.get("stages"), list) else []
    error = trace.get("error")
    error_class = trace.get("error_class")
    if not error_class and isinstance(error, dict):
        error_class = error.get("class")
    return {
        "request_id": bundle.get("request_id"),
        "stages": stages,
        "error": error,
        "error_class": error_class,
        "created_at": snapshot.get("created_at"),
        "task": snapshot.get("task"),
    }


def _prune_observe_store() -> dict[str, Any]:
    """清理超过 TTL 的临时观测存储（LLM runtime debug 与 ingress history）。"""
    pruned: dict[str, Any] = {}
    cutoff = int(time.time()) - OBSERVE_RETENTION_SEC
    try:
        from pallas.product.llm.runtime_debug import request_snapshot_path, runtime_trace_path

        for name, path in (
            ("request_snapshots", request_snapshot_path()),
            ("runtime_traces", runtime_trace_path()),
        ):
            pruned[name] = _prune_jsonl(path, cutoff)
    except Exception as exc:  # pragma: no cover
        pruned["llm_runtime"] = f"unavailable: {type(exc).__name__}"
    try:
        _ensure_nonebot()
        from packages.pb_webui.ingress_metrics_history import prune_ingress_metrics_history

        pruned["ingress_metrics"] = prune_ingress_metrics_history()
    except Exception as exc:  # pragma: no cover
        pruned["ingress_metrics"] = f"unavailable: {type(exc).__name__}"
    return pruned


def _prune_jsonl(path: Path, cutoff: int) -> int:
    if not path.is_file():
        return 0
    kept: list[str] = []
    removed = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = int(row.get("created_at") or 0)
        if ts and ts < cutoff:
            removed += 1
            continue
        kept.append(line)
    if removed:
        path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    return removed


def build_observation_snapshot(
    *,
    request_id: str | None = None,
    window_sec: int = 3600,
    bucket_sec: int = 60,
    raw: bool = False,
) -> dict[str, Any]:
    """聚合各观测源为统一脱敏快照。"""
    snapshot: dict[str, Any] = {
        "generated_at": int(time.time()),
        "retention_sec": OBSERVE_RETENTION_SEC,
        "startup_report": _startup_report_snapshot(),
        "ingress_metrics": _ingress_metrics(window_sec=window_sec, bucket_sec=bucket_sec),
        "route_candidates": _route_candidate_history(),
    }
    if request_id:
        bundle = _llm_runtime_bundle(request_id)
        snapshot["llm_runtime"] = _failure_classification(bundle)
        snapshot["request_ids"] = [request_id]
    else:
        snapshot["request_ids"] = _list_request_ids()
    if not raw:
        snapshot = _redact(snapshot)
    return snapshot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="跨进程运行态观测：聚合 startup report / LLM runtime / ingress metrics 为脱敏快照。",
    )
    parser.add_argument("--request-id", default=None, help="按关联 ID 查询单个 LLM runtime bundle。")
    parser.add_argument("--window", type=int, default=3600, help="ingress metrics 时间窗（秒）。")
    parser.add_argument("--bucket", type=int, default=60, help="ingress metrics 分桶（秒）。")
    parser.add_argument("--raw", action="store_true", help="输出原始正文（仅本地排障，不进长期产物）。")
    parser.add_argument("--prune", action="store_true", help="清理超过 TTL 的临时观测存储。")
    parser.add_argument("--out", type=Path, help="可选：把快照写入 JSON 文件。")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.prune:
        result = _prune_observe_store()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    snapshot = build_observation_snapshot(
        request_id=args.request_id,
        window_sec=args.window,
        bucket_sec=args.bucket,
        raw=args.raw,
    )
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote snapshot -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
