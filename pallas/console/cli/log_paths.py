"""默认日志路径（unified+aux 心智；分片为进阶）与实时跟随。"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Sequence  # noqa: TC003
from dataclasses import dataclass, field
from pathlib import Path  # noqa: TC003

from pallas.console.cli.runtime_mode import resolve_bot_mode
from pallas.core.foundation.paths import PROJECT_ROOT

BOT_LOG_DIR = PROJECT_ROOT / "data" / "bot"
UNIFIED_LAUNCHER_LOG_DIR = PROJECT_ROOT / "data" / "pallas_unified" / "logs"
UNIFIED_BOT_LOG = UNIFIED_LAUNCHER_LOG_DIR / "bot.log"
EMBED_AUX_LOG = PROJECT_ROOT / "data" / "pallas_embed" / "logs" / "embed.log"
WORK_AUX_LOG = PROJECT_ROOT / "data" / "pallas_work" / "logs" / "work.log"
SHARD_HUB_LOG = PROJECT_ROOT / "data" / "pallas_shard" / "logs" / "hub.log"
SHARD_LOG_DIR = PROJECT_ROOT / "data" / "pallas_shard" / "logs"


def default_primary_log(*, mode: str = "auto") -> Path:
    resolved = resolve_bot_mode(mode)
    if resolved == "shard":
        return SHARD_HUB_LOG
    return UNIFIED_BOT_LOG


def latest_bot_log() -> Path | None:
    try:
        return max(BOT_LOG_DIR.glob("nonebot_*.log"), key=lambda path: path.stat().st_mtime)
    except (OSError, ValueError):
        return None


def list_default_log_targets(*, mode: str = "auto") -> list[tuple[str, Path]]:
    """返回 (标签, 路径)；优先业务日志，默认不枚举 worker-N。"""
    resolved = resolve_bot_mode(mode)
    bot_log = latest_bot_log()
    bot_targets = [("Bot 业务日志", bot_log)] if bot_log is not None else []
    if resolved == "shard":
        targets: list[tuple[str, Path]] = [
            *bot_targets,
            ("hub", SHARD_HUB_LOG),
            ("work 辅进程", WORK_AUX_LOG),
            ("embed 辅进程", EMBED_AUX_LOG),
        ]
        return targets
    return [
        *bot_targets,
        ("启动器日志目录", UNIFIED_LAUNCHER_LOG_DIR),
        ("work 辅进程", WORK_AUX_LOG),
        ("embed 辅进程", EMBED_AUX_LOG),
    ]


def read_log_tail(path: Path, *, lines: int = 40) -> str:
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    parts = text.splitlines()
    if lines <= 0:
        return text
    return "\n".join(parts[-lines:])


def latest_unified_launcher_log() -> Path | None:
    """最新启动器日志 ``bot_*.log``；后台运行每次启动生成一个新文件。"""
    try:
        return max(UNIFIED_LAUNCHER_LOG_DIR.glob("bot_*.log"), key=lambda path: path.stat().st_mtime)
    except (OSError, ValueError):
        return None


FollowTarget = Path | Callable[[], Path | None]


def resolve_follow_targets(*, mode: str = "auto") -> list[tuple[str, FollowTarget]]:
    """实时跟随目标：目录项解析为动态的最新启动器日志，Bot 业务日志保持最新文件。"""
    targets: list[tuple[str, FollowTarget]] = []
    for label, path in list_default_log_targets(mode=mode):
        if path.is_dir():
            targets.append(("启动器日志", latest_unified_launcher_log))
        else:
            targets.append((label, path))
    return targets


def primary_follow_target(*, mode: str = "auto") -> tuple[str, FollowTarget]:
    """默认实时跟随目标：unified 跟 Bot 业务日志，分片跟 hub。"""
    resolved = resolve_bot_mode(mode)
    if resolved == "shard":
        return ("hub", SHARD_HUB_LOG)
    targets = resolve_follow_targets(mode=mode)
    if targets:
        return targets[0]
    return ("启动器日志", latest_unified_launcher_log)


@dataclass
class _FollowState:
    path: Path | None = None
    offset: int = 0
    size: int | None = None
    pending: str = field(default_factory=str)


def stream_log_targets(
    targets: Sequence[tuple[str, FollowTarget]],
    *,
    lines: int = 10,
    poll: float = 0.2,
) -> Iterator[tuple[str, str]]:
    """持续产出 ``(label, line)``：先补打各文件末尾 N 行，随后跟随新增行。

    文件被截断/重建（轮转）或动态解析到新文件时自动切换跟随；目录或缺失文件跳过，
    之后出现时也会被跟上。无新增内容时不产出（等待轮询）。
    """
    states: dict[str, _FollowState] = {}
    while True:
        for label, target in targets:
            path = target() if callable(target) else target
            state = states.setdefault(label, _FollowState())
            if path is None or path.is_dir() or not path.is_file():
                state.path = None
                continue
            if state.path != path:
                if state.path is not None:
                    yield label, f"== 日志切换，跟随 {path.name} =="
                try:
                    size = path.stat().st_size
                except OSError:
                    size = 0
                state.path = path
                state.offset = size
                state.size = size
                state.pending = ""
                if lines > 0:
                    for line in read_log_tail(path, lines=lines).splitlines():
                        yield label, line
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if state.size is not None and size < state.size:
                yield label, f"== {path.name} 已轮转，重新跟随 =="
                state.offset = 0
                state.pending = ""
            if size > state.offset:
                try:
                    with path.open("r", encoding="utf-8", errors="replace") as fh:
                        fh.seek(state.offset)
                        chunk = fh.read()
                except OSError:
                    continue
                raw = state.pending + chunk
                parts = raw.split("\n")
                *complete, tail = parts
                for line in complete:
                    if line:
                        yield label, line
                state.pending = tail
                state.offset = size
            state.size = size
        time.sleep(poll)
