"""聚合启动阶段关键事实，并在启动链尾输出成熟摘要。"""

from __future__ import annotations

import os
import re
import sys
from collections import OrderedDict
from dataclasses import dataclass, field

from nonebot import get_driver, logger

from .logging.bridge import display_log_name, format_plugin_event

_ROLE_LABELS = {
    "unified": "单一运行时",
    "hub": "分片 Hub",
    "worker": "分片 Worker",
}

_FACT_LABELS = {
    "plugins": "插件",
    "plugin_failures": "插件",
    "plugin_slow": "插件",
    "llm": "LLM",
    "ingress": "入站",
    "console": "控制台",
    "scheduler": "调度器",
}

_WARNING_LABELS = {
    "llm": "LLM",
    "console": "控制台",
}


@dataclass(frozen=True)
class StartupEvent:
    state: str
    detail: str


@dataclass
class StartupFactCollector:
    facts: OrderedDict[str, str] = field(default_factory=OrderedDict)
    warnings: OrderedDict[str, str] = field(default_factory=OrderedDict)
    events: OrderedDict[str, StartupEvent] = field(default_factory=OrderedDict)
    emitted: bool = False

    def set_fact(self, key: str, value: str | None) -> None:
        text = str(value or "").strip()
        if text:
            self.facts[key] = text

    def set_warning(self, key: str, value: str | None) -> None:
        text = str(value or "").strip()
        if text:
            self.warnings[key] = text

    def set_event(self, component: str, state: str, detail: str | None = None) -> None:
        name = str(component or "").strip()
        if not name:
            return
        self.events[name] = StartupEvent(state=state, detail=str(detail or "").strip())


_collector = StartupFactCollector()

_BANNER = """\
██████╗  █████╗ ██╗     ██╗      █████╗ ███████╗
██╔══██╗██╔══██╗██║     ██║     ██╔══██╗██╔════╝
██████╔╝███████║██║     ██║     ███████║███████╗
██╔═══╝ ██╔══██║██║     ██║     ██╔══██║╚════██║
██║     ██║  ██║███████╗███████╗██║  ██║███████║
╚═╝     ╚═╝  ╚═╝╚══════╝╚══════╝╚═╝  ╚═╝╚══════╝"""


def _render_banner() -> str:
    """返回纯白 block 字横幅，避免不同终端的颜色差异。"""
    return _BANNER


def emit_startup_banner() -> None:
    sys.stdout.write("\n" + _render_banner() + "\n")
    sys.stdout.flush()


def register_startup_fact(key: str, value: str | None) -> None:
    _collector.set_fact(key, value)


def register_startup_warning(key: str, value: str | None) -> None:
    _collector.set_warning(key, value)


def register_startup_ready(component: str, detail: str | None = None) -> None:
    _collector.set_event(component, "已就绪", detail)


def register_plugin_startup_ready(
    plugin: str,
    commands: list[str] | tuple[str, ...] | None = None,
    detail: str | None = None,
) -> None:
    """将插件的就绪事件并入启动摘要，避免逐插件启动刷屏。

    ``detail`` 为运维中文叙事（如 ``MAA 远控 HTTP 路由已挂载``）；缺省时回退
    ``Plugin [x] registered commands [...]``。
    """
    plugin_id = str(plugin or "").strip()
    if not plugin_id:
        return
    if detail is not None and str(detail).strip():
        detail_text = str(detail).strip()
    else:
        command_names = ", ".join(_command_log_name(command) for command in commands or ()) or "-"
        detail_text = f"Plugin [{plugin_id}] registered commands [{command_names}]"
    _collector.set_event(plugin_id, "plugin_ready", format_plugin_event("ready", detail_text))


def _command_log_name(command: str) -> str:
    name = str(command or "").strip().rsplit(".", maxsplit=1)[-1]
    return "".join(part[:1].upper() + part[1:] for part in re.split(r"[_-]+", name) if part) or "-"


def register_startup_scheduled(component: str, detail: str | None = None) -> None:
    _collector.set_event(component, "已调度", detail)


def register_startup_skipped(component: str, detail: str | None = None) -> None:
    _collector.set_event(component, "已跳过", detail)


