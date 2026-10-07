from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest


def _index(minimum="4.4.4", plugin_id="demo"):
    return {
        "plugins": [
            {
                "plugin_id": plugin_id,
                "repository_url": "https://github.com/example/demo.git",
                "ref": "main",
                "min_pallas_version": minimum,
            },
        ],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("minimum", ["4.4.3", "4.4.4"])
async def test_minimum_version_at_or_below_current_is_allowed(monkeypatch, minimum):
    import pallas
    from pallas.console.webui import community_plugin_install as cpi

    monkeypatch.setattr(pallas, "__version__", "4.4.4")
    monkeypatch.setattr(cpi, "load_community_plugin_index_safe", AsyncMock(return_value=_index(minimum)))

    assert await cpi.ensure_community_plugin_compatible("demo") is None


@pytest.mark.asyncio
async def test_higher_and_rc_minimum_versions_are_compared_semantically(monkeypatch):
    import pallas
    from pallas.console.webui import community_plugin_install as cpi

    loader = AsyncMock(return_value=_index("4.5.0rc1"))
    monkeypatch.setattr(cpi, "load_community_plugin_index_safe", loader)
    monkeypatch.setattr(pallas, "__version__", "4.4.9")
    with pytest.raises(cpi.CommunityPluginInstallError, match="需要 Pallas-Bot >= 4.5.0rc1"):
        await cpi.ensure_community_plugin_compatible("demo")

    loader.return_value = _index("4.5.0")
    monkeypatch.setattr(pallas, "__version__", "4.5.0rc1")
    with pytest.raises(cpi.CommunityPluginInstallError):
        await cpi.ensure_community_plugin_compatible("demo")

    loader.return_value = _index("4.5.0rc1")
    assert await cpi.ensure_community_plugin_compatible("demo") is None


@pytest.mark.asyncio
async def test_v_prefix_and_local_versions_use_packaging_semantics(monkeypatch):
    import pallas
    from pallas.console.webui import community_plugin_install as cpi

    loader = AsyncMock(return_value=_index("v4.4.4"))
    monkeypatch.setattr(cpi, "load_community_plugin_index_safe", loader)
    monkeypatch.setattr(pallas, "__version__", "4.4.4+local.1")
    assert await cpi.ensure_community_plugin_compatible("demo") is None

    loader.return_value = _index("4.4.4+local.2")
    with pytest.raises(cpi.CommunityPluginInstallError):
        await cpi.ensure_community_plugin_compatible("demo")


@pytest.mark.asyncio
async def test_invalid_versions_reject_but_unknown_compatibility_warns(monkeypatch):
    import pallas
    from pallas.console.webui import community_plugin_install as cpi

    loader = AsyncMock(return_value=_index("latest"))
    monkeypatch.setattr(cpi, "load_community_plugin_index_safe", loader)
    with pytest.raises(cpi.CommunityPluginInstallError, match="最低版本声明无效"):
        await cpi.ensure_community_plugin_compatible("demo")

    loader.return_value = _index("4.0.0")
    monkeypatch.setattr(pallas, "__version__", "dev-build")
    with pytest.raises(cpi.CommunityPluginInstallError, match="当前 Pallas-Bot 版本无效"):
        await cpi.ensure_community_plugin_compatible("demo")

    monkeypatch.setattr(pallas, "__version__", "4.4.4")
    for minimum in (None, " "):
        loader.return_value = _index(minimum)
        assert "兼容性未验证" in (await cpi.ensure_community_plugin_compatible("demo") or "")
    loader.return_value = {"plugins": [], "error": "offline"}
    assert "索引加载失败" in (await cpi.ensure_community_plugin_compatible("demo") or "")
    loader.return_value = _index("4.0.0", plugin_id="other")
    assert "索引中未找到" in (await cpi.ensure_community_plugin_compatible("demo") or "")
    loader.side_effect = RuntimeError("offline")
    assert "索引加载失败" in (await cpi.ensure_community_plugin_compatible("demo") or "")


@pytest.mark.asyncio
async def test_install_rejection_precedes_parent_creation_and_custom_ref_cannot_bypass(monkeypatch, tmp_path):
    import pallas
    from pallas.console.webui import community_plugin_install as cpi

    monkeypatch.setattr(pallas, "__version__", "4.4.4")
    monkeypatch.setattr(cpi, "PROJECT_ROOT", tmp_path)
    loader = AsyncMock(return_value=_index("9.0.0"))
    monkeypatch.setattr(cpi, "load_community_plugin_index_safe", loader)
    git = AsyncMock(side_effect=AssertionError("git must not run"))
    deps = AsyncMock(side_effect=AssertionError("dependency install must not run"))
    rmtree = Mock(side_effect=AssertionError("delete must not run"))
    metadata = Mock(side_effect=AssertionError("metadata must not be written"))
    monkeypatch.setattr(cpi, "run_git_command", git)
    monkeypatch.setattr(cpi, "install_missing_dependencies", deps)
    monkeypatch.setattr(cpi.shutil, "rmtree", rmtree)
    monkeypatch.setattr(cpi, "_write_install_meta", metadata)

    with pytest.raises(cpi.CommunityPluginInstallError, match="需要 Pallas-Bot >= 9.0.0"):
        await cpi.install_community_plugin(
            "demo",
            repository_url="https://gitlab.com/other/custom.git",
            ref="custom-ref",
        )

    assert not (tmp_path / cpi.COMMUNITY_PLUGINS_DIR).exists()
    loader.assert_awaited_once()
    git.assert_not_awaited()
    deps.assert_not_awaited()
    rmtree.assert_not_called()
    metadata.assert_not_called()


@pytest.mark.asyncio
async def test_update_rejection_precedes_all_mutating_operations(monkeypatch, tmp_path):
    import pallas
    from pallas.console.webui import community_plugin_install as cpi

    monkeypatch.setattr(pallas, "__version__", "4.4.4")
    monkeypatch.setattr(cpi, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(cpi, "load_community_plugin_index_safe", AsyncMock(return_value=_index("9.0.0")))
    dest = tmp_path / cpi.COMMUNITY_PLUGINS_DIR / "demo"
    dest.mkdir(parents=True)
    sentinel = dest / "sentinel"
    sentinel.write_text("keep", encoding="utf-8")
    (dest / "__init__.py").write_text("# demo\n", encoding="utf-8")
    git = AsyncMock(side_effect=AssertionError("git must not run"))
    deps = AsyncMock(side_effect=AssertionError("dependency install must not run"))
    rmtree = Mock(side_effect=AssertionError("delete must not run"))
    metadata = Mock(side_effect=AssertionError("metadata must not be written"))
    monkeypatch.setattr(cpi, "run_git_command", git)
    monkeypatch.setattr(cpi, "install_missing_dependencies", deps)
    monkeypatch.setattr(cpi.shutil, "rmtree", rmtree)
    monkeypatch.setattr(cpi, "_write_install_meta", metadata)

    with pytest.raises(cpi.CommunityPluginInstallError, match="需要 Pallas-Bot >= 9.0.0"):
        await cpi.update_community_plugin("demo", ref="custom-ref")

    assert sentinel.read_text(encoding="utf-8") == "keep"
    git.assert_not_awaited()
    deps.assert_not_awaited()
    rmtree.assert_not_called()
    metadata.assert_not_called()


@pytest.mark.asyncio
async def test_cli_and_sync_api_propagate_compatibility_rejection(monkeypatch, tmp_path):
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient

    from packages.pb_webui import plugins_console_api
    from packages.pb_webui.config import Config
    from pallas.console.cli.commands import community_plugin_cmd
    from pallas.console.webui import community_plugin_install as cpi

    monkeypatch.setattr(
        community_plugin_cmd,
        "resolve_community_plugin_target",
        AsyncMock(return_value=("demo", "https://github.com/example/demo.git", "main")),
    )
    monkeypatch.setattr(cpi, "load_community_plugin_index_safe", AsyncMock(return_value=_index("9.0.0")))
    monkeypatch.setattr(plugins_console_api, "check_pallas_write_token", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        plugins_console_api,
        "_resolve_community_plugin_target",
        AsyncMock(
            return_value=(
                "demo",
                "https://github.com/example/demo.git",
                "main",
            )
        ),
    )
    monkeypatch.setattr(cpi, "PROJECT_ROOT", tmp_path)
    code = await community_plugin_cmd.run_install_async(
        "demo",
        repository_url="https://github.com/example/demo.git",
        ref="main",
        restart=False,
    )
    assert code == 1

    app = FastAPI()
    router = APIRouter()
    plugins_console_api.register_plugins_console_router(router, x="/api", plugin_config=Config())
    app.include_router(router)
    with TestClient(app) as client:
        response = client.post("/api/plugins/community-plugins/install", json={"plugin_id": "demo"})
    assert response.status_code == 400
    assert "需要 Pallas-Bot" in response.json()["detail"]


@pytest.mark.asyncio
async def test_real_store_job_runner_marks_rejection_failed_without_activation(monkeypatch, tmp_path):
    from pallas.console.cli import community_plugin_activation as activation
    from pallas.console.cli import community_plugin_ops
    from pallas.console.webui import community_plugin_install as cpi
    from pallas.console.webui.plugin_store_job_progress import PluginStoreJob, run_plugin_store_job

    monkeypatch.setattr(cpi, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(cpi, "load_community_plugin_index_safe", AsyncMock(return_value=_index("9.0.0")))
    monkeypatch.setattr(activation, "hot_load_extra_dir_plugin", lambda *_: pytest.fail("activation ran"))
    monkeypatch.setattr(activation, "schedule_bot_restart", lambda **_kwargs: pytest.fail("restart ran"))
    job = PluginStoreJob("job", "community", "demo", "install")

    async def runner(_job):
        await community_plugin_ops.install_community_plugin_with_options(
            "demo",
            repository_url="https://github.com/example/demo.git",
            restart=True,
        )

    await run_plugin_store_job(job, runner)

    assert job.phase == "failed"
    assert "需要 Pallas-Bot" in job.error
    assert not (tmp_path / cpi.COMMUNITY_PLUGINS_DIR).exists()


@pytest.mark.asyncio
async def test_automatic_update_records_incompatibility_as_failed(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from packages.pb_webui import webui_auto_update as auto
    from pallas.console.webui import community_plugin_install as cpi

    monkeypatch.setattr(cpi, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(cpi, "load_community_plugin_index_safe", AsyncMock(return_value=_index("9.0.0")))
    monkeypatch.setattr(auto, "auto_update_state_path", lambda: tmp_path / "auto-update.json")
    monkeypatch.setattr(
        "pallas.console.webui.plugin_update_snapshot.refresh_plugin_update_snapshot",
        AsyncMock(return_value={"official": {}, "community": {"demo": {"has_update": True}}}),
    )
    dest = tmp_path / cpi.COMMUNITY_PLUGINS_DIR / "demo"
    dest.mkdir(parents=True)
    (dest / "__init__.py").write_text("# demo\n", encoding="utf-8")
    git = AsyncMock(side_effect=AssertionError("git must not run"))
    monkeypatch.setattr(cpi, "run_git_command", git)
    restart = Mock(side_effect=AssertionError("restart must not run"))
    monkeypatch.setattr("pallas.console.cli.bot_process.schedule_bot_restart", restart)

    result = await auto._run_plugins_target(
        config=SimpleNamespace(pallas_plugins_auto_update_enabled=True),
        force=True,
    )

    assert result["result"] == "failed"
    assert result["failed"][0]["id"] == "demo"
    assert "需要 Pallas-Bot" in result["error"]
    git.assert_not_awaited()
    restart.assert_not_called()
