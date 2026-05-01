"""GitHub Release 工具函数。

提供：
- :func:`github_release_api_url` — 构造 GitHub Releases API URL
- :func:`github_auth_headers` — Bearer 鉴权头（API / 网页下载链可选）
- :func:`github_release_asset_url` / :func:`github_release_asset_url_candidates` — releases/download 直链
- :func:`release_tag_from_github_final_url` — 从 ``…/releases/tag/{tag}`` 解析 tag
- :func:`fetch_latest_release_tag_via_github_web` — API 不可用时经 github.com 跳转解析最新 tag
- :func:`fetch_github_releases` — 获取 release 列表（含 assets）
- :func:`fetch_latest_release` — 获取最新单条 release 摘要
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, unquote, urlparse

import httpx


def github_release_api_url(repo: str, tag: str = "") -> str:
    """返回 GitHub Releases API URL。

    - ``tag`` 为空 → ``/releases/latest``
    - ``tag`` 非空 → ``/releases/tags/{tag}``
    """
    owner, _, name = (repo or "").strip().partition("/")
    if not owner or not name:
        msg = f"无效的 GitHub 仓库名: {repo!r}，应为 Owner/Repo"
        raise ValueError(msg)
    if not (tag or "").strip():
        return f"https://api.github.com/repos/{owner}/{name}/releases/latest"
    return f"https://api.github.com/repos/{owner}/{name}/releases/tags/{tag.strip()}"


def github_auth_headers(token: str = "") -> dict[str, str]:
    """构造 GitHub API 鉴权头；token 为空时返回空字典。"""
    t = (token or "").strip()
    if not t:
        return {}
    return {"Authorization": f"Bearer {t}"}


_github_auth_headers = github_auth_headers


def github_release_asset_url(repo: str, asset_name: str, tag: str = "") -> str:
    """GitHub Releases 网页直链（latest/download 或 tag/download）。"""
    owner_part, _, name_part = (repo or "").strip().partition("/")
    if not owner_part or not name_part:
        msg = f"无效的 GitHub 仓库名: {repo!r}，应为 Owner/Repo"
        raise ValueError(msg)
    encoded = quote((asset_name or "").strip(), safe=".")
    if not encoded:
        raise ValueError("发布资产名不能为空")
    if not (tag or "").strip():
        return f"https://github.com/{owner_part}/{name_part}/releases/latest/download/{encoded}"
    return f"https://github.com/{owner_part}/{name_part}/releases/download/{(tag or '').strip()}/{encoded}"


def github_release_asset_url_candidates(repo: str, asset_name: str, tag: str = "") -> list[str]:
    """返回可尝试的下载地址：优先固定 tag，其次 latest。"""
    out: list[str] = []
    tag_clean = (tag or "").strip()
    if tag_clean:
        out.append(github_release_asset_url(repo, asset_name, tag_clean))
    out.append(github_release_asset_url(repo, asset_name, ""))
    dedup: list[str] = []
    seen: set[str] = set()
    for u in out:
        if u in seen:
            continue
        seen.add(u)
        dedup.append(u)
    return dedup


def release_tag_from_github_final_url(url: str) -> str:
    """从跳转后的 GitHub releases 页 URL 解析 tag（``…/releases/tag/{tag}``）。"""
    segments = [s for s in urlparse(url).path.split("/") if s]
    for i, seg in enumerate(segments):
        if seg == "tag" and i + 1 < len(segments):
            return unquote(segments[i + 1])
    return ""


async def fetch_latest_release_tag_via_github_web(
    repo: str,
    *,
    token: str = "",
    user_agent: str = "Pallas-Bot/1.0",
    client_timeout: httpx.Timeout | None = None,
) -> dict[str, str]:
    """GET ``github.com/{owner}/{repo}/releases/latest`` 并跟随跳转，解析当前最新 tag。"""
    owner_part, _, name_part = (repo or "").strip().partition("/")
    if not owner_part or not name_part:
        msg = f"无效的 GitHub 仓库名: {repo!r}，应为 Owner/Repo"
        raise ValueError(msg)
    page_url = f"https://github.com/{owner_part}/{name_part}/releases/latest"
    eff_timeout = client_timeout or httpx.Timeout(15.0, connect=8.0)
    headers: dict[str, str] = {"User-Agent": user_agent}
    headers.update(github_auth_headers(token))
    async with httpx.AsyncClient(follow_redirects=True, timeout=eff_timeout, headers=headers) as client:
        resp = await client.get(page_url)
        resp.raise_for_status()
    final_url = str(resp.url)
    tag = release_tag_from_github_final_url(final_url)
    if not tag:
        msg = f"无法从 GitHub 网页解析 release tag: {final_url!r}"
        raise ValueError(msg)
    return {"tag": tag, "html_url": final_url}


async def fetch_github_releases(
    repo: str,
    *,
    client: httpx.AsyncClient,
    limit: int = 10,
    token: str = "",
) -> list[dict[str, Any]]:
    """从 GitHub API 获取最近的 release 列表。

    返回 ``[{tag, assets: [{name, url}]}]``，每个 asset 仅保留
    ``name`` 与 ``browser_download_url``，调用方按平台自行过滤。
    """
    owner, _, name = (repo or "").strip().partition("/")
    if not owner or not name:
        return []
    api_url = f"https://api.github.com/repos/{owner}/{name}/releases?per_page={limit}"
    auth_headers = github_auth_headers(token)
    try:
        resp = await client.get(api_url, headers=auth_headers)
    except Exception:  # noqa: BLE001
        return []
    if resp.status_code != 200:
        return []
    data = resp.json()
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for rel in data:
        if not isinstance(rel, dict):
            continue
        tag = str(rel.get("tag_name", "")).strip()
        if not tag:
            continue
        assets = [
            {"name": str(a.get("name", "")), "url": str(a.get("browser_download_url", ""))}
            for a in (rel.get("assets") or [])
            if isinstance(a, dict) and a.get("name") and a.get("browser_download_url")
        ]
        out.append({
            "tag": tag,
            "tag_name": tag,
            "name": str(rel.get("name") or tag).strip(),
            "prerelease": bool(rel.get("prerelease", False)),
            "published_at": str(rel.get("published_at") or ""),
            "assets": assets,
        })
    return out


async def fetch_latest_release(
    repo: str,
    *,
    user_agent: str = "Pallas-Bot/1.0",
    token: str = "",
    preferred_asset_name: str | None = None,
    include_asset_url: bool = True,
) -> dict[str, Any]:
    """获取指定仓库最新 release 的摘要信息。

    返回 ``{tag, html_url, asset_url}``。``asset_url``：

    - ``include_asset_url=False`` 时恒为空（适合仅需对比 tag 的场景）。
    - 否则优先匹配 ``preferred_asset_name``（忽略大小写），否则取第一个 ``.zip`` 资产。
    """
    api_url = github_release_api_url(repo)
    headers: dict[str, str] = {"User-Agent": user_agent}
    headers.update(github_auth_headers(token))
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(15.0, connect=8.0),
        headers=headers,
    ) as client:
        resp = await client.get(api_url)
        resp.raise_for_status()
        data = resp.json()
    tag = str(data.get("tag_name") or "").strip()
    html_url = str(data.get("html_url") or "").strip()
    asset_url = ""
    if include_asset_url:
        assets = data.get("assets") or []
        pref = (preferred_asset_name or "").strip().lower()
        if pref:
            for item in assets:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "")).strip()
                if name.lower() == pref:
                    asset_url = str(item.get("browser_download_url", "") or "").strip()
                    break
        if not asset_url:
            for item in assets:
                if isinstance(item, dict) and str(item.get("name", "")).lower().endswith(".zip"):
                    asset_url = str(item.get("browser_download_url", "") or "").strip()
                    break
    return {"tag": tag, "html_url": html_url, "asset_url": asset_url}
