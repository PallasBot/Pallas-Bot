"""Pallas-Bot 运行版本探测。"""

from __future__ import annotations

import importlib.metadata
import os
import re
import subprocess
import tomllib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

_SHA_TAIL_RE = re.compile(r"\s*·\s*[0-9a-f]{4,40}\b", re.IGNORECASE)
_GIT_TAIL_RE = re.compile(r"\s+git\s+[0-9a-f]{4,40}\s*$", re.IGNORECASE)
_PLUS_G_RE = re.compile(r"\+g[0-9a-f]{4,40}", re.IGNORECASE)
_BRACKET_SHA_RE = re.compile(r"\[[0-9a-f]{4,40}\]", re.IGNORECASE)
_PAREN_SHA_RE = re.compile(r"\s*\(\s*[0-9a-f]{7,40}\s*\)\s*$", re.IGNORECASE)


def pallas_bot_repo_root() -> Path:
    from pallas.core.foundation.paths import PROJECT_ROOT

    return PROJECT_ROOT


def display_version_without_sha(value: str | None) -> str:
    """与 WebUI ``displayVersionWithoutSha`` 一致：展示时去掉常见 git 哈希片段。"""
    raw = (value or "").strip()
    if not raw:
        return ""
    s = raw
    s = _SHA_TAIL_RE.sub("", s)
    s = _GIT_TAIL_RE.sub("", s)
    s = _PLUS_G_RE.sub("", s)
    s = _BRACKET_SHA_RE.sub("", s)
    s = _PAREN_SHA_RE.sub("", s)
    return s.strip()


def get_bot_current_version() -> dict[str, str]:
    root = pallas_bot_repo_root()
    tag = ""
    commit = ""
    try:
        tag = subprocess.check_output(
            ["git", "describe", "--tags", "--exact-match"],
            cwd=root,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:  # noqa: BLE001
        pass
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:  # noqa: BLE001
        pass
    return {"tag": tag, "commit": commit}


def get_pallas_bot_version_for_health() -> str:
    """供 ``/health`` 的 ``pallas_bot``：优先环境变量、git describe，其次已安装发行版号，最后 pyproject。"""
    env = (os.environ.get("PALLAS_BOT_VERSION") or os.environ.get("PALLAS_VERSION") or "").strip()
    if env:
        return env
    root = pallas_bot_repo_root()
    try:
        desc = subprocess.check_output(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=root,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3.0,
        ).strip()
        if desc:
            return desc
    except Exception:  # noqa: BLE001
        pass
    try:
        v = importlib.metadata.version("pallas-bot")
        if v.strip():
            return v.strip()
    except importlib.metadata.PackageNotFoundError:
        pass
    try:
        data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        return str(data.get("project", {}).get("version", "")).strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def get_pallas_bot_version_for_reporting() -> str:
    """社区心跳 / 对外聚合：与 WebUI ``pallasBotVersionLabel`` 同源。"""
    tag = str(get_bot_current_version().get("tag") or "").strip()
    if tag:
        cleaned = display_version_without_sha(tag)
        return cleaned or tag
    raw = get_pallas_bot_version_for_health().strip()
    if not raw:
        return "unknown"
    cleaned = display_version_without_sha(raw)
    return cleaned or raw
