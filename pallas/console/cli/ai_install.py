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
    managed_ai_root,
    resolve_ai_repo_root,
    sibling_ai_root,
)

_AI_BOOTSTRAP = "scripts/ai_bootstrap.sh"
AI_REPO_GIT_URL = "https://github.com/PallasBot/Pallas-Bot-AI.git"
AI_REPO_DIR_NAME = "Pallas-Bot-AI"


def default_ai_clone_target() -> Path:
    """默认克隆目标：PALLAS_AI_ROOT 或 data/runtimes/pallas-bot-ai。"""
    override = os.environ.get("PALLAS_AI_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return managed_ai_root()


def docker_compose_hint() -> str:
    return (
        "Docker 全栈：compose 已注入 AI_SERVER_HOST=pallasbot-ai；控制台探测该地址，"
        "不在 Bot 容器内 clone AI。宿主机启停示例：\n"
        "  docker compose -f docker-compose.full.yml up -d\n"
        "  # 仅 AI 栈（在 Pallas-Bot-AI 仓）\n"
        "  docker compose -f docker-compose.llm.yml up -d\n"
        "  # 默认 slim AI、不预拉模型；预拉可加 --profile pull-models\n"
        "详见文档：docs/maintainer/install/ai-runtime.md / docs/deploy/docker.md"
    )


def forbid_ai_clone(*, runtime: dict[str, Any] | None = None) -> bool:
    """Docker / 非本机 AI_SERVER 时禁止在 Bot 进程内 clone。"""
    from pallas.console.cli.ai_supervisor import is_loopback_host, resolve_configured_ai_endpoint, running_in_docker

    if running_in_docker():
        return True
    host, _port = resolve_configured_ai_endpoint()
    if not is_loopback_host(host):
        return True
    if runtime and runtime.get("layout") in {"docker", "remote"} and runtime.get("running"):
        return True
    return False


def ai_install_status() -> dict[str, Any]:
    from pallas.console.cli.ai_supervisor import (
        ai_root_layout,
        ai_runtime_status,
        is_managed_ai_root,
        resolve_configured_ai_endpoint,
        running_in_docker,
    )

    target = default_ai_clone_target()
    resolved = resolve_ai_repo_root()
    git_ok = shutil.which("git") is not None
    bootstrap = (resolved / _AI_BOOTSTRAP) if resolved else (target / _AI_BOOTSTRAP)
    runtime = ai_runtime_status(ai_root=resolved)
    layout = str(runtime.get("layout") or (ai_root_layout(resolved) if resolved else "missing"))
    if resolved is None and layout == "missing":
        # remote probe may have set docker/remote already
        layout = str(runtime.get("layout") or "missing")
    host, port = resolve_configured_ai_endpoint()
    forbid_clone = forbid_ai_clone(runtime=runtime)
    can_clone = git_ok and resolved is None and not target.exists() and not forbid_clone
    detected = (
        resolved is not None
        or bool(runtime.get("running"))
        or (runtime.get("layout") in {"docker", "remote"} and bool((runtime.get("health") or {}).get("ok")))
    )
    return {
        "detected": detected,
        "ai_root": str(resolved) if resolved else None,
        "clone_target": str(target),
        "managed_root": str(managed_ai_root()),
        "sibling_root": str(sibling_ai_root()),
        "layout": layout,
        "deployment": "source" if resolved is not None else ("docker" if running_in_docker() else layout),
        "is_managed": is_managed_ai_root(resolved),
        "bootstrap_script": str(bootstrap),
        "bootstrap_ready": bootstrap.is_file() if resolved or target.exists() else False,
        "git_available": git_ok,
        "can_clone": can_clone,
        "can_bootstrap": resolved is not None and (resolved / _AI_BOOTSTRAP).is_file(),
        "in_docker": running_in_docker(),
        "endpoint": {"host": host, "port": port},
        "docker_hint": docker_compose_hint(),
        "git_url": AI_REPO_GIT_URL,
        "runtime": runtime,
    }


def clone_ai_repo(*, target: Path | None = None, git_url: str = AI_REPO_GIT_URL) -> Path:
    """Clone 到受控默认路径；已存在则报错。"""
    from pallas.console.cli.ai_supervisor import mark_ai_root_managed

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
    mark_ai_root_managed(dest)
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
    from pallas.console.cli.ai_supervisor import is_managed_ai_root, mark_ai_root_managed

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
    if completed.returncode == 0 and is_managed_ai_root(ai_root):
        mark_ai_root_managed(ai_root)
    return int(completed.returncode), header + out
