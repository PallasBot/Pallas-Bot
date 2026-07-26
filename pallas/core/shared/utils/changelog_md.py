"""Keep a Changelog 文本截取与仓库 CHANGELOG.md 拉取。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import httpx

from pallas.core.shared.utils.git_mirror import iter_mirrors_for_failover, request_with_mirrors

if TYPE_CHECKING:
    from pathlib import Path

_VERSION_HEADING_RE = re.compile(r"^##\s+(\[[^\]]+\].*)$", re.MULTILINE)
_DEFAULT_MAX_VERSIONS = 10
_DEFAULT_NOTES_MAX = 12000
_HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_CHANGELOG_FILENAMES = ("CHANGELOG.md", "docs/CHANGELOG.md", "CHANGELOG.MD", "changelog.md")

WEBUI_CHANGELOG_REPO = "PallasBot/Pallas-Bot-WebUI"
BOT_CHANGELOG_REPO = "PallasBot/Pallas-Bot"
WEBUI_CHANGELOG_BLOB = "https://github.com/PallasBot/Pallas-Bot-WebUI/blob/main/CHANGELOG.md"
BOT_CHANGELOG_BLOB = "https://github.com/PallasBot/Pallas-Bot/blob/main/CHANGELOG.md"


def github_changelog_raw_urls(repo: str) -> list[str]:
    owner_repo = str(repo or "").strip().strip("/")
    if "/" not in owner_repo:
        return []
    owner, name = owner_repo.split("/", 1)
    urls: list[str] = []
    for branch in ("main", "master"):
        for filename in _CHANGELOG_FILENAMES:
            urls.extend((
                f"https://raw.githubusercontent.com/{owner}/{name}/refs/heads/{branch}/{filename}",
                f"https://raw.githubusercontent.com/{owner}/{name}/{branch}/{filename}",
            ))
    return urls


def slice_keep_a_changelog(
    markdown: str,
    *,
    max_versions: int = _DEFAULT_MAX_VERSIONS,
    notes_max: int = _DEFAULT_NOTES_MAX,
    changelog_url: str = "",
) -> str:
    """截取 Keep a Changelog 最近若干版本段（文件通常新→旧）。"""
    text = (markdown or "").replace("\r\n", "\n").strip()
    if not text:
        return ""

    matches = list(_VERSION_HEADING_RE.finditer(text))
    limit = max(1, int(max_versions))
    if not matches:
        cut = text if len(text) <= notes_max else f"{text[:notes_max].rstrip()}\n\n…（已截断）"
        return cut

    preamble = text[: matches[0].start()].rstrip()
    selected = matches[:limit]
    truncated = len(matches) > len(selected)
    end = matches[len(selected)].start() if truncated else len(text)
    body = text[selected[0].start() : end].rstrip()
    out = f"{preamble}\n\n{body}".strip() if preamble else body

    if truncated:
        more = f"[CHANGELOG.md]({changelog_url})" if changelog_url else "CHANGELOG.md"
        out = f"{out}\n\n…（仅展示最近 {len(selected)} 个版本，完整历史见 {more}）"

    if len(out) <= notes_max:
        return out
    more = f"[CHANGELOG.md]({changelog_url})" if changelog_url else "CHANGELOG.md"
    return f"{out[:notes_max].rstrip()}\n\n…（已截断，完整内容见 {more}）"


async def download_changelog_markdown(repo: str) -> str:
    urls = github_changelog_raw_urls(repo)
    if not urls:
        raise ValueError("invalid changelog repo")
    mirrors = list(iter_mirrors_for_failover("community"))
    last_exc: Exception | None = None
    for url in urls:
        try:

            async def getter(rewritten_url: str) -> str:
                async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
                    resp = await client.get(rewritten_url)
                    resp.raise_for_status()
                    return resp.text

            return await request_with_mirrors(url, mirrors, getter)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            continue
    if last_exc is not None:
        raise last_exc
    raise ValueError("changelog not found")


def read_local_changelog(path: Path) -> str | None:
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8")
    except OSError:
        return None
    return None


async def load_update_changelog_payload(
    target: str,
    *,
    max_versions: int = _DEFAULT_MAX_VERSIONS,
) -> dict[str, Any]:
    """返回 WebUI / Bot 的 CHANGELOG 截取结果。"""
    kind = str(target or "").strip().lower()
    if kind in {"web", "webui"}:
        kind = "webui"
    elif kind in {"bot", "pallas-bot"}:
        kind = "bot"
    else:
        raise ValueError("target must be webui or bot")

    if kind == "webui":
        repo = WEBUI_CHANGELOG_REPO
        blob_url = WEBUI_CHANGELOG_BLOB
        source = "github"
        raw = await download_changelog_markdown(repo)
    else:
        from pallas.core.foundation.paths import PROJECT_ROOT

        blob_url = BOT_CHANGELOG_BLOB
        local = read_local_changelog(PROJECT_ROOT / "CHANGELOG.md")
        if local is not None and local.strip():
            raw = local
            source = "local"
            repo = BOT_CHANGELOG_REPO
        else:
            repo = BOT_CHANGELOG_REPO
            raw = await download_changelog_markdown(repo)
            source = "github"

    markdown = slice_keep_a_changelog(
        raw,
        max_versions=max_versions,
        changelog_url=blob_url,
    )
    return {
        "target": kind,
        "repo": repo,
        "source": source,
        "changelog_url": blob_url,
        "markdown": markdown,
        "max_versions": max(1, int(max_versions)),
    }
