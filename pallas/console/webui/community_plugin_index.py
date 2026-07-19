"""社区插件索引：本地文件或远程 JSON。"""

from __future__ import annotations

import json
from typing import Any

import httpx
from nonebot import logger

from pallas.core.foundation.config.repo_settings import repo_env_raw_value
from pallas.core.foundation.paths import PROJECT_ROOT

INDEX_FETCH_TIMEOUT_S = 15.0
DEFAULT_INDEX_REL = "config/community_plugin_index.json"
LOCAL_INDEX_REL = "data/pallas_config/community_plugin_index.json"
# 官方策展索引（独立仓）；拉取失败时回退本地文件
DEFAULT_COMMUNITY_PLUGIN_INDEX_URL = (
    "https://raw.githubusercontent.com/PallasBot/community-plugin-index/main/index.json"
)


class CommunityIndexError(Exception):
    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


def community_plugin_index_url() -> str | None:
    raw = (repo_env_raw_value("COMMUNITY_PLUGIN_INDEX_URL") or "").strip()
    if raw:
        return raw
    return DEFAULT_COMMUNITY_PLUGIN_INDEX_URL


def normalize_index_entry(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    plugin_id = str(raw.get("id") or raw.get("plugin_id") or "").strip()
    if not plugin_id:
        return None
    repo = str(raw.get("repository") or raw.get("repository_url") or "").strip()
    if not repo:
        return None
    name = str(raw.get("name") or plugin_id).strip() or plugin_id
    description = str(raw.get("description") or "").strip()
    ref = str(raw.get("ref") or raw.get("branch") or "main").strip() or "main"
    author = str(raw.get("author") or "").strip()
    homepage = str(raw.get("homepage") or "").strip()
    tags_raw = raw.get("tags")
    tags: list[str] = []
    if isinstance(tags_raw, list):
        tags = [str(t).strip() for t in tags_raw if str(t).strip()]
    min_version = str(raw.get("min_pallas_version") or "").strip()
    icon = str(raw.get("icon") or "").strip()
    cover = str(raw.get("cover") or "").strip()
    avatar = str(raw.get("avatar") or "").strip()
    return {
        "plugin_id": plugin_id,
        "name": name,
        "description": description,
        "repository_url": repo,
        "ref": ref,
        "author": author,
        "homepage": homepage or None,
        "icon": icon or None,
        "cover": cover or None,
        "avatar": avatar or None,
        "tags": tags,
        "min_pallas_version": min_version or None,
    }


def parse_index_document(raw: object) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(raw, dict):
        msg = "索引 JSON 须为对象"
        raise CommunityIndexError(msg)
    meta = {
        "version": raw.get("version"),
        "updated_at": raw.get("updated_at"),
        "description": raw.get("description"),
    }
    entries_raw = raw.get("plugins")
    if not isinstance(entries_raw, list):
        msg = "索引缺少 plugins 数组"
        raise CommunityIndexError(msg)
    plugins: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in entries_raw:
        entry = normalize_index_entry(item)
        if entry is None:
            continue
        pid = entry["plugin_id"]
        if pid in seen:
            continue
        seen.add(pid)
        plugins.append(entry)
    return meta, plugins


def load_index_from_path(path: object) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    file_path = PROJECT_ROOT / str(path)
    if not file_path.is_file():
        msg = f"索引文件不存在：{file_path.relative_to(PROJECT_ROOT)}"
        raise CommunityIndexError(msg)
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        msg = f"读取索引失败：{e}"
        raise CommunityIndexError(msg) from e
    meta, plugins = parse_index_document(raw)
    return f"file:{file_path.relative_to(PROJECT_ROOT).as_posix()}", meta, plugins


async def fetch_index_from_url(url: str) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    try:
        async with httpx.AsyncClient(timeout=INDEX_FETCH_TIMEOUT_S, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            raw = resp.json()
    except httpx.HTTPError as e:
        msg = f"拉取社区索引失败：{e}"
        raise CommunityIndexError(msg) from e
    except json.JSONDecodeError as e:
        msg = f"社区索引 JSON 无效：{e}"
        raise CommunityIndexError(msg) from e
    meta, plugins = parse_index_document(raw)
    return f"url:{url}", meta, plugins


async def load_community_plugin_index() -> dict[str, Any]:
    """返回 { source, meta, plugins }。远程索引失败时回退本地文件。"""
    url = community_plugin_index_url()
    if url:
        try:
            source, meta, plugins = await fetch_index_from_url(url)
            return {"source": source, "meta": meta, "plugins": plugins}
        except CommunityIndexError as e:
            logger.warning("社区插件索引远程拉取失败，回退本地：{}", e.detail)
    local_path = PROJECT_ROOT / LOCAL_INDEX_REL
    if local_path.is_file():
        source, meta, plugins = load_index_from_path(local_path)
        return {"source": source, "meta": meta, "plugins": plugins}
    source, meta, plugins = load_index_from_path(DEFAULT_INDEX_REL)
    return {"source": source, "meta": meta, "plugins": plugins}


async def load_community_plugin_index_safe() -> dict[str, Any]:
    try:
        return await load_community_plugin_index()
    except CommunityIndexError as e:
        logger.warning("社区插件索引：{}", e.detail)
        return {"source": "error", "meta": {}, "plugins": [], "error": e.detail}
