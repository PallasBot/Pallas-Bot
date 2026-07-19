from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

from pallas.core.foundation.config.repo_settings import repo_config_path
from pallas.core.foundation.paths import PROJECT_ROOT

_AI_BOOTSTRAP = "scripts/ai_bootstrap.sh"


def resolve_ai_repo_root() -> Path | None:
    override = os.environ.get("PALLAS_AI_ROOT", "").strip()
    if override:
        root = Path(override).expanduser().resolve()
        if (root / _AI_BOOTSTRAP).is_file():
            return root
        return None
    sibling = (PROJECT_ROOT.parent / "Pallas-Bot-AI").resolve()
    if (sibling / _AI_BOOTSTRAP).is_file():
        return sibling
    return None


def default_bot_callback_host() -> str:
    return "127.0.0.1"


def default_bot_callback_port() -> int:
    path = repo_config_path()
    if path.is_file():
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            data = {}
        bootstrap = data.get("bootstrap")
        if isinstance(bootstrap, dict) and bootstrap.get("port") is not None:
            try:
                return int(bootstrap["port"])
            except (TypeError, ValueError):
                pass
    for key in ("PORT", "BOT_PORT"):
        raw = os.environ.get(key, "").strip()
        if raw.isdigit():
            return int(raw)
    return 8088


def run_ai_bootstrap(
    *,
    ai_root: Path,
    check_only: bool = False,
    no_start: bool = False,
    with_media: bool = False,
    remote_only: bool = False,
    use_gpu: bool = False,
    bot_host: str | None = None,
    bot_port: int | None = None,
) -> int:
    script = ai_root / _AI_BOOTSTRAP
    if not script.is_file():
        print(f"未找到 {script}", file=sys.stderr)
        return 1

    cmd = [str(script)]
    if check_only:
        cmd.append("--check-only")
    if no_start:
        cmd.append("--no-start")
    if with_media:
        cmd.append("--with-media")
    if remote_only:
        cmd.append("--remote-only")
    cmd.extend(["--bot-host", bot_host or default_bot_callback_host()])
    cmd.extend(["--bot-port", str(bot_port if bot_port is not None else default_bot_callback_port())])

    env = os.environ.copy()
    if use_gpu:
        env["PALLAS_GPU"] = "1"

    print(f"执行: {' '.join(cmd)}")
    print(f"AI 仓: {ai_root}")
    completed = subprocess.run(cmd, cwd=ai_root, env=env, check=False)
    return int(completed.returncode)
