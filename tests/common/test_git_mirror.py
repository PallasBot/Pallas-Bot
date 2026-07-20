import pytest

from pallas.core.shared.utils.git_mirror import (
    BUILTIN_MIRRORS,
    MirrorSpec,
    rewrite_github_url,
    validate_custom_proxy_prefix,
)


def test_rewrite_github_clone_with_proxy_prefix():
    m = MirrorSpec(
        id="ghproxy-vip",
        label="ghproxy.vip",
        type="proxy",
        clone_prefix="https://ghproxy.vip/https://github.com",
        raw_prefix="https://ghproxy.vip/https://raw.githubusercontent.com",
        api_prefix="https://ghproxy.vip/https://api.github.com",
    )
    assert (
        rewrite_github_url("https://github.com/PallasBot/Pallas-Bot.git", m)
        == "https://ghproxy.vip/https://github.com/PallasBot/Pallas-Bot.git"
    )


def test_rewrite_raw_and_api():
    m = MirrorSpec(
        id="ghproxy-vip",
        label="x",
        type="proxy",
        clone_prefix="https://ghproxy.vip/https://github.com",
        raw_prefix="https://ghproxy.vip/https://raw.githubusercontent.com",
        api_prefix="https://ghproxy.vip/https://api.github.com",
    )
    assert rewrite_github_url("https://raw.githubusercontent.com/a/b/main/README.md", m).startswith(
        "https://ghproxy.vip/https://raw.githubusercontent.com/"
    )
    assert rewrite_github_url("https://api.github.com/repos/a/b/releases/latest", m).startswith(
        "https://ghproxy.vip/https://api.github.com/"
    )


def test_github_mirror_is_noop():
    m = next(x for x in BUILTIN_MIRRORS if x.id == "github")
    u = "https://github.com/a/b"
    assert rewrite_github_url(u, m) == u


def test_reject_private_custom_prefix():
    import pytest

    with pytest.raises(ValueError, match="私网"):
        validate_custom_proxy_prefix("https://127.0.0.1/")
    with pytest.raises(ValueError, match="https"):
        validate_custom_proxy_prefix("http://example.com/")  # 仅允许 https


def test_failover_order_preferred_then_others_then_github(monkeypatch, tmp_path):
    from pallas.core.shared.utils import git_mirror as gm

    monkeypatch.setattr(gm, "repo_webui_settings_path", lambda: tmp_path / "webui.json")
    (tmp_path / "webui.json").write_text(
        '{"env":{},"git_mirror":{"preferred_id":"ghproxy-vip","custom_proxy_prefix":""}}\n',
        encoding="utf-8",
    )
    ids = [m.id for m in gm.iter_mirrors_for_failover()]
    assert ids[0] == "ghproxy-vip"
    assert ids[-1] == "github"
    assert len(ids) == len(set(ids))


def test_save_and_load_preferred(monkeypatch, tmp_path):
    from pallas.core.shared.utils import git_mirror as gm

    monkeypatch.setattr(gm, "repo_webui_settings_path", lambda: tmp_path / "webui.json")
    (tmp_path / "webui.json").write_text('{"env":{}}\n', encoding="utf-8")
    gm.save_git_mirror_config(preferred_id="github", custom_proxy_prefix="")
    cfg = gm.load_git_mirror_config()
    assert cfg["preferred_id"] == "github"


def test_missing_webui_json_defaults_to_github(monkeypatch, tmp_path):
    from pallas.core.shared.utils import git_mirror as gm

    monkeypatch.setattr(gm, "repo_webui_settings_path", lambda: tmp_path / "webui.json")
    cfg = gm.load_git_mirror_config()
    assert cfg["preferred_id"] == "github"
    assert cfg["custom_proxy_prefix"] == ""
    assert gm.resolve_preferred_mirror().id == "github"


