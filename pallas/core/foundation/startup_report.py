"""聚合启动阶段关键事实，并在启动链尾输出成熟摘要。"""

from __future__ import annotations

import os
import re
from collections import OrderedDict
from dataclasses import dataclass, field

from nonebot import get_driver, logger

_ROLE_LABELS = {
    "unified": "统一进程",
    "hub": "Hub",
    "worker": "Worker",
}

_FACT_LABELS = {
    "plugins": "插件",
    "llm": "LLM",
    "ingress": "入站",
    "console": "控制台",
    "scheduler": "调度器",
}

_WARNING_LABELS = {
    "llm": "LLM",
    "console": "控制台",
}


@dataclass
class StartupFactCollector:
    facts: OrderedDict[str, str] = field(default_factory=OrderedDict)
    warnings: OrderedDict[str, str] = field(default_factory=OrderedDict)
    emitted: bool = False

    def set_fact(self, key: str, value: str | None) -> None:
        text = str(value or "").strip()
        if text:
            self.facts[key] = text

    def set_warning(self, key: str, value: str | None) -> None:
        text = str(value or "").strip()
        if text:
            self.warnings[key] = text


_collector = StartupFactCollector()


def register_startup_fact(key: str, value: str | None) -> None:
    _collector.set_fact(key, value)


def register_startup_warning(key: str, value: str | None) -> None:
    _collector.set_warning(key, value)


def reset_startup_report_for_tests() -> None:
    _collector.facts.clear()
    _collector.warnings.clear()
    _collector.emitted = False


def startup_report_snapshot() -> dict[str, dict[str, str] | bool]:
    return {
        "facts": dict(_collector.facts),
        "warnings": dict(_collector.warnings),
        "emitted": _collector.emitted,
    }


def _kv_pairs(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in str(raw or "").split():
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        key = key.strip()
        if key:
            out[key] = value.strip()
    return out


def _role_label(role: str) -> str:
    return _ROLE_LABELS.get(role, role or "-")


def _db_label(backend: str) -> str:
    mapping = {
        "postgresql": "PostgreSQL",
        "postgres": "PostgreSQL",
        "mongodb": "MongoDB",
        "mongo": "MongoDB",
        "sqlite": "SQLite",
    }
    key = (backend or "").strip().lower()
    return mapping.get(key, backend or "-")


def _format_plugins(raw: str) -> str:
    kv = _kv_pairs(raw)
    parts = [
        f"本地 {kv.get('local', '0')}",
        f"内置 {kv.get('src', '0')}",
        f"pip {kv.get('pip', '0')}",
        f"扩展 {kv.get('extra', '0')}",
    ]
    if "skip" in kv:
        parts.append(f"跳过 {kv['skip']}")
    return " · ".join(parts)


def _format_llm(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return "-"
    if text.startswith("ok"):
        rest = text[2:].strip()
        kv = _kv_pairs(rest)
        bits: list[str] = ["正常"]
        if kv.get("v"):
            bits.append(f"版本 {kv['v']}")
        if kv.get("provider"):
            bits.append(f"通道 {kv['provider']}")
        if kv.get("switches"):
            bits.append(f"开关 {kv['switches']}")
        # 兼容仅有 ok / ok switches=X 以外的尾巴
        leftover = rest
        for key in ("v", "provider", "switches"):
            leftover = re.sub(rf"\b{key}=\S+", "", leftover).strip()
        if leftover and leftover != "ok":
            bits.append(leftover)
        return "，".join(bits) if len(bits) > 1 else bits[0]
    return text


def _format_ingress(raw: str) -> str:
    kv = _kv_pairs(raw)
    if not kv:
        return raw or "-"
    strict_raw = (kv.get("strict") or "").lower()
    strict = "开" if strict_raw in {"1", "true", "yes", "on"} else "关"
    return (
        f"前缀规则 {kv.get('prefix', '-')} · "
        f"精确规则 {kv.get('exact', '-')} · "
        f"模块 {kv.get('modules', '-')} · "
        f"严格模式 {strict}"
    )


def _format_scheduler(raw: str) -> str:
    text = str(raw or "").strip().lower()
    if text in {"ready", "ok", "1", "true"}:
        return "已就绪"
    return raw or "-"


def _format_fact(key: str, value: str) -> str:
    if key == "plugins":
        return _format_plugins(value)
    if key == "llm":
        return _format_llm(value)
    if key == "ingress":
        return _format_ingress(value)
    if key == "scheduler":
        return _format_scheduler(value)
    return value


def _runtime_base_lines() -> list[str]:
    from pallas.core.foundation.bot_version import get_pallas_bot_version_for_reporting
    from pallas.core.platform.bot_runtime.roles import bot_role, is_sharded_worker

    driver = get_driver()
    cfg = driver.config
    role = str(bot_role())
    lines = [
        f"版本：{get_pallas_bot_version_for_reporting()}",
        f"角色：{_role_label(role)}",
    ]

    if is_sharded_worker():
        shard_id = str(os.environ.get("PALLAS_SHARD_ID", "") or "").strip()
        if shard_id:
            lines.append(f"分片：#{shard_id}")

    host = str(getattr(cfg, "host", "") or "").strip() or "0.0.0.0"
    port = getattr(cfg, "port", None)
    if port not in (None, ""):
        lines.append(f"监听：{host}:{port}")

    backend = str(os.environ.get("DB_BACKEND", "") or "").strip().lower()
    if backend:
        lines.append(f"数据库：{_db_label(backend)}")

    return lines


def build_startup_summary_lines(
    *,
    facts: dict[str, str] | None = None,
    warnings: dict[str, str] | None = None,
    base_lines: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """构造中文摘要行；返回 ``(info_lines, warning_lines)``。"""
    runtime = base_lines if base_lines is not None else _runtime_base_lines()
    fact_map = facts if facts is not None else dict(_collector.facts)
    info_lines = [
        "[启动] 就绪",
        *[f"[启动] {line}" for line in runtime],
        *[f"[启动] {_FACT_LABELS.get(key, key)}：{_format_fact(key, value)}" for key, value in fact_map.items()],
    ]

    warn_map = warnings if warnings is not None else dict(_collector.warnings)
    warning_lines = [f"[启动] 降级 · {_WARNING_LABELS.get(key, key)}：{value}" for key, value in warn_map.items()]
    return info_lines, warning_lines


def emit_startup_summary() -> None:
    if _collector.emitted:
        return
    _collector.emitted = True

    info_lines, warning_lines = build_startup_summary_lines()
    for line in info_lines:
        logger.info("{}", line)
    for line in warning_lines:
        logger.warning("{}", line)
