"""插件商店资源快照：README / icon / cover / avatar 定时拉取到独立静态目录。"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from nonebot import logger

from pallas.core.foundation.paths import plugin_data_dir

_SNAPSHOT_FILENAME = "plugin_store_assets_snapshot.json"
_PUBLIC_PREFIX = "/pallas/store-assets"
_MAX_CONCURRENCY = 6
_HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_GITHUB_RAW_RE = re.compile(r"github\.com[/:]([^/]+)/([^/.]+?)(?:\.git)?(?:/|$)", re.IGNORECASE)


def snapshot_path() -> Path:
    return plugin_data_dir("pb_webui", create=True) / _SNAPSHOT_FILENAME


def load_snapshot() -> dict[str, Any]:
    path = snapshot_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("Pallas-Bot 控制台: 插件商店资源快照损坏，忽略 path={}", path)
        return {}
    return data if isinstance(data, dict) else {}


def snapshot_has_assets_for_kind(kind: str) -> bool:
    bucket = load_snapshot().get((kind or "").strip())
    if not isinstance(bucket, dict) or not bucket:
        return False
    for entry in bucket.values():
        if not isinstance(entry, dict):
            continue
        assets = entry.get("assets")
        if not isinstance(assets, dict):
            continue
        for asset in assets.values():
            if not isinstance(asset, dict):
                continue
            public_url = str(asset.get("public_url") or "").strip()
            relative_path = str(asset.get("relative_path") or "").strip()
            if public_url or relative_path:
                return True
    return False


def save_snapshot(data: dict[str, Any]) -> None:
    path = snapshot_path()
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        logger.warning("Pallas-Bot 控制台: 插件商店资源快照写盘失败 err={}", exc)


def _public_root() -> Path:
    return plugin_data_dir("pb_webui", create=True) / "store-assets"


def _asset_target_id(kind: str, row: dict[str, Any]) -> str:
    return str(row["package"] if kind == "official" else row["plugin_id"]).strip()


def _safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-") or "asset"


def _parse_repo(repository_url: str | None) -> tuple[str, str] | None:
    raw = (repository_url or "").strip()
    match = _GITHUB_RAW_RE.search(raw)
    if not match:
        return None
    owner = match.group(1).strip()
    repo = match.group(2).strip()
    if not owner or not repo:
        return None
    return owner, repo


def _guess_suffix(url: str, content_type: str = "") -> str:
    path = urlparse(url).path
    suffix = Path(path).suffix.lower()
    if suffix:
        return suffix
    guessed = mimetypes.guess_extension((content_type or "").split(";", 1)[0].strip()) or ""
    if guessed == ".jpe":
        return ".jpg"
    return guessed or ".bin"


def _readme_public_rel(kind: str, target_id: str) -> str:
    return f"readme/{kind}-{_safe_name(target_id)}.md"


def _changelog_public_rel(kind: str, target_id: str) -> str:
    return f"changelog/{kind}-{_safe_name(target_id)}.md"


def _asset_public_rel(kind: str, asset_type: str, target_id: str, suffix: str) -> str:
    clean_suffix = suffix if suffix.startswith(".") else f".{suffix}"
    return f"{asset_type}/{kind}-{_safe_name(target_id)}{clean_suffix}"


def _public_url_from_rel(relative_path: str) -> str:
    rel = relative_path.replace("\\", "/").strip("/")
    return f"{_PUBLIC_PREFIX}/{rel}"


def _resolve_path(relative_path: str) -> Path:
    rel = Path(relative_path)
    return _public_root() / rel


def _snapshot_entry(snapshot: dict[str, Any], kind: str, target_id: str) -> dict[str, Any]:
    bucket = snapshot.setdefault(kind, {})
    entry = bucket.setdefault(target_id, {})
    if not isinstance(entry, dict):
        entry = {}
        bucket[target_id] = entry
    return entry


def resolve_store_cached_visual_urls(kind: str, target_id: str) -> dict[str, str | None]:
    """从商店资源快照读取已缓存的 cover/icon/avatar URL。"""
    clean_kind = (kind or "").strip()
    clean_id = (target_id or "").strip()
    if not clean_kind or not clean_id:
        return {"cover": None, "icon": None, "avatar": None}
    entry = (load_snapshot().get(clean_kind) or {}).get(clean_id) or {}
    if not isinstance(entry, dict):
        return {"cover": None, "icon": None, "avatar": None}
    assets = entry.get("assets")
    if not isinstance(assets, dict):
        return {"cover": None, "icon": None, "avatar": None}
    result: dict[str, str | None] = {"cover": None, "icon": None, "avatar": None}
    for asset_type in ("cover", "icon", "avatar"):
        asset = assets.get(asset_type)
        if not isinstance(asset, dict):
            continue
        public_url = str(asset.get("public_url") or "").strip()
        if public_url:
            result[asset_type] = public_url
    return result


def resolve_store_cached_visual_urls_for_plugin(plugin_id: str) -> dict[str, str | None]:
    pid = (plugin_id or "").strip()
    if not pid:
        return {"cover": None, "icon": None, "avatar": None}
    community = resolve_store_cached_visual_urls("community", pid)
    if community.get("cover") or community.get("icon") or community.get("avatar"):
        return community
    from pallas.core.platform.bot_runtime.plugin_matrix import extra_package_for_plugin

    package = extra_package_for_plugin(pid)
    if package:
        official = resolve_store_cached_visual_urls("official", package)
        if official.get("cover") or official.get("icon") or official.get("avatar"):
            return official
    return {"cover": None, "icon": None, "avatar": None}


def apply_asset_snapshot_to_rows(kind: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from pallas.console.webui.plugin_catalog import resolve_catalog_visuals

    out: list[dict[str, Any]] = []
    for row in rows:
        copied = dict(row)
        if kind == "official":
            plugin_ids = copied.get("plugin_ids") or []
            plugin_id = str(plugin_ids[0] if plugin_ids else copied.get("package") or "").strip()
            plugin_source = "extra"
        else:
            plugin_id = str(copied.get("plugin_id") or "").strip()
            plugin_source = "local" if copied.get("local_installed") else "pip"
        if not plugin_id:
            out.append(copied)
            continue
        visuals = resolve_catalog_visuals(
            plugin_id=plugin_id,
            plugin_source=plugin_source,
        )
        for asset_type in ("icon", "cover", "avatar"):
            value = visuals.get(asset_type)
            if value:
                copied[asset_type] = value
        out.append(copied)
    return out


def get_cached_readme_markdown(kind: str, target_id: str) -> str | None:
    snapshot = load_snapshot()
    entry = (snapshot.get(kind) or {}).get(target_id) or {}
    if not isinstance(entry, dict):
        return None
    readme = entry.get("readme") or {}
    if not isinstance(readme, dict):
        return None
    relative_path = str(readme.get("relative_path") or "").strip()
    if not relative_path:
        return None
    path = _resolve_path(relative_path)
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None
    return text or None


def get_cached_changelog_markdown(kind: str, target_id: str) -> str | None:
    snapshot = load_snapshot()
    entry = (snapshot.get(kind) or {}).get(target_id) or {}
    if not isinstance(entry, dict):
        return None
    changelog = entry.get("changelog") or {}
    if not isinstance(changelog, dict):
        return None
    relative_path = str(changelog.get("relative_path") or "").strip()
    if not relative_path:
        return None
    path = _resolve_path(relative_path)
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None
    return text or None


def resolve_readme_request_id(kind: str, target_id: str) -> str:
    clean_kind = (kind or "").strip()
    clean_id = (target_id or "").strip()
    if clean_kind != "official" or not clean_id:
        return clean_id
    from pallas.core.platform.bot_runtime.plugin_matrix import extra_package_for_plugin

    return extra_package_for_plugin(clean_id) or clean_id


async def collect_store_asset_targets() -> dict[str, list[dict[str, Any]]]:
    from pallas.console.webui.community_plugin_index import load_community_plugin_index_safe
    from pallas.console.webui.community_plugin_registry import resolve_community_plugin_avatar
    from pallas.core.platform.bot_runtime.plugin_matrix import (
        EXTRA_PLUGIN_PACKAGES,
        official_extension_repo_url,
        official_extension_visuals,
    )

    official: list[dict[str, Any]] = []
    for package in sorted(set(EXTRA_PLUGIN_PACKAGES.values())):
        repo_url = official_extension_repo_url(package)
        visuals = official_extension_visuals(package)
        official.append({
            "id": package,
            "repository_url": repo_url,
            "assets": {
                "icon": visuals.get("icon"),
                "cover": visuals.get("cover"),
                "avatar": visuals.get("avatar"),
            },
            "readme_urls": _github_readme_urls(repo_url),
            "changelog_urls": _github_changelog_urls(repo_url),
        })

    index = await load_community_plugin_index_safe()
    community: list[dict[str, Any]] = []
    for row in index.get("plugins") or []:
        if not isinstance(row, dict) or not row.get("plugin_id"):
            continue
        community.append({
            "id": str(row["plugin_id"]).strip(),
            "repository_url": row.get("repository_url"),
            "assets": {
                "icon": row.get("icon"),
                "cover": row.get("cover"),
                "avatar": resolve_community_plugin_avatar(row),
            },
            "readme_urls": _github_readme_urls(row.get("repository_url")),
            "changelog_urls": _github_changelog_urls(row.get("repository_url")),
        })
    return {"official": official, "community": community}


def _find_target(kind: str, target_id: str) -> dict[str, Any] | None:
    targets = run_async(collect_store_asset_targets())
    for target in targets.get(kind, []) or []:
        if not isinstance(target, dict):
            continue
        if str(target.get("id") or "").strip() == target_id:
            return target
    return None


def _github_readme_urls(repository_url: str | None) -> list[str]:
    parsed = _parse_repo(repository_url)
    if not parsed:
        return []
    owner, repo = parsed
    return [
        f"https://raw.githubusercontent.com/{owner}/{repo}/refs/heads/main/README.md",
        f"https://raw.githubusercontent.com/{owner}/{repo}/refs/heads/master/README.md",
        f"https://raw.githubusercontent.com/{owner}/{repo}/main/README.md",
        f"https://raw.githubusercontent.com/{owner}/{repo}/master/README.md",
    ]


# 约定优先：CHANGELOG.md（Keep a Changelog）置于仓库根目录；docs/ 作为次选。
_CHANGELOG_FILENAMES = ("CHANGELOG.md", "docs/CHANGELOG.md", "CHANGELOG.MD", "changelog.md")


def _github_changelog_urls(repository_url: str | None) -> list[str]:
    parsed = _parse_repo(repository_url)
    if not parsed:
        return []
    owner, repo = parsed
    urls: list[str] = []
    for branch in ("main", "master"):
        for name in _CHANGELOG_FILENAMES:
            urls.extend((
                f"https://raw.githubusercontent.com/{owner}/{repo}/refs/heads/{branch}/{name}",
                f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{name}",
            ))
    return urls


async def _download_binary(url: str) -> tuple[bytes, str]:
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content, str(resp.headers.get("content-type") or "")


async def _download_text_first(urls: list[str]) -> tuple[str, str]:
    last_exc: Exception | None = None
    for url in urls:
        raw = str(url or "").strip()
        if not raw:
            continue
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
                resp = await client.get(raw)
                resp.raise_for_status()
                return resp.text, raw
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            continue
    if last_exc is not None:
        raise last_exc
    raise ValueError("no readme urls")


async def _download_text(url: str) -> str:
    text, _source = await _download_text_first([url])
    return text


def _write_bytes(relative_path: str, content: bytes) -> None:
    path = _resolve_path(relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(content)
    tmp.replace(path)


def _write_text(relative_path: str, content: str) -> None:
    path = _resolve_path(relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _normalize_existing_asset(
    asset: dict[str, Any] | None,
    *,
    fallback_url: str | None = None,
) -> dict[str, Any] | None:
    if not isinstance(asset, dict):
        return None
    source_url = str(asset.get("source_url") or fallback_url or "").strip()
    public_url = str(asset.get("public_url") or "").strip()
    relative_path = str(asset.get("relative_path") or "").strip()
    if not public_url and not relative_path and not source_url:
        return None
    return {
        "source_url": source_url or None,
        "public_url": public_url or None,
        "relative_path": relative_path or None,
        "updated_at": asset.get("updated_at"),
        "error": asset.get("error"),
    }


async def _refresh_one(kind: str, target: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    target_id = str(target["id"]).strip()
    entry: dict[str, Any] = {
        "repository_url": str(target.get("repository_url") or "").strip() or None,
        "assets": {},
        "readme": None,
        "changelog": None,
    }
    prev_assets = previous.get("assets") if isinstance(previous.get("assets"), dict) else {}
    for asset_type, source_url in (target.get("assets") or {}).items():
        if asset_type not in ("icon", "cover", "avatar"):
            continue
        raw_url = str(source_url or "").strip()
        prev_asset = _normalize_existing_asset(prev_assets.get(asset_type), fallback_url=raw_url)
        if not raw_url:
            if prev_asset:
                entry["assets"][asset_type] = prev_asset
            continue
        if raw_url.startswith("/pallas/"):
            entry["assets"][asset_type] = {
                "source_url": raw_url,
                "public_url": raw_url,
                "relative_path": None,
                "updated_at": time.time(),
                "error": None,
            }
            continue
        try:
            content, content_type = await _download_binary(raw_url)
            rel = _asset_public_rel(kind, asset_type, target_id, _guess_suffix(raw_url, content_type))
            _write_bytes(rel, content)
            entry["assets"][asset_type] = {
                "source_url": raw_url,
                "public_url": _public_url_from_rel(rel),
                "relative_path": rel,
                "updated_at": time.time(),
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            if prev_asset:
                prev_asset["error"] = str(exc)
                entry["assets"][asset_type] = prev_asset
            else:
                entry["assets"][asset_type] = {
                    "source_url": raw_url,
                    "public_url": None,
                    "relative_path": None,
                    "updated_at": None,
                    "error": str(exc),
                }

    readme_urls = target.get("readme_urls")
    if not isinstance(readme_urls, list):
        legacy = str(target.get("readme_url") or "").strip()
        readme_urls = [legacy] if legacy else []
    readme_urls = [str(url or "").strip() for url in readme_urls if str(url or "").strip()]
    prev_readme = previous.get("readme") if isinstance(previous.get("readme"), dict) else None
    if readme_urls:
        try:
            markdown, source_url = await _download_text_first(readme_urls)
            rel = _readme_public_rel(kind, target_id)
            _write_text(rel, markdown)
            entry["readme"] = {
                "source_url": source_url,
                "public_url": _public_url_from_rel(rel),
                "relative_path": rel,
                "updated_at": time.time(),
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            if prev_readme:
                entry["readme"] = {
                    **prev_readme,
                    "error": str(exc),
                }
            else:
                entry["readme"] = {
                    "source_url": readme_urls[0],
                    "public_url": None,
                    "relative_path": None,
                    "updated_at": None,
                    "error": str(exc),
                }
    elif prev_readme:
        entry["readme"] = prev_readme

    changelog_urls = target.get("changelog_urls")
    if not isinstance(changelog_urls, list):
        changelog_urls = []
    changelog_urls = [str(url or "").strip() for url in changelog_urls if str(url or "").strip()]
    prev_changelog = previous.get("changelog") if isinstance(previous.get("changelog"), dict) else None
    if changelog_urls:
        try:
            markdown, source_url = await _download_text_first(changelog_urls)
            rel = _changelog_public_rel(kind, target_id)
            _write_text(rel, markdown)
            entry["changelog"] = {
                "source_url": source_url,
                "public_url": _public_url_from_rel(rel),
                "relative_path": rel,
                "updated_at": time.time(),
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            # 仓库未提供 CHANGELOG.md 属正常情况；保留旧缓存（若有）。
            if prev_changelog:
                entry["changelog"] = {**prev_changelog, "error": str(exc)}
            else:
                entry["changelog"] = None
    elif prev_changelog:
        entry["changelog"] = prev_changelog
    else:
        entry["changelog"] = None
    return target_id, entry


async def refresh_store_asset_snapshot() -> dict[str, Any]:
    previous = load_snapshot()
    targets = await collect_store_asset_targets()
    snapshot: dict[str, Any] = {"checked_at": time.time(), "official": {}, "community": {}}
    sem = asyncio.Semaphore(_MAX_CONCURRENCY)

    async def _run(kind: str, target: dict[str, Any]):
        async with sem:
            previous_bucket = (previous.get(kind) or {}) if isinstance(previous.get(kind), dict) else {}
            prev = previous_bucket.get(target["id"]) or {}
            if not isinstance(prev, dict):
                prev = {}
            return await _refresh_one(kind, target, prev)

    for kind in ("official", "community"):
        items = [t for t in targets.get(kind, []) if isinstance(t, dict) and t.get("id")]
        results = await asyncio.gather(*[_run(kind, item) for item in items])
        snapshot[kind] = dict(results)

    save_snapshot(snapshot)
    return snapshot


async def fetch_and_cache_readme_markdown(
    kind: str,
    target_id: str,
    *,
    repository_url: str | None = None,
) -> str | None:
    resolved_id = resolve_readme_request_id(kind, target_id)
    if not resolved_id:
        return None
    target = _find_target(kind, resolved_id) or _find_target(kind, target_id)
    if target is None and repository_url:
        target = {
            "id": resolved_id,
            "repository_url": str(repository_url or "").strip() or None,
            "assets": {},
            "readme_urls": _github_readme_urls(repository_url),
        }
    if not target:
        return None
    previous_bucket = load_snapshot().get(kind) or {}
    previous = previous_bucket.get(resolved_id) or {}
    if not isinstance(previous, dict):
        previous = {}
    _, entry = await _refresh_one(kind, target, previous)
    snapshot = load_snapshot()
    bucket = snapshot.setdefault(kind, {})
    bucket[resolved_id] = entry
    snapshot["checked_at"] = time.time()
    save_snapshot(snapshot)
    return get_cached_readme_markdown(kind, resolved_id)


async def fetch_and_cache_changelog_markdown(
    kind: str,
    target_id: str,
    *,
    repository_url: str | None = None,
) -> str | None:
    resolved_id = resolve_readme_request_id(kind, target_id)
    if not resolved_id:
        return None
    target = _find_target(kind, resolved_id) or _find_target(kind, target_id)
    if target is None and repository_url:
        target = {
            "id": resolved_id,
            "repository_url": str(repository_url or "").strip() or None,
            "assets": {},
            "readme_urls": [],
            "changelog_urls": _github_changelog_urls(repository_url),
        }
    if not target:
        return None
    previous_bucket = load_snapshot().get(kind) or {}
    previous = previous_bucket.get(resolved_id) or {}
    if not isinstance(previous, dict):
        previous = {}
    # 仅刷新 changelog，避免无谓重抓 README/图标；复用旧 entry 的其余字段。
    refresh_target = {
        "id": resolved_id,
        "repository_url": target.get("repository_url"),
        "assets": {},
        "readme_urls": [],
        "changelog_urls": target.get("changelog_urls") or _github_changelog_urls(target.get("repository_url")),
    }
    _, fresh = await _refresh_one(kind, refresh_target, previous)
    snapshot = load_snapshot()
    bucket = snapshot.setdefault(kind, {})
    existing = bucket.get(resolved_id) if isinstance(bucket.get(resolved_id), dict) else {}
    merged = dict(existing) if isinstance(existing, dict) else {}
    merged["changelog"] = fresh.get("changelog")
    if not merged.get("repository_url"):
        merged["repository_url"] = fresh.get("repository_url")
    bucket[resolved_id] = merged
    snapshot["checked_at"] = time.time()
    save_snapshot(snapshot)
    return get_cached_changelog_markdown(kind, resolved_id)


def run_async(awaitable):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    raise RuntimeError("run_async cannot be used inside a running event loop")
