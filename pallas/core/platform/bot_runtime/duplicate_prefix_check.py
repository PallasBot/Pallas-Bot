"""启动后扫描重复命令 prefix（多插件模块注册同一口令）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nonebot import logger
from nonebot.matcher import matchers
from nonebot.rule import CommandRule, ShellCommandRule

from pallas.core.foundation.config.repo_settings import repo_env_raw_value
from pallas.core.platform.ingress.matcher_activation import iter_matcher_checker_calls

if TYPE_CHECKING:
    from nonebot.matcher import Matcher

_COMMAND_CHECKERS = frozenset({CommandRule, ShellCommandRule})


@dataclass(frozen=True, slots=True)
class DuplicatePrefixConflict:
    command: str
    modules: tuple[str, ...]


def duplicate_prefix_strict() -> bool:
    raw = repo_env_raw_value("PALLAS_DUPLICATE_PREFIX_STRICT")
    if raw is None:
        return False
    text = str(raw).strip().lower()
    return text in ("1", "true", "yes", "on")


def matcher_plugin_module(matcher: type[Matcher]) -> str:
    name = str(getattr(matcher, "plugin_name", "") or "").strip()
    return name or "unknown"


def collect_duplicate_command_prefixes() -> list[DuplicatePrefixConflict]:
    cmd_to_modules: dict[str, set[str]] = {}

    for priority_matchers in matchers.values():
        for matcher in priority_matchers:
            module = matcher_plugin_module(matcher)
            for call in iter_matcher_checker_calls(matcher):
                if type(call) not in _COMMAND_CHECKERS:
                    continue
                for cmd in call.cmds:
                    cmd_key = cmd[0] if len(cmd) == 1 else " ".join(cmd)
                    cmd_to_modules.setdefault(cmd_key, set()).add(module)

    conflicts: list[DuplicatePrefixConflict] = []
    for cmd_key, modules in sorted(cmd_to_modules.items()):
        if len(modules) < 2:
            continue
        conflicts.append(DuplicatePrefixConflict(command=cmd_key, modules=tuple(sorted(modules))))
    return conflicts


def run_duplicate_prefix_check() -> None:
    conflicts = collect_duplicate_command_prefixes()
    if not conflicts:
        return
    doc = "docs/maintainer/install/ai-runtime.md"
    for item in conflicts:
        logger.error(
            '重复命令 prefix "{}" 对应多个插件模块: {}（见 {}）',
            item.command,
            ", ".join(item.modules),
            doc,
        )
    if duplicate_prefix_strict():
        raise RuntimeError(f"检测到 {len(conflicts)} 个重复命令 prefix")


def register_duplicate_prefix_startup_check() -> None:
    from nonebot import get_driver

    @get_driver().on_startup
    async def check_duplicate_command_prefixes_on_startup() -> None:
        run_duplicate_prefix_check()
