import httpx
import pytest


@pytest.mark.asyncio
async def test_fetch_latest_release_tries_proxy_before_github(monkeypatch):
    from pallas.core.shared.utils import git_mirror as gm
    from pallas.core.shared.utils import github_release as gr

    ghproxy_mirror = next(m for m in gm.BUILTIN_MIRRORS if m.id == "ghproxy-vip")
    github_mirror = next(m for m in gm.BUILTIN_MIRRORS if m.id == "github")

    def fake_iter_mirrors(*_args):
        yield ghproxy_mirror
        yield github_mirror

    monkeypatch.setattr(gr, "iter_mirrors_for_failover", fake_iter_mirrors)

    calls: list[str] = []

    async def fake_get(self, url: str, **kwargs):
        calls.append(url)
        if "ghproxy.vip" in url:
            raise httpx.ConnectError("down", request=httpx.Request("GET", url))
        return httpx.Response(
            200,
            json={
                "tag_name": "v1.0.0",
                "html_url": "https://github.com/a/b/releases/tag/v1.0.0",
                "body": "notes",
                "assets": [],
            },
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    result = await gr.fetch_latest_release("a/b")
    assert result["tag"] == "v1.0.0"
    assert result["body"] == "notes"
    assert any("ghproxy.vip" in u for u in calls)
    assert any(u.startswith("https://api.github.com/") for u in calls)


@pytest.mark.asyncio
async def test_fetch_github_releases_failover_proxy_then_github(monkeypatch):
    from pallas.core.shared.utils import git_mirror as gm
    from pallas.core.shared.utils import github_release as gr

    ghproxy_mirror = next(m for m in gm.BUILTIN_MIRRORS if m.id == "ghproxy-vip")
    github_mirror = next(m for m in gm.BUILTIN_MIRRORS if m.id == "github")

    def fake_iter_mirrors(*_args):
        yield ghproxy_mirror
        yield github_mirror

    monkeypatch.setattr(gr, "iter_mirrors_for_failover", fake_iter_mirrors)

    calls: list[str] = []

    async def fake_get(self, url: str, **kwargs):
        calls.append(url)
        if "ghproxy.vip" in url:
            raise httpx.ConnectError("down", request=httpx.Request("GET", url))
        return httpx.Response(
            200,
            json=[
                {
                    "tag_name": "v2.0.0",
                    "name": "v2.0.0",
                    "prerelease": False,
                    "published_at": "2026-01-01T00:00:00Z",
                    "assets": [
                        {
                            "name": "app.zip",
                            "browser_download_url": "https://github.com/a/b/releases/download/v2.0.0/app.zip",
                        }
                    ],
                }
            ],
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    async with httpx.AsyncClient() as client:
        result = await gr.fetch_github_releases("a/b", client=client)

    assert len(result) == 1
    assert result[0]["tag"] == "v2.0.0"
    assert result[0]["assets"][0]["name"] == "app.zip"
    assert any("ghproxy.vip" in u for u in calls)
    assert any(u.startswith("https://api.github.com/") for u in calls)


@pytest.mark.asyncio
async def test_fetch_github_releases_all_mirrors_fail_returns_empty(monkeypatch):
    from pallas.core.shared.utils import git_mirror as gm
    from pallas.core.shared.utils import github_release as gr

    ghproxy_mirror = next(m for m in gm.BUILTIN_MIRRORS if m.id == "ghproxy-vip")
    github_mirror = next(m for m in gm.BUILTIN_MIRRORS if m.id == "github")

    def fake_iter_mirrors(*_args):
        yield ghproxy_mirror
        yield github_mirror

    monkeypatch.setattr(gr, "iter_mirrors_for_failover", fake_iter_mirrors)

    async def fake_get(self, url: str, **kwargs):
        raise httpx.ConnectError("down", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    async with httpx.AsyncClient() as client:
        result = await gr.fetch_github_releases("a/b", client=client)

    assert result == []


@pytest.mark.asyncio
async def test_fetch_latest_release_tag_via_github_web_failover(monkeypatch):
    from pallas.core.shared.utils import git_mirror as gm
    from pallas.core.shared.utils import github_release as gr

    ghproxy_mirror = next(m for m in gm.BUILTIN_MIRRORS if m.id == "ghproxy-vip")
    github_mirror = next(m for m in gm.BUILTIN_MIRRORS if m.id == "github")

    def fake_iter_mirrors(*_args):
        yield ghproxy_mirror
        yield github_mirror

    monkeypatch.setattr(gr, "iter_mirrors_for_failover", fake_iter_mirrors)

    final_url = "https://github.com/a/b/releases/tag/v3.1.0"
    calls: list[str] = []

    async def fake_get(self, url: str, **kwargs):
        calls.append(url)
        if "ghproxy.vip" in url:
            raise httpx.ConnectError("down", request=httpx.Request("GET", url))
        return httpx.Response(
            200,
            request=httpx.Request("GET", final_url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    result = await gr.fetch_latest_release_tag_via_github_web("a/b")
    assert result == {"tag": "v3.1.0", "html_url": final_url}
    assert any("ghproxy.vip" in u for u in calls)
    assert any(u.startswith("https://github.com/a/b/releases/latest") for u in calls)
