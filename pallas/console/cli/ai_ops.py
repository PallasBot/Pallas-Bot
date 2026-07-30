from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

from pallas.console.cli.process_util import bash_missing_message, bash_script_cmd, env_for_nested_project
from pallas.core.foundation.config.repo_settings import repo_config_path
from pallas.core.foundation.paths import DATA_ROOT, PROJECT_ROOT

_AI_BOOTSTRAP = "scripts/ai_bootstrap.sh"
AI_REPO_DIR_NAME = "Pallas-Bot-AI"
AI_RUNTIME_DIR_NAME = "pallas-bot-ai"


def managed_ai_root() -> Path:
    """Bot 托管安装默认路径：data/runtimes/pallas-bot-ai。"""
    return (DATA_ROOT / "runtimes" / AI_RUNTIME_DIR_NAME).resolve()


def sibling_ai_root() -> Path:
    return (PROJECT_ROOT.parent / AI_REPO_DIR_NAME).resolve()


def resolve_ai_repo_root() -> Path | None:
    """解析已安装的 AI Runtime 根目录。

    优先级：PALLAS_AI_ROOT → data/runtimes/pallas-bot-ai → 同级 Pallas-Bot-AI。
    """
    override = os.environ.get("PALLAS_AI_ROOT", "").strip()
    if override:
        root = Path(override).expanduser().resolve()
        if (root / _AI_BOOTSTRAP).is_file():
            return root
        return None
    managed = managed_ai_root()
    if (managed / _AI_BOOTSTRAP).is_file():
        return managed
    sibling = sibling_ai_root()
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
    with_media: bool = True,
    remote_only: bool = False,
    use_gpu: bool = False,
    bot_host: str | None = None,
    bot_port: int | None = None,
) -> int:
    """调用 AI 仓 bootstrap（默认媒体栈）。

    ``with_media`` / ``remote_only`` 保留兼容，不再传给脚本。
    """
    del with_media, remote_only
    script = ai_root / _AI_BOOTSTRAP
    if not script.is_file():
        print(f"未找到 {script}", file=sys.stderr)
        return 1

    cmd = bash_script_cmd(script)
    if cmd is None:
        print(bash_missing_message(purpose="AI Runtime bootstrap"), file=sys.stderr)
        return 1

    if check_only:
        cmd.append("--check-only")
    if no_start:
        cmd.append("--no-start")
    cmd.extend(["--bot-host", bot_host or default_bot_callback_host()])
    cmd.extend(["--bot-port", str(bot_port if bot_port is not None else default_bot_callback_port())])

    env = env_for_nested_project()
    if use_gpu:
        env["PALLAS_GPU"] = "1"

    print(f"执行: {' '.join(cmd)}")
    print(f"AI 仓: {ai_root}")
    try:
        completed = subprocess.run(cmd, cwd=ai_root, env=env, check=False)
    except OSError as err:
        print(f"无法执行 bootstrap: {err}", file=sys.stderr)
        return 1
    return int(completed.returncode)
