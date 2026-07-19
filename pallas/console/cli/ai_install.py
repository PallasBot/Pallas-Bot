"""Pallas-Bot-AI 源码安装：状态探测、受控 clone、bootstrap。"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from pallas.console.cli.ai_ops import (
    default_bot_callback_host,
    default_bot_callback_port,
    resolve_ai_repo_root,
)
from pallas.core.foundation.paths import PROJECT_ROOT

_AI_BOOTSTRAP = "scripts/ai_bootstrap.sh"
AI_REPO_GIT_URL = "https://github.com/PallasBot/Pallas-Bot-AI.git"
AI_REPO_DIR_NAME = "Pallas-Bot-AI"


def default_ai_clone_target() -> Path:
    override = os.environ.get("PALLAS_AI_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (PROJECT_ROOT.parent / AI_REPO_DIR_NAME).resolve()


def docker_compose_hint() -> str:
    return (
        "Docker 部署请在宿主机执行（本控制台不代跑 docker）：\n"
        "  # 仅 AI 栈（在 Pallas-Bot-AI 仓）\n"
        "  docker compose -f docker-compose.llm.yml up -d\n"
        "  # 或与 Bot 同编排（在 Pallas-Bot 仓）\n"
        "  docker compose -f docker-compose.full.yml up -d\n"
        "详见文档：docs/maintainer/install/ai-runtime.md"
    )


def ai_install_status() -> dict[str, Any]:
    target = default_ai_clone_target()
    resolved = resolve_ai_repo_root()
    git_ok = shutil.which("git") is not None
    bootstrap = (resolved / _AI_BOOTSTRAP) if resolved else (target / _AI_BOOTSTRAP)
    return {
        "detected": resolved is not None,
        "ai_root": str(resolved) if resolved else None,
        "clone_target": str(target),
        "bootstrap_script": str(bootstrap),
        "bootstrap_ready": bootstrap.is_file() if resolved or target.exists() else False,
        "git_available": git_ok,
        "can_clone": git_ok and resolved is None and not target.exists(),
        "can_bootstrap": resolved is not None and (resolved / _AI_BOOTSTRAP).is_file(),
        "docker_hint": docker_compose_hint(),
        "git_url": AI_REPO_GIT_URL,
    }


def clone_ai_repo(*, target: Path | None = None, git_url: str = AI_REPO_GIT_URL) -> Path:
    """Clone 到受控默认路径；已存在则报错。"""
    dest = (target or default_ai_clone_target()).resolve()
    allowed = default_ai_clone_target().resolve()
    if dest != allowed:
        raise ValueError(f"仅允许克隆到受控路径: {allowed}")
    if dest.exists():
        raise FileExistsError(f"目标已存在: {dest}")
    if not shutil.which("git"):
        raise RuntimeError("未找到 git，无法克隆")
    parent = dest.parent
    parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        ["git", "clone", "--depth", "1", git_url, str(dest)],
        cwd=parent,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or "").strip() or f"exit {completed.returncode}"
        raise RuntimeError(f"git clone 失败: {err}")
    if not (dest / _AI_BOOTSTRAP).is_file():
        raise RuntimeError(f"克隆完成但缺少 {_AI_BOOTSTRAP}")
    return dest


def run_ai_bootstrap_captured(
    *,
    ai_root: Path,
    check_only: bool = False,
    no_start: bool = False,
    with_media: bool = False,
    remote_only: bool = False,
    use_gpu: bool = False,
    bot_host: str | None = None,
    bot_port: int | None = None,
) -> tuple[int, str]:
    """运行 bootstrap，返回 (exit_code, combined_output)。"""
    script = ai_root / _AI_BOOTSTRAP
    if not script.is_file():
        return 1, f"未找到 {script}"

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

    completed = subprocess.run(
        cmd,
        cwd=ai_root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    out = (completed.stdout or "") + (completed.stderr or "")
    header = f"执行: {' '.join(cmd)}\nAI 仓: {ai_root}\n"
    return int(completed.returncode), header + out