def test_corrupt_webui_json_defaults_to_github(monkeypatch, tmp_path):
    from pallas.core.shared.utils import git_mirror as gm

    path = tmp_path / "webui.json"
    monkeypatch.setattr(gm, "repo_webui_settings_path", lambda: path)
    path.write_text("{not json", encoding="utf-8")
    cfg = gm.load_git_mirror_config()
    assert cfg["preferred_id"] == "github"
    assert gm.resolve_preferred_mirror().id == "github"


def test_unknown_preferred_id_falls_back_to_github(monkeypatch, tmp_path):
    from pallas.core.shared.utils import git_mirror as gm

    monkeypatch.setattr(gm, "repo_webui_settings_path", lambda: tmp_path / "webui.json")
    (tmp_path / "webui.json").write_text(
        '{"env":{},"git_mirror":{"preferred_id":"unknown-mirror","custom_proxy_prefix":""}}\n',
        encoding="utf-8",
    )
    assert gm.resolve_preferred_mirror().id == "github"


def test_custom_empty_prefix_falls_back_to_github(monkeypatch, tmp_path):
    from pallas.core.shared.utils import git_mirror as gm

    monkeypatch.setattr(gm, "repo_webui_settings_path", lambda: tmp_path / "webui.json")
    (tmp_path / "webui.json").write_text(
        '{"env":{},"git_mirror":{"preferred_id":"custom","custom_proxy_prefix":""}}\n',
        encoding="utf-8",
    )
    assert gm.resolve_preferred_mirror().id == "github"


def test_custom_invalid_prefix_falls_back_to_github_failover(monkeypatch, tmp_path):
    from pallas.core.shared.utils import git_mirror as gm

    monkeypatch.setattr(gm, "repo_webui_settings_path", lambda: tmp_path / "webui.json")
    (tmp_path / "webui.json").write_text(
        '{"env":{},"git_mirror":{"preferred_id":"custom","custom_proxy_prefix":"https://127.0.0.1/"}}\n',
        encoding="utf-8",
    )
    assert gm.resolve_preferred_mirror().id == "github"
    ids = [m.id for m in gm.iter_mirrors_for_failover()]
    assert ids[0] == "github"
    assert len(ids) >= 2


def test_github_preferred_failover_order(monkeypatch, tmp_path):
    from pallas.core.shared.utils import git_mirror as gm

    monkeypatch.setattr(gm, "repo_webui_settings_path", lambda: tmp_path / "webui.json")
    (tmp_path / "webui.json").write_text(
        '{"env":{},"git_mirror":{"preferred_id":"github","custom_proxy_prefix":""}}\n',
        encoding="utf-8",
    )
    ids = [m.id for m in gm.iter_mirrors_for_failover()]
    assert ids[0] == "github"
    assert "ghproxy-vip" in ids
    assert "ghproxy-net" in ids
    assert len(ids) == len(set(ids))


def test_scope_override_failover(monkeypatch, tmp_path):
    from pallas.core.shared.utils import git_mirror as gm

    monkeypatch.setattr(gm, "repo_webui_settings_path", lambda: tmp_path / "webui.json")
    (tmp_path / "webui.json").write_text(
        '{"env":{},"git_mirror":{"preferred_id":"github","custom_proxy_prefix":"",'
        '"scopes":{"webui":"ghproxy-net","bot":"","community":""}}}\n',
        encoding="utf-8",
    )
    assert gm.resolve_mirror_for_scope("webui").id == "ghproxy-net"
    assert gm.resolve_mirror_for_scope("bot").id == "github"
    ids = [m.id for m in gm.iter_mirrors_for_failover("webui")]
    assert ids[0] == "ghproxy-net"


def test_git_instead_of_args_github_is_empty():
    from pallas.core.shared.utils.git_mirror import BUILTIN_MIRRORS, git_instead_of_args

    github = next(m for m in BUILTIN_MIRRORS if m.id == "github")
    assert git_instead_of_args(github) == []


