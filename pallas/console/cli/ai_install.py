"""Pallas-Bot-AI 源码安装：状态探测、受控 clone、bootstrap。"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pallas.console.cli.ai_ops import (
    default_bot_callback_host,
    default_bot_callback_port,
    managed_ai_root,
    resolve_ai_repo_root,
    sibling_ai_root,
)

if TYPE_CHECKING:
    from collections.abc import Callable

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
        "当前 Bot 在 Docker 内，无法在此页安装或启停媒体服务。\n"
        "请在宿主机用 compose 管理 AI，控制台只填连接地址并测通。\n"
        "全栈示例见文档站 Docker 部署「全栈」：\n"
        "  https://PallasBot.github.io/Pallas-Bot-Docs/deploy/docker\n"
        "或在 Pallas-Bot-AI 仓使用其 LLM compose。\n"
        "全栈编排通常已注入 AI_SERVER_HOST=pallasbot-ai。"
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
    can_bootstrap = resolved is not None and (resolved / _AI_BOOTSTRAP).is_file()
    can_update = (
        git_ok
        and resolved is not None
        and is_managed_ai_root(resolved)
        and (resolved / ".git").exists()
        and (resolved / _AI_BOOTSTRAP).is_file()
        and not forbid_clone
    )
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
        "can_bootstrap": can_bootstrap,
        "can_update": can_update,
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
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or "").strip() or f"exit {completed.returncode}"
        raise RuntimeError(f"git clone 失败: {err}")
    if not (dest / _AI_BOOTSTRAP).is_file():
        raise RuntimeError(f"克隆完成但缺少 {_AI_BOOTSTRAP}")
    mark_ai_root_managed(dest)
    return dest


def _git_run(ai_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ai_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def update_ai_repo(*, ai_root: Path | None = None) -> dict[str, Any]:
    """托管目录 ``git pull --ff-only``（含 submodule）；非托管 / Docker 远端禁止。"""
    from pallas.console.cli.ai_supervisor import is_managed_ai_root, mark_ai_root_managed

    root = ai_root or resolve_ai_repo_root()
    if root is None:
        raise FileNotFoundError("未找到 AI Runtime 目录")
    root = root.resolve()
    if forbid_ai_clone():
        raise RuntimeError("当前环境禁止在进程内更新 AI Runtime（Docker / 远端请在宿主机更新）")
    if not is_managed_ai_root(root):
        raise PermissionError(
            "仅允许更新控制台托管的 AI Runtime（data/runtimes/pallas-bot-ai）；同级手工克隆请自行 git pull"
        )
    if not (root / ".git").exists():
        raise RuntimeError(f"不是 git 仓库，无法更新: {root}")
    if not (root / _AI_BOOTSTRAP).is_file():
        raise RuntimeError(f"缺少 {_AI_BOOTSTRAP}")
    if not shutil.which("git"):
        raise RuntimeError("未找到 git，无法更新")

    before = _git_run(root, "rev-parse", "HEAD")
    if before.returncode != 0:
        raise RuntimeError(f"无法读取当前提交: {(before.stderr or before.stdout or '').strip()}")
    before_sha = (before.stdout or "").strip()

    fetch = _git_run(root, "fetch", "--prune", "origin")
    if fetch.returncode != 0:
        err = (fetch.stderr or fetch.stdout or "").strip() or f"exit {fetch.returncode}"
        raise RuntimeError(f"git fetch 失败: {err}")

    upstream = _git_run(root, "rev-parse", "--abbrev-ref", "@{u}")
    if upstream.returncode == 0 and (upstream.stdout or "").strip():
        pull = _git_run(root, "pull", "--ff-only", "--autostash")
        pull_desc = (upstream.stdout or "").strip()
    else:
        pull = _git_run(root, "pull", "--ff-only", "--autostash", "origin", "main")
        pull_desc = "origin/main"
        if pull.returncode != 0:
            pull = _git_run(root, "pull", "--ff-only", "--autostash", "origin", "master")
            pull_desc = "origin/master"

    if pull.returncode != 0:
        err = (pull.stderr or pull.stdout or "").strip() or f"exit {pull.returncode}"
        raise RuntimeError(f"git pull --ff-only 失败（{pull_desc}）: {err}")

    after = _git_run(root, "rev-parse", "HEAD")
    after_sha = (after.stdout or "").strip() if after.returncode == 0 else ""

    sub = _git_run(root, "submodule", "update", "--init", "--recursive")
    mark_ai_root_managed(root)

    chunks = [
        fetch.stdout or "",
        fetch.stderr or "",
        pull.stdout or "",
        pull.stderr or "",
        sub.stdout or "",
        sub.stderr or "",
    ]
    result: dict[str, Any] = {
        "ai_root": str(root),
        "before": before_sha,
        "after": after_sha,
        "changed": bool(before_sha and after_sha and before_sha != after_sha),
        "upstream": pull_desc,
        "output_tail": "".join(chunks)[-4000:],
        "submodule_ok": sub.returncode == 0,
    }
    if sub.returncode != 0:
        result["submodule_error"] = (sub.stderr or sub.stdout or "").strip() or f"exit {sub.returncode}"
    return result


def run_ai_bootstrap_captured(
    *,
    ai_root: Path,
    check_only: bool = False,
    no_start: bool = False,
    with_media: bool = True,
    remote_only: bool = False,
    use_gpu: bool = False,
    bot_host: str | None = None,
    bot_port: int | None = None,
    on_output_line: Callable[[str], None] | None = None,
) -> tuple[int, str]:
    """运行 bootstrap，返回 (exit_code, combined_output)。默认媒体栈。

    ``on_output_line`` 按行回调 stdout/stderr 合并流（不含命令头）。
    """
    del with_media, remote_only
    from pallas.console.cli.ai_supervisor import is_managed_ai_root, mark_ai_root_managed
    from pallas.console.cli.process_util import bash_missing_message, bash_script_cmd

    script = ai_root / _AI_BOOTSTRAP
    if not script.is_file():
        return 1, f"未找到 {script}"

    cmd = bash_script_cmd(script)
    if cmd is None:
        return 1, bash_missing_message(purpose="AI Runtime bootstrap")

    if check_only:
        cmd.append("--check-only")
    if no_start:
        cmd.append("--no-start")
    cmd.extend(["--bot-host", bot_host or default_bot_callback_host()])
    cmd.extend(["--bot-port", str(bot_port if bot_port is not None else default_bot_callback_port())])

    env = os.environ.copy()
    if use_gpu:
        env["PALLAS_GPU"] = "1"

    # 中文 Windows 默认 GBK；bootstrap/uv 多为 UTF-8，勿用 locale 解码。
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")

    header = f"执行: {' '.join(cmd)}\nAI 仓: {ai_root}\n"
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=ai_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except OSError as err:
        return 1, f"无法执行 bootstrap: {err}"

    chunks: list[str] = []
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            chunks.append(raw)
            if on_output_line is not None:
                on_output_line(raw.rstrip("\n"))
        code = int(proc.wait())
    except Exception as err:  # noqa: BLE001
        try:
            proc.kill()
        except OSError:
            pass
        return 1, header + "".join(chunks) + f"\nbootstrap 读取失败: {err}"

    out = "".join(chunks)
    if code == 0 and is_managed_ai_root(ai_root):
        mark_ai_root_managed(ai_root)
    return code, header + out
