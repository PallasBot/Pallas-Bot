"""Docker CLI：镜像名解析、stderr 启发式、inspect/rm/stop 共用实现。"""

from __future__ import annotations

import asyncio
import shutil
import subprocess


def docker_repository_from_ref(ref: str) -> str:
    s = (ref or "").strip()
    if not s:
        return ""
    if "@" in s:
        s = s.split("@", 1)[0].strip()
    if ":" not in s:
        return s
    i = s.rfind(":")
    rhs = s[i + 1 :]
    if "/" not in rhs:
        return s[:i].strip()
    return s


def docker_stderr_suggests_host_port_bind_conflict(text: str) -> bool:
    t = (text or "").lower()
    return (
        "port is already allocated" in t
        or "ports are not available" in t
        or "address already in use" in t
        or "only one usage of each socket address" in t
    )


def docker_stderr_suggests_container_name_conflict(text: str) -> bool:
    t = (text or "").lower()
    return "already in use" in t and "container" in t


async def docker_inspect_running_async(name: str) -> bool:
    if not shutil.which("docker"):
        return False
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "inspect",
        "-f",
        "{{.State.Running}}",
        name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    if proc.returncode != 0:
        return False
    return b"true" in (out or b"").lower()


def docker_inspect_running_sync(name: str) -> bool:
    if not shutil.which("docker"):
        return False
    try:
        r = subprocess.run(  # noqa: S603
            ["docker", "inspect", "-f", "{{.State.Running}}", name],
            check=False,
            capture_output=True,
            text=True,
            timeout=6,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if r.returncode != 0:
        return False
    return "true" in (r.stdout or "").lower()


async def docker_rm_force_async(name: str) -> None:
    if not shutil.which("docker"):
        return
    p = await asyncio.create_subprocess_exec("docker", "rm", "-f", name, stderr=asyncio.subprocess.DEVNULL)
    await p.wait()


def docker_rm_force_sync(name: str, *, subprocess_timeout: int = 30) -> None:
    if not shutil.which("docker"):
        return
    try:
        subprocess.run(  # noqa: S603
            ["docker", "rm", "-f", name],
            check=False,
            capture_output=True,
            timeout=subprocess_timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


async def docker_stop_async(name: str, *, wait_timeout: int = 60) -> None:
    if not shutil.which("docker"):
        return
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "stop",
        name,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(proc.wait(), timeout=wait_timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()


def docker_stop_sync(name: str, *, subprocess_timeout: int = 60) -> None:
    if not shutil.which("docker"):
        return
    try:
        subprocess.run(["docker", "stop", name], check=False, capture_output=True, timeout=subprocess_timeout)  # noqa: S603
    except (OSError, subprocess.TimeoutExpired):
        pass
