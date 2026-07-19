"""插件「有无新版本」快照：社区插件比对 git commit，官方扩展比对 PyPI 版本。

商店行（plugin_registry / community_plugin_registry）读取本快照得到精确的
``has_update`` 语义，而不是「能否执行更新动作」。快照由用户手动触发或每天 4 点
定时任务刷新，落盘到 pb_webui 数据目录，重启后仍可用。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from nonebot import logger

# 单插件检查超时，控制 git ls-remote / PyPI 查询的最坏耗时。
_PER_PLUGIN_TIMEOUT_S = 15.0
# 整轮刷新的并发上限，避免一次性打满网络与子进程。
_MAX_CONCURRENCY = 6
_SNAPSHOT_FILENAME = "plugin_update_snapshot.json"


def _snapshot_path():
    # 直接走 foundation 路径，避免 import packages.pb_webui
    # （预导入会让后续 nonebot.load_plugin 报 already exists / not loaded as plugin）
    from pallas.core.foundation.paths import plugin_data_dir

    return plugin_data_dir("pb_webui") / _SNAPSHOT_FILENAME


def load_snapshot() -> dict[str, Any]:
    """读取磁盘快照；不存在或损坏时返回空快照（不抛异常）。"""
    path = _snapshot_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("Pallas-Bot 控制台: 插件更新快照损坏，忽略 path={}", path)
        return {}
    return data if isinstance(data, dict) else {}


def _save_snapshot(data: dict[str, Any]) -> None:
    path = _snapshot_path()
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        logger.warning("Pallas-Bot 控制台: 插件更新快照写盘失败 err={}", exc)


def community_update_entry(plugin_id: str) -> dict[str, Any] | None:
    """取某社区插件的更新判定；无快照返回 None（前端按 unknown 处理）。"""
    snap = load_snapshot()
    entry = (snap.get("community") or {}).get(plugin_id)
    return entry if isinstance(entry, dict) else None


def official_update_entry(package: str) -> dict[str, Any] | None:
    """取某官方扩展包的更新判定；无快照返回 None。"""
    snap = load_snapshot()
    entry = (snap.get("official") or {}).get(package)
    return entry if isinstance(entry, dict) else None


def snapshot_checked_at() -> float | None:
    snap = load_snapshot()
    ts = snap.get("checked_at")
    return float(ts) if isinstance(ts, (int, float)) else None


async def _community_remote_head(repository_url: str, ref: str) -> str | None:
    """git ls-remote 取远端 ref 的 commit；失败返回 None。"""
    from pallas.console.webui.community_plugin_install import run_git_command

    try:
        code, out, _ = await run_git_command(
            _PER_PLUGIN_TIMEOUT_S,
            "ls-remote",
            repository_url,
            ref,
        )
    except Exception:  # noqa: BLE001 — 网络/超时/命令缺失统一降级为 unknown
        return None
    if code != 0:
        return None
    first = (out or "").strip().split("\n", 1)[0].strip()
    sha = first.split("\t", 1)[0].strip() if first else ""
    return sha or None


async def _community_local_head(plugin_id: str) -> str | None:
    from pallas.console.webui.community_plugin_install import (
        local_plugin_installed,
        plugin_install_path,
        run_git_command,
    )

    if not local_plugin_installed(plugin_id):
        return None
    dest = plugin_install_path(plugin_id)
    if not (dest / ".git").exists():
        return None
    try:
        code, out, _ = await run_git_command(
            _PER_PLUGIN_TIMEOUT_S,
            "rev-parse",
            "HEAD",
            cwd=str(dest),
        )
    except Exception:  # noqa: BLE001
        return None
    if code != 0:
        return None
    sha = (out or "").strip()
    return sha or None


async def _check_community(entry: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    plugin_id = str(entry["plugin_id"])
    ref = str(entry.get("ref") or "main").strip() or "main"
    repo = str(entry.get("repository_url") or "").strip()
    result: dict[str, Any] = {"has_update": None, "installed_ref": None, "latest_ref": None, "error": None}

    local_head = await _community_local_head(plugin_id)
    if local_head is None:
        result["error"] = "本地非 git 仓库或未安装"
        return plugin_id, result
    result["installed_ref"] = local_head[:12]

    if not repo:
        # 无远端地址（local_only）无法比对，保持 unknown。
        result["error"] = "无远端仓库地址"
        return plugin_id, result

    remote_head = await _community_remote_head(repo, ref)
    if remote_head is None:
        result["error"] = "远端版本获取失败"
        return plugin_id, result
    result["latest_ref"] = remote_head[:12]
    result["has_update"] = local_head != remote_head
    return plugin_id, result


def _installed_package_version(package: str) -> str | None:
    import importlib.metadata

    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None
    except Exception:  # noqa: BLE001
        return None


def _version_is_newer(latest: str, installed: str) -> bool:
    latest = (latest or "").strip()
    installed = (installed or "").strip()
    if not latest or not installed:
        return False
    if latest == installed:
        return False
    try:
        from packaging.version import InvalidVersion, Version

        try:
            return Version(latest) > Version(installed)
        except InvalidVersion:
            return latest != installed
    except ImportError:
        return latest != installed


async def _pypi_latest_version(package: str) -> str | None:
    import httpx

    url = f"https://pypi.org/pypi/{package}/json"
    try:
        async with httpx.AsyncClient(timeout=_PER_PLUGIN_TIMEOUT_S) as client:
            resp = await client.get(url, headers={"Accept": "application/json"})
            resp.raise_for_status()
            data = resp.json()
    except Exception:  # noqa: BLE001 — 网络/解析失败统一降级
        return None
    version = ((data.get("info") or {}).get("version")) if isinstance(data, dict) else None
    return str(version).strip() if version else None


async def _check_official(package: str) -> tuple[str, dict[str, Any]]:
    result: dict[str, Any] = {"has_update": None, "installed_ref": None, "latest_ref": None, "error": None}
    installed = _installed_package_version(package)
    if not installed:
        result["error"] = "未通过 pip 安装"
        return package, result
    result["installed_ref"] = installed

    latest = await _pypi_latest_version(package)
    if not latest:
        result["error"] = "PyPI 版本获取失败"
        return package, result
    result["latest_ref"] = latest
    result["has_update"] = _version_is_newer(latest, installed)
    return package, result


async def _gather_limited(coros: list) -> list:
    sem = asyncio.Semaphore(_MAX_CONCURRENCY)

    async def _run(coro):
        async with sem:
            try:
                return await coro
            except Exception as exc:  # noqa: BLE001
                logger.warning("Pallas-Bot 控制台: 插件更新检查异常 err={}", exc)
                return None

    return await asyncio.gather(*[_run(c) for c in coros])


async def refresh_plugin_update_snapshot() -> dict[str, Any]:
    """重新比对全部商店插件的版本，落盘并返回新快照。"""
    from pallas.console.webui.community_plugin_index import load_community_plugin_index_safe
    from pallas.core.platform.bot_runtime.plugin_matrix import EXTRA_PLUGIN_PACKAGES

    index = await load_community_plugin_index_safe()
    community_entries = [e for e in (index.get("plugins") or []) if isinstance(e, dict) and e.get("plugin_id")]
    packages = sorted(set(EXTRA_PLUGIN_PACKAGES.values()))

    community_results, official_results = await asyncio.gather(
        _gather_limited([_check_community(e) for e in community_entries]),
        _gather_limited([_check_official(pkg) for pkg in packages]),
    )

    community: dict[str, Any] = {}
    for item in community_results:
        if item is None:
            continue
        plugin_id, payload = item
        community[plugin_id] = payload

    official: dict[str, Any] = {}
    for item in official_results:
        if item is None:
            continue
        package, payload = item
        official[package] = payload

    snapshot = {
        "checked_at": time.time(),
        "community": community,
        "official": official,
    }
    _save_snapshot(snapshot)
    logger.info(
        "Pallas-Bot 控制台: 插件更新快照已刷新 community={} official={}",
        len(community),
        len(official),
    )
    return snapshot
