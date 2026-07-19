"""社区插件资源 URL：从 Git 仓库推断图标等。"""

from __future__ import annotations

import re
from typing import Any

_GITHUB_REPO_RE = re.compile(
    r"(?:https?://|git@)github\.com[/:]([^/]+)/([^/.]+?)(?:\.git)?/?$",
    flags=re.IGNORECASE,
)
_GITEE_REPO_RE = re.compile(
    r"https?://gitee\.com/([^/]+)/([^/.]+?)(?:\.git)?/?$",
    flags=re.IGNORECASE,
)

ICON_CANDIDATE_PATHS = (
    "assets/icon.png",
    "assets/icon.webp",
    "assets/icon.svg",
    "assets/avatar.png",
    "assets/avatar.jpg",
    "icon.png",
    "avatar.png",
)

AVATAR_CANDIDATE_PATHS = (
    "assets/avatar.png",
    "assets/avatar.jpg",
    "assets/avatar.webp",
    "assets/avatar.svg",
    "avatar.png",
    "avatar.jpg",
    "avatar.webp",
    "avatar.svg",
)

COVER_CANDIDATE_PATHS = (
    "assets/cover.webp",
    "assets/cover.png",
    "assets/cover.jpg",
    "cover.webp",
    "cover.png",
    "cover.jpg",
    "assets/banner.webp",
    "assets/banner.png",
)


def parse_git_host_repo(repository_url: str) -> tuple[str, str, str] | None:
    """解析 GitHub / Gitee 仓库，返回 (host, owner, repo)。"""
    raw = (repository_url or "").strip()
    if not raw:
        return None
    match = _GITHUB_REPO_RE.match(raw)
    if match:
        owner, repo = match.group(1).strip(), match.group(2).strip()
        if owner and repo:
            return "github", owner, repo
    match = _GITEE_REPO_RE.match(raw)
    if match:
        owner, repo = match.group(1).strip(), match.group(2).strip()
        if owner and repo:
            return "gitee", owner, repo
    return None


def raw_file_url(host: str, owner: str, repo: str, ref: str, path: str) -> str:
    branch = (ref or "main").strip() or "main"
    if host == "gitee":
        return f"https://gitee.com/{owner}/{repo}/raw/{branch}/{path}"
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"


def infer_community_plugin_icon(repository_url: str, ref: str = "main") -> str | None:
    parsed = parse_git_host_repo(repository_url)
    if parsed is None:
        return None
    host, owner, repo = parsed
    return raw_file_url(host, owner, repo, ref, ICON_CANDIDATE_PATHS[0])


def infer_community_plugin_avatar(repository_url: str, ref: str = "main") -> str | None:
    parsed = parse_git_host_repo(repository_url)
    if parsed is None:
        return None
    host, owner, repo = parsed
    return raw_file_url(host, owner, repo, ref, AVATAR_CANDIDATE_PATHS[0])


def infer_community_plugin_cover(repository_url: str, ref: str = "main") -> str | None:
    parsed = parse_git_host_repo(repository_url)
    if parsed is None:
        return None
    host, owner, repo = parsed
    return raw_file_url(host, owner, repo, ref, COVER_CANDIDATE_PATHS[0])


def resolve_community_plugin_icon(entry: dict[str, Any]) -> str | None:
    explicit = str(entry.get("icon") or "").strip()
    if explicit:
        return explicit
    repo = str(entry.get("repository_url") or entry.get("repository") or "").strip()
    ref = str(entry.get("ref") or "main").strip() or "main"
    return infer_community_plugin_icon(repo, ref)


def resolve_community_plugin_avatar_asset(entry: dict[str, Any]) -> str | None:
    explicit = str(entry.get("avatar") or "").strip()
    if explicit:
        return explicit
    repo = str(entry.get("repository_url") or entry.get("repository") or "").strip()
    ref = str(entry.get("ref") or "main").strip() or "main"
    return infer_community_plugin_avatar(repo, ref)


def resolve_community_plugin_cover(entry: dict[str, Any]) -> str | None:
    explicit = str(entry.get("cover") or "").strip()
    if explicit:
        return explicit
    repo = str(entry.get("repository_url") or entry.get("repository") or "").strip()
    ref = str(entry.get("ref") or "main").strip() or "main"
    return infer_community_plugin_cover(repo, ref)