def test_git_instead_of_args_proxy_mirror():
    from pallas.core.shared.utils.git_mirror import BUILTIN_MIRRORS, git_instead_of_args

    proxy = next(m for m in BUILTIN_MIRRORS if m.id == "ghproxy-vip")
    assert git_instead_of_args(proxy) == [
        "-c",
        "url.https://ghproxy.vip/https://github.com/.insteadOf=https://github.com/",
    ]


def test_save_preserves_unrelated_top_level_keys(monkeypatch, tmp_path):
    from pallas.core.shared.utils import git_mirror as gm

    path = tmp_path / "webui.json"
    monkeypatch.setattr(gm, "repo_webui_settings_path", lambda: path)
    path.write_text('{"env":{},"other_section":{"keep":true}}\n', encoding="utf-8")
    gm.save_git_mirror_config(preferred_id="github", custom_proxy_prefix="")
    data = __import__("json").loads(path.read_text(encoding="utf-8"))
    assert data["other_section"] == {"keep": True}
    assert data["git_mirror"]["preferred_id"] == "github"


def test_custom_mirror_rewrite_and_failover(monkeypatch, tmp_path):
    from pallas.core.shared.utils import git_mirror as gm

    prefix = "https://ghproxy.example/"
    monkeypatch.setattr(gm, "repo_webui_settings_path", lambda: tmp_path / "webui.json")
    (tmp_path / "webui.json").write_text('{"env":{}}\n', encoding="utf-8")
    gm.save_git_mirror_config(preferred_id="custom", custom_proxy_prefix=prefix)

    preferred = gm.resolve_preferred_mirror()
    assert preferred.id == "custom"
    assert preferred.clone_prefix == "https://ghproxy.example/https://github.com"
    assert preferred.raw_prefix == "https://ghproxy.example/https://raw.githubusercontent.com"
    assert preferred.api_prefix == "https://ghproxy.example/https://api.github.com"

    ids = [m.id for m in gm.iter_mirrors_for_failover()]
    assert ids[0] == "custom"
    assert "github" in ids
    assert len(ids) == len(set(ids))

    clone_url = "https://github.com/PallasBot/Pallas-Bot.git"
    assert (
        gm.rewrite_github_url(clone_url, preferred)
        == "https://ghproxy.example/https://github.com/PallasBot/Pallas-Bot.git"
    )


@pytest.mark.asyncio
async def test_request_failover_skips_failing_mirror():
    from pallas.core.shared.utils import git_mirror as gm

    calls: list[str] = []

    async def fake_get(url: str) -> str:
        calls.append(url)
        if "ghproxy.vip" in url:
            raise RuntimeError("down")
        return "ok"

    mirrors = [
        gm.MirrorSpec(
            id="ghproxy-vip",
            label="a",
            type="proxy",
            clone_prefix="https://ghproxy.vip/https://github.com",
            raw_prefix="https://ghproxy.vip/https://raw.githubusercontent.com",
            api_prefix="https://ghproxy.vip/https://api.github.com",
        ),
        next(m for m in gm.BUILTIN_MIRRORS if m.id == "github"),
    ]
    out = await gm.request_with_mirrors(
        "https://api.github.com/repos/a/b/releases/latest",
        mirrors,
        fake_get,
    )
    assert out == "ok"
    assert any("ghproxy.vip" in c for c in calls)
    assert any(c.startswith("https://api.github.com/") for c in calls)


@pytest.mark.asyncio
async def test_request_failover_reraises_last_exception():
    from pallas.core.shared.utils import git_mirror as gm

    async def always_fail(url: str) -> str:
        raise RuntimeError(f"fail:{url}")

    mirrors = [
        next(m for m in gm.BUILTIN_MIRRORS if m.id == "ghproxy-vip"),
        next(m for m in gm.BUILTIN_MIRRORS if m.id == "github"),
    ]
    with pytest.raises(RuntimeError, match="fail:https://api.github.com/"):
        await gm.request_with_mirrors(
            "https://api.github.com/repos/a/b/releases/latest",
            mirrors,
            always_fail,
        )
