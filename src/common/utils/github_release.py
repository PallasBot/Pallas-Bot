"""GitHub Release 工具函数。

提供：
- :func:`github_release_api_url` — 构造 GitHub Releases API URL
- :func:`fetch_github_releases` — 获取 release 列表（含 assets）
- :func:`fetch_latest_release` — 获取最新单条 release 摘要
"""

from __future__ import annotations

from typing import Any

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


def _github_auth_headers(token: str = "") -> dict[str, str]:
    """构造 GitHub API 鉴权头；token 为空时返回空字典。"""
    t = (token or "").strip()
    if not t:
        return {}
    return {"Authorization": f"Bearer {t}"}


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
    auth_headers = _github_auth_headers(token)
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
) -> dict[str, Any]:
    """获取指定仓库最新 release 的摘要信息。

    返回 ``{tag, html_url, asset_url}``，其中 ``asset_url`` 为第一个
    ``.zip`` 资产的下载地址（不存在时为空字符串）。
    """
    api_url = github_release_api_url(repo)
    headers: dict[str, str] = {"User-Agent": user_agent}
    headers.update(_github_auth_headers(token))
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
    assets = data.get("assets") or []
    asset_url = ""
    for item in assets:
        if isinstance(item, dict) and str(item.get("name", "")).lower().endswith(".zip"):
            asset_url = str(item.get("browser_download_url", "")).strip()
            break
    return {"tag": tag, "html_url": html_url, "asset_url": asset_url}
