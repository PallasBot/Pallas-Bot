"""WebUI 自动更新：开关跳过、忙时跳过、成功写 notice、ack 清除。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from packages.pb_webui import webui_auto_update as auto
from pallas.console.webui.update_apply_progress import (
    clear_update_apply_jobs_for_tests,
    create_update_apply_job,
)


@pytest.fixture
def state_dir(tmp_path, monkeypatch: pytest.MonkeyPatch):
    clear_update_apply_jobs_for_tests()
    monkeypatch.setattr(auto, "auto_update_state_path", lambda: tmp_path / "auto_update_state.json")
    monkeypatch.setattr(
        "pallas.core.platform.bot_runtime.roles.is_sharded_worker",
        lambda: False,
    )
    return tmp_path


def _cfg(**overrides: object) -> MagicMock:
    cfg = MagicMock()
    cfg.pallas_webui_auto_update_enabled = False
    cfg.pallas_bot_auto_update_enabled = False
    cfg.pallas_bot_update_track = "release"
    cfg.pallas_bot_update_branch = ""
    cfg.pallas_plugins_auto_update_enabled = False
    cfg.pallas_auto_update_notify_superusers = False
    cfg.pallas_auto_update_notify_bot_id = 0
    cfg.pallas_webui_auto_update_schedule_mode = "interval"
    cfg.pallas_webui_auto_update_interval_hours = 6
    cfg.pallas_webui_auto_update_cron_hour = 4
    cfg.pallas_webui_auto_update_cron_minute = 0
    cfg.pallas_webui_dist_zip_repo = "PallasBot/Pallas-Bot"
    cfg.pallas_webui_dist_zip_asset = "dist.zip"
    cfg.pallas_webui_dist_zip_tag = ""
    cfg.pallas_protocol_github_token = ""
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


@pytest.mark.asyncio
async def test_tick_skipped_when_disabled(state_dir) -> None:
    result = await auto.run_webui_auto_update_tick(
        config=_cfg(pallas_webui_auto_update_enabled=False),
        force=False,
    )
    assert result["result"] == "skipped"
    assert result["reason"] == "disabled"
    state = auto.load_auto_update_state()
    assert state["last_check_result"] == "skipped"


@pytest.mark.asyncio
async def test_tick_skipped_when_update_job_busy(state_dir) -> None:
    job = await create_update_apply_job("webui")
    job.push("running", "busy", progress_percent=10)
    with patch.object(auto, "get_pallas_webui_config", return_value=_cfg(pallas_webui_auto_update_enabled=True)):
        result = await auto.run_webui_auto_update_tick(
            config=_cfg(pallas_webui_auto_update_enabled=True),
            force=True,
        )
    assert result["result"] == "skipped"
    assert result["reason"] == "busy"


@pytest.mark.asyncio
async def test_tick_up_to_date(state_dir) -> None:
    check = {
        "current_tag": "v1.0.0",
        "latest_tag": "v1.0.0",
        "has_update": False,
        "error": None,
    }
    with (
        patch.object(auto, "_load_webui_check", AsyncMock(return_value=check)),
        patch.object(auto, "apply_webui_dist_update", AsyncMock()) as apply_mock,
    ):
        result = await auto.run_webui_auto_update_tick(
            config=_cfg(pallas_webui_auto_update_enabled=True),
            force=True,
        )
    assert result["result"] == "up_to_date"
    apply_mock.assert_not_awaited()
    state = auto.load_auto_update_state()
    assert state["pending_notice"] is None
    assert state["last_check_result"] == "up_to_date"


@pytest.mark.asyncio
async def test_tick_applied_sets_pending_notice(state_dir) -> None:
    check = {
        "current_tag": "v1.0.0",
        "latest_tag": "v1.1.0",
        "has_update": True,
        "error": None,
    }
    apply = AsyncMock(return_value={"tag": "v1.1.0", "message": "ok"})
    with (
        patch.object(auto, "_load_webui_check", AsyncMock(return_value=check)),
        patch.object(auto, "apply_webui_dist_update", apply),
    ):
        result = await auto.run_webui_auto_update_tick(
            config=_cfg(pallas_webui_auto_update_enabled=True),
            force=True,
        )
    assert result["result"] == "applied"
    assert result["tag"] == "v1.1.0"
    state = auto.load_auto_update_state()
    assert state["targets"]["webui"]["last_check_result"] == "applied"
    assert state["targets"]["webui"]["last_applied_tag"] == "v1.1.0"
    notice = state["pending_notice"]
    assert isinstance(notice, dict)
    items = notice.get("items") or []
    assert items
    assert items[0]["tag"] == "v1.1.0"
    assert items[0]["from_tag"] == "v1.0.0"
    assert items[0]["kind"] == "webui"


def test_ack_clears_pending_notice(state_dir) -> None:
    auto.save_auto_update_state({
        "pending_notice": {"tag": "v1.1.0", "from_tag": "v1.0.0", "applied_at": 1.0},
        "last_check_result": "applied",
    })
    out = auto.ack_pending_notice()
    assert out["pending_notice"] is None
    assert auto.load_auto_update_state()["pending_notice"] is None


@pytest.mark.asyncio
async def test_tick_failed_records_error(state_dir) -> None:
    check = {
        "current_tag": "v1.0.0",
        "latest_tag": "v1.1.0",
        "has_update": True,
        "error": None,
    }
    with (
        patch.object(auto, "_load_webui_check", AsyncMock(return_value=check)),
        patch.object(
            auto,
            "apply_webui_dist_update",
            AsyncMock(side_effect=auto.WebuiUpdateError("boom")),
        ),
    ):
        result = await auto.run_webui_auto_update_tick(
            config=_cfg(pallas_webui_auto_update_enabled=True),
            force=True,
        )
    assert result["result"] == "failed"
    assert "boom" in str(result.get("error") or "")
    state = auto.load_auto_update_state()
    assert state["last_check_result"] == "failed"
    assert state["pending_notice"] is None
    assert "boom" in str(state.get("last_error") or "")


@pytest.mark.asyncio
async def test_bot_tick_skips_non_release_tag(state_dir) -> None:
    with patch(
        "packages.pb_webui.manager.inspect_bot_deployment",
        return_value={"deployment_mode": "dev_clone", "git_available": True},
    ):
        result = await auto._run_bot_target(
            config=_cfg(pallas_bot_auto_update_enabled=True, pallas_bot_update_track="release"),
            force=True,
        )
    assert result["result"] == "skipped"
    assert "dev_clone" in str(result.get("reason") or "")
    state = auto.load_auto_update_state()
    assert state["targets"]["bot"]["last_check_result"] == "skipped"
    assert state["targets"]["bot"]["skip_reason"] == "dev_clone"


@pytest.mark.asyncio
async def test_bot_tick_branch_track_applies_on_dev_clone(state_dir) -> None:
    check = {
        "current_tag": "",
        "latest_tag": "v1.1.0",
        "latest_commit": "abc1234",
        "upstream_ref": "origin/dev",
        "has_update": True,
        "error": None,
        "update_track": "branch",
    }
    apply = AsyncMock(return_value={"tag": "abc1234", "message": "ok", "restart_scheduled": True})
    with (
        patch(
            "packages.pb_webui.manager.inspect_bot_deployment",
            return_value={"deployment_mode": "dev_clone", "git_available": True},
        ),
        patch.object(auto, "_load_bot_check", AsyncMock(return_value=check)),
        patch.object(auto, "apply_bot_update", apply),
    ):
        result = await auto._run_bot_target(
            config=_cfg(pallas_bot_auto_update_enabled=True, pallas_bot_update_track="branch"),
            force=True,
        )
    assert result["result"] == "applied"
    apply.assert_awaited_once()


@pytest.mark.asyncio
async def test_bot_tick_applies_on_clean_release_tag(state_dir) -> None:
    check = {
        "current_tag": "v1.0.0",
        "latest_tag": "v1.1.0",
        "has_update": True,
        "error": None,
    }
    apply = AsyncMock(return_value={"tag": "v1.1.0", "message": "ok", "restart_scheduled": True})
    with (
        patch("packages.pb_webui.manager.inspect_bot_deployment", return_value={"deployment_mode": "release_tag"}),
        patch.object(auto, "_load_bot_check", AsyncMock(return_value=check)),
        patch.object(auto, "apply_bot_update", apply),
    ):
        result = await auto._run_bot_target(
            config=_cfg(pallas_bot_auto_update_enabled=True),
            force=True,
        )
    assert result["result"] == "applied"
    apply.assert_awaited_once()
    assert apply.await_args.kwargs.get("restart") is True
    notice = auto.load_auto_update_state()["pending_notice"]
    assert notice
    assert notice["items"][0]["kind"] == "bot"


@pytest.mark.asyncio
async def test_bot_tick_applies_release_in_docker(state_dir) -> None:
    check = {
        "current_tag": "v1.0.0",
        "latest_tag": "v1.1.0",
        "has_update": True,
        "error": None,
    }
    apply = AsyncMock(return_value={"tag": "v1.1.0", "message": "ok", "container_overlay_update": True})
    with (
        patch(
            "packages.pb_webui.manager.inspect_bot_deployment",
            return_value={"deployment_mode": "docker", "git_available": False},
        ),
        patch.object(auto, "_load_bot_check", AsyncMock(return_value=check)),
        patch.object(auto, "apply_bot_update", apply),
    ):
        result = await auto._run_bot_target(
            config=_cfg(pallas_bot_auto_update_enabled=True, pallas_bot_update_track="release"),
            force=True,
        )
    assert result["result"] == "applied"
    apply.assert_awaited_once()


def test_auto_update_status_allows_docker_release(state_dir) -> None:
    with patch(
        "packages.pb_webui.manager.inspect_bot_deployment",
        return_value={"deployment_mode": "docker", "git_available": False},
    ):
        status = auto.auto_update_status_payload(
            _cfg(pallas_bot_auto_update_enabled=True, pallas_bot_update_track="release")
        )
    assert status["bot"]["auto_apply_eligible"] is True


@pytest.mark.asyncio
async def test_unified_tick_runs_enabled_targets(state_dir) -> None:
    webui = AsyncMock(return_value={"result": "up_to_date"})
    bot = AsyncMock(return_value={"result": "skipped", "reason": "deploy:docker"})
    plugins = AsyncMock(return_value={"result": "up_to_date"})
    with (
        patch.object(auto, "_run_webui_target", webui),
        patch.object(auto, "_run_bot_target", bot),
        patch.object(auto, "_run_plugins_target", plugins),
    ):
        out = await auto.run_auto_update_tick(
            config=_cfg(
                pallas_webui_auto_update_enabled=True,
                pallas_bot_auto_update_enabled=False,
                pallas_plugins_auto_update_enabled=True,
            ),
            force=False,
        )
    webui.assert_awaited_once()
    plugins.assert_awaited_once()
    bot.assert_not_awaited()
    assert out["result"] == "up_to_date"
    assert "webui" in out["targets"]
    assert "plugins" in out["targets"]
    assert "bot" not in out["targets"]


@pytest.mark.asyncio
async def test_force_tick_only_runs_enabled_targets(state_dir) -> None:
    webui = AsyncMock(return_value={"result": "up_to_date"})
    bot = AsyncMock(return_value={"result": "up_to_date"})
    plugins = AsyncMock(return_value={"result": "up_to_date"})
    with (
        patch.object(auto, "_run_webui_target", webui),
        patch.object(auto, "_run_bot_target", bot),
        patch.object(auto, "_run_plugins_target", plugins),
    ):
        out = await auto.run_auto_update_tick(
            config=_cfg(
                pallas_webui_auto_update_enabled=True,
                pallas_bot_auto_update_enabled=False,
                pallas_plugins_auto_update_enabled=False,
            ),
            force=True,
        )
    webui.assert_awaited_once()
    bot.assert_not_awaited()
    plugins.assert_not_awaited()
    assert out["result"] == "up_to_date"


@pytest.mark.asyncio
async def test_tick_skips_when_other_job_busy_but_not_own(state_dir) -> None:
    own = await create_update_apply_job("auto")
    own.push("running", "own", progress_percent=5)
    webui = AsyncMock(return_value={"result": "up_to_date"})
    with patch.object(auto, "_run_webui_target", webui):
        out = await auto.run_auto_update_tick(
            config=_cfg(pallas_webui_auto_update_enabled=True),
            force=True,
            progress_job_id=own.job_id,
        )
    webui.assert_awaited_once()
    assert out["result"] == "up_to_date"

    other = await create_update_apply_job("webui")
    other.push("running", "manual", progress_percent=10)
    webui.reset_mock()
    with patch.object(auto, "_run_webui_target", webui):
        out2 = await auto.run_auto_update_tick(
            config=_cfg(pallas_webui_auto_update_enabled=True),
            force=True,
            progress_job_id=own.job_id,
        )
    webui.assert_not_awaited()
    assert out2["result"] == "skipped"
    assert out2["reason"] == "busy"


def test_format_auto_update_notify_message() -> None:
    text = auto.format_auto_update_notify_message([
        {"kind": "webui", "from_tag": "v1.2.2", "tag": "v1.2.3"},
        {"kind": "plugins", "updated": ["a", "b"], "result": "partial"},
    ])
    assert "【自动更新完成】" in text
    assert "WebUI：v1.2.2 -> v1.2.3" in text
    assert "插件（2 个）：" in text


def test_format_auto_update_notify_message_lists_plugin_versions() -> None:
    text = auto.format_auto_update_notify_message([
        {
            "kind": "plugins",
            "updated": [
                {
                    "id": "pallas-plugin-afdian",
                    "source": "official",
                    "from_ref": "0.1.8",
                    "to_ref": "0.1.9",
                },
                {
                    "id": "local_plugin",
                    "source": "community",
                    "from_ref": "a1b2c3d4",
                    "to_ref": "e5f6g7h8",
                    "ref_kind": "commit",
                },
            ],
            "restart_scheduled": True,
        },
    ])

    assert "【自动更新完成】" in text
    assert "插件（2 个）：" in text
    assert "pallas-plugin-afdian：0.1.8 -> 0.1.9" in text
    assert "local_plugin：a1b2c3d4 -> e5f6g7h8（提交）" in text
    assert "已安排重启 Bot" in text


@pytest.mark.asyncio
async def test_notify_superusers_respects_switch_and_bot_id(state_dir) -> None:
    bot_ok = MagicMock()
    bot_ok.self_id = "10001"
    bot_ok.send_private_msg = AsyncMock()
    bot_other = MagicMock()
    bot_other.self_id = "10002"
    bot_other.send_private_msg = AsyncMock()
    driver = MagicMock()
    driver.config.superusers = {"3023094357"}

    with (
        patch("nonebot.get_bots", return_value={"a": bot_ok, "b": bot_other}),
        patch("nonebot.get_driver", return_value=driver),
    ):
        disabled = await auto.notify_superusers_auto_update(
            [{"kind": "webui", "tag": "v1"}],
            config=_cfg(pallas_auto_update_notify_superusers=False),
        )
        assert disabled["reason"] == "disabled"

        offline = await auto.notify_superusers_auto_update(
            [{"kind": "webui", "tag": "v1"}],
            config=_cfg(
                pallas_auto_update_notify_superusers=True,
                pallas_auto_update_notify_bot_id=99999,
            ),
        )
        assert offline["reason"] == "bot_offline"
        bot_ok.send_private_msg.assert_not_awaited()

        sent = await auto.notify_superusers_auto_update(
            [{"kind": "webui", "tag": "v9.9.9"}],
            config=_cfg(
                pallas_auto_update_notify_superusers=True,
                pallas_auto_update_notify_bot_id=10001,
            ),
        )
        assert sent["sent"] is True
        assert sent["bot_id"] == 10001
        bot_ok.send_private_msg.assert_awaited_once()
        kwargs = bot_ok.send_private_msg.await_args.kwargs
        assert kwargs["user_id"] == 3023094357
        assert "v9.9.9" in kwargs["message"]


@pytest.mark.asyncio
async def test_unified_tick_notifies_on_applied(state_dir) -> None:
    notify = AsyncMock(return_value={"sent": True})
    with (
        patch.object(
            auto,
            "_run_webui_target",
            new=AsyncMock(return_value={"result": "applied", "tag": "v2"}),
        ),
        patch.object(auto, "notify_superusers_auto_update", notify),
    ):
        out = await auto.run_auto_update_tick(
            config=_cfg(
                pallas_webui_auto_update_enabled=True,
                pallas_auto_update_notify_superusers=True,
            ),
            force=True,
        )
    assert out["result"] == "applied"
    notify.assert_awaited_once()
    items = notify.await_args.args[0]
    assert items[0]["kind"] == "webui"
    assert items[0]["tag"] == "v2"