def register_startup_degraded(component: str, detail: str | None = None) -> None:
    _collector.set_event(component, "已降级", detail)


def reset_startup_report_for_tests() -> None:
    _collector.facts.clear()
    _collector.warnings.clear()
    _collector.events.clear()
    _collector.emitted = False


def startup_report_snapshot() -> dict[str, dict[str, str] | bool]:
    return {
        "facts": dict(_collector.facts),
        "warnings": dict(_collector.warnings),
        "events": {component: event.state for component, event in _collector.events.items()},
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
    local = int(kv.get("local", "0") or 0)
    bundled_raw = kv.get("src", "") or kv.get("modules", "0")
    bundled_loaded = bundled_raw.split("/", 1)[0]
    bundled = int(bundled_loaded or 0)
    official = int(kv.get("official", kv.get("pip", "0")) or 0)
    nonebot = int(kv.get("nonebot", "0") or 0)
    community = int(kv.get("community", "0") or 0)
    extra = int(kv.get("extra", "0") or 0)
    total = local + bundled + official + nonebot + community + extra
    parts = []
    if local:
        parts.append(f"本地 {local}")
    if bundled:
        parts.append(f"内置 {bundled_raw}")
    if official:
        parts.append(f"官方 {official}")
    if nonebot:
        parts.append(f"NoneBot {nonebot}")
    if community:
        parts.append(f"社区 {community}")
    if extra:
        parts.append(f"额外目录 {extra}")
    text = f"已成功载入 {total} 个插件"
    if parts:
        text += "：" + " | ".join(parts)
    if "skip" in kv:
        text += f" | 配置跳过 {kv['skip']}"
        source_labels = {
            "local": "本地",
            "src": "内置",
            "official": "官方",
            "nonebot": "NoneBot",
            "community": "社区",
            "extra": "额外目录",
        }
        source_parts = []
        for item in (kv.get("skip_sources", "") or "").split(","):
            source, separator, count = item.partition(":")
            if separator and source in source_labels:
                source_parts.append(f"{source_labels[source]} {count}")
        if source_parts:
            text += "：" + " | ".join(source_parts)
    return text


def _format_llm(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return "-"
    if text.startswith("ok"):
        rest = text[2:].strip()
        kv = _kv_pairs(rest)
        bits: list[str] = ["已就绪"]
        if kv.get("v"):
            bits.append(f"版本 {kv['v']}")
        if kv.get("provider"):
            bits.append(f"Provider {kv['provider']}")
        if "model" in kv:
            bits.append("模型未声明" if kv["model"] in {"?", "-"} else f"模型 {kv['model']}")
        if kv.get("chat"):
            bits.append("智能对话已启用" if kv["chat"] == "enabled" else "智能对话未启用")
        # 兼容仅有 ok / ok switches=X 以外的尾巴
        leftover = rest
        for key in ("v", "provider", "model", "chat", "switches"):
            leftover = re.sub(rf"\b{key}=\S+", "", leftover).strip()
        if leftover and leftover != "ok":
            bits.append(leftover)
        if len(bits) > 1:
            return f"{bits[0]}：" + " | ".join(bits[1:])
        return bits[0]
    return text


def _format_ingress(raw: str) -> str:
    kv = _kv_pairs(raw)
    if not kv:
        return raw or "-"
    strict_raw = (kv.get("strict") or "").lower()
    strict = "开" if strict_raw in {"1", "true", "yes", "on"} else "关"
    return (
        f"已载入 {kv.get('prefix', '-')} 条前缀规则、"
        f"{kv.get('exact', '-')} 条精确规则，"
        f"覆盖 {kv.get('modules', '-')} 个模块；"
        f"严格路由{'已启用' if strict == '开' else '未启用'}"
    )


def _format_scheduler(raw: str) -> str:
    text = str(raw or "").strip().lower()
    if text in {"ready", "ok", "1", "true"}:
        return "已就绪"
    return raw or "-"


def _format_console(raw: str) -> str:
    return f"已就绪：{raw}" if raw else "-"


def _format_plugin_failures(raw: str) -> str:
    names = [part.strip() for part in raw.split(",") if part.strip()]
    text = "、".join(part for part in names if not part.startswith("+"))
    overflow = next((part[1:] for part in names if part.startswith("+")), "")
    if overflow:
        text += f"等 {overflow} 个"
    return f"载入失败：{text}" if text else "载入失败"


def _format_slow_plugins(raw: str) -> str:
    parts: list[str] = []
    for item in raw.split(","):
        text = item.strip()
        if not text:
            continue
        if text.startswith("+"):
            parts.append(f"等 {text[1:]} 个")
            continue
        name, sep, elapsed = text.partition("=")
        if name and sep:
            parts.append(f"{name} {elapsed} 秒")
    return f"载入较慢：{'、'.join(parts)}" if parts else "载入较慢"


def _format_fact(key: str, value: str) -> str:
    if key == "plugins":
        return _format_plugins(value)
    if key == "llm":
        return _format_llm(value)
    if key == "ingress":
        return _format_ingress(value)
    if key == "scheduler":
        return _format_scheduler(value)
    if key == "console":
        return _format_console(value)
    if key == "plugin_failures":
        return _format_plugin_failures(value)
    if key == "plugin_slow":
        return _format_slow_plugins(value)
    return value


def _format_command_start(start: list[str] | tuple[str, ...] | None) -> str:
    """把 command_start 整理成可读序列，空串展示为「（无）」；如 [\"\", \"/\"]。"""
    texts = [repr(item) if item else "（无）" for item in (start or [])]
    return "、".join(texts) if texts else "（无）"


def _runtime_base_lines() -> list[str]:
    from pallas.core.foundation.bot_version import get_pallas_bot_version_for_reporting
    from pallas.core.foundation.config.repo_settings import repo_env_raw_value
    from pallas.core.platform.bot_runtime.roles import bot_role, is_sharded_worker

    driver = get_driver()
    cfg = driver.config
    role = str(bot_role())
    lines = [
        f"版本：{get_pallas_bot_version_for_reporting()}",
        f"进程：{_role_label(role)}",
        f"日志级别：{str(repo_env_raw_value('LOG_LEVEL') or 'INFO').upper()}",
    ]

    command_start: list[str] = []
    try:
        from pallas.core.foundation.command_start_config import get_command_start_config

        command_start = list(get_command_start_config().command_start or [])
    except Exception:
        raw = str(getattr(cfg, "command_start", "") or "")
        command_start = [part.strip() for part in raw.split() if part.strip()]
    if command_start:
        lines.append(f"命令前缀：{_format_command_start(command_start)}")

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
    fact_lines = []
    for key, value in fact_map.items():
        formatted = _format_fact(key, value)
        if key == "plugins":
            fact_lines.append(f"[初始化] {formatted}")
        else:
            fact_lines.append(f"[{_FACT_LABELS.get(key, key)}] {formatted}")
    info_lines = [
        "[初始化] Pallas-Bot 已就绪",
        *[f"[初始化] {line}" for line in runtime],
        *fact_lines,
    ]
    for component, event in _collector.events.items():
        if event.state == "plugin_ready":
            info_lines.append(event.detail)
            continue
        if event.state != "已降级":
            detail = f"：{event.detail}" if event.detail else ""
            info_lines.append(f"[{component}] {event.state}{detail}")

    warn_map = warnings if warnings is not None else dict(_collector.warnings)
    warning_lines = [f"[{_WARNING_LABELS.get(key, key)}] 已降级：{value}" for key, value in warn_map.items()]
    for component, event in _collector.events.items():
        if event.state == "已降级":
            detail = f"：{event.detail}" if event.detail else ""
            warning_lines.append(f"[{component}] 已降级{detail}")
    return info_lines, warning_lines


def emit_startup_summary() -> None:
    if _collector.emitted:
        return
    _collector.emitted = True

    info_lines, warning_lines = build_startup_summary_lines()
    ready_details = {event.detail for event in _collector.events.values() if event.state == "plugin_ready"}
    for line in info_lines:
        if line in ready_details:
            continue
        logger.info("{}", line)
    for component, event in _collector.events.items():
        if event.state == "plugin_ready":
            display = display_log_name(str(component)) or "Plugin"
            logger.bind(display_name=display).info("{}", event.detail)
    for line in warning_lines:
        logger.warning("{}", line)
