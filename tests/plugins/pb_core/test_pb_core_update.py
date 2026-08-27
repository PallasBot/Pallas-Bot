from unittest.mock import AsyncMock, patch

import pytest

from packages.pb_core.update import (
    apply_update_action,
    apply_update_config_command,
    format_update_check_text,
    parse_update_action,
    parse_update_config_command,
    update_usage_text,
)


def test_parse_update_action():
    assert parse_update_action("牛牛更新") == "check"
    assert parse_update_action("牛牛更新 检查") == "check"
    assert parse_update_action("牛牛更新 帮助") == "help"
    assert parse_update_action("牛牛更新 应用") == "all"
    assert parse_update_action("牛牛更新 全部") == "all"
    assert parse_update_action("牛牛更新 bot") == "bot"
    assert parse_update_action("牛牛更新 webui") == "webui"
    assert parse_update_action("牛牛更新 插件") == "plugins"
    assert parse_update_action("牛牛更新 乱七八糟") is None
    assert parse_update_action("牛牛更新 自动 bot 开") is None


def test_parse_update_config_command():
    auto = parse_update_config_command("牛牛更新 自动 webui 开")
    assert auto is not None
    assert auto.kind == "auto"
    assert auto.target == "webui"
    assert auto.enabled is True

    notify = parse_update_config_command("牛牛更新 汇报 关")
    assert notify is not None
    assert notify.kind == "notify"
    assert notify.enabled is False

    bot = parse_update_config_command("牛牛更新 汇报号 12345")
    assert bot is not None
    assert bot.kind == "notify_bot"
    assert bot.bot_id == 12345

    any_bot = parse_update_config_command("牛牛更新 汇报号 自动")
    assert any_bot is not None
    assert any_bot.bot_id == 0

    assert parse_update_config_command("牛牛更新 应用") is None


@pytest.mark.asyncio
async def test_format_update_check_text_success():
    with (
        patch(
            "packages.pb_webui.manager.get_bot_current_version",
            return_value={"tag": "v1.0.0", "commit": "abc1234"},
        ),
        patch(
            "packages.pb_webui.manager.fetch_latest_bot_release",
            new=AsyncMock(return_value={"tag": "v1.0.0", "html_url": "https://example.com"}),
        ),
        patch("packages.pb_webui.manager.bot_has_release_update", return_value=False),
        patch("packages.pb_webui.manager.bot_is_development_build", return_value=False),
        patch(
            "packages.pb_webui.manager.inspect_bot_deployment",
            return_value={"deployment_mode": "release_tag"},
        ),
        patch(
            "packages.pb_webui.manager.get_installed_webui_version",
            return_value={"tag": "v0.8.0"},
        ),
        patch(
            "packages.pb_webui.manager.resolve_compatible_webui_release",
            new=AsyncMock(
                return_value={
                    "tag": "v0.8.0",
                    "html_url": "https://example.com/releases/v0.8.0",
                    "asset_url": "https://example.com/releases/download/v0.8.0/dist.zip",
                    "min_bot_commit": "a" * 40,
                    "bot_commit": "f" * 40,
                },
            ),
        ) as compatible_resolver,
        patch(
            "packages.pb_webui.manager.fetch_latest_webui_release",
            new=AsyncMock(side_effect=AssertionError("牛牛更新不应直接查询 latest")),
        ),
        patch(
            "pallas.console.webui.plugin_update_snapshot.refresh_plugin_update_snapshot",
            new=AsyncMock(return_value={"official": {}, "community": {}}),
        ),
        patch(
            "packages.pb_webui.webui_auto_update.auto_update_status_payload",
            return_value={
                "webui": {"enabled": False, "last_check_result": "—"},
                "bot": {"enabled": True, "last_check_result": "up_to_date"},
                "plugins": {"enabled": False, "last_check_result": "—"},
                "notify_superusers": True,
                "notify_bot_id": 10001,
            },
        ),
        patch("pallas.console.webui.update_apply_progress.has_active_update_apply_job", return_value=False),
        patch("packages.pb_core.update._github_token", return_value=""),
        patch("packages.pb_webui.config.get_pallas_webui_config") as cfg,
    ):
        cfg.return_value.pallas_webui_dist_zip_repo = "PallasBot/Pallas-Bot"
        cfg.return_value.pallas_webui_dist_zip_asset = "dist.zip"
        cfg.return_value.pallas_webui_dist_zip_tag = ""
        text = await format_update_check_text()
    assert "【Bot】" in text
    assert "当前 v1.0.0" in text
    assert "【WebUI】" in text
    assert "【插件】" in text
    assert "【自动更新】" in text
    assert "汇报 开" in text
    assert "号 10001" in text
    assert "release_tag" in text
    assert "牛牛更新 帮助" in text
    assert "汇报号" not in text  # 完整用法不挂在检查结果后
    assert text.count("\n") < 20
    compatible_resolver.assert_awaited_once_with(
        "PallasBot/Pallas-Bot-WebUI",
        "dist.zip",
        "",
        token="",
    )


@pytest.mark.asyncio
async def test_apply_update_action_help_returns_usage():
    text = await apply_update_action("help")
    assert "用法" in text
    assert "汇报" in text


@pytest.mark.asyncio
async def test_apply_update_action_all_runs_three_targets():
    with (
        patch(
            "pallas.console.webui.update_apply_progress.has_active_update_apply_job",
            return_value=False,
        ),
        patch(
            "packages.pb_core.update._apply_webui",
            new=AsyncMock(return_value={"result": "up_to_date"}),
        ),
        patch(
            "packages.pb_core.update._apply_plugins",
            new=AsyncMock(return_value={"result": "up_to_date", "updated": [], "failed": []}),
        ),
        patch(
            "packages.pb_core.update._apply_bot",
            new=AsyncMock(return_value={"result": "applied", "tag": "v1.2.3"}),
        ),
    ):
        text = await apply_update_action("all")
    assert "全部更新结束" in text
    assert "WebUI：已是最新" in text
    assert "Bot：已应用" in text


@pytest.mark.asyncio
async def test_apply_plugins_lists_updated_plugin_versions():
    with (
        patch(
            "pallas.console.webui.update_apply_progress.has_active_update_apply_job",
            return_value=False,
        ),
        patch(
            "packages.pb_core.update._apply_plugins",
            new=AsyncMock(
                return_value={
                    "result": "applied",
                    "updated": [
                        {
                            "id": "pallas-plugin-afdian",
                            "source": "official",
                            "from_ref": "0.1.8",
                            "to_ref": "0.1.9",
                        },
                    ],
                    "restart_scheduled": True,
                },
            ),
        ),
    ):
        text = await apply_update_action("plugins")

    assert "【插件更新】" in text
    assert "pallas-plugin-afdian：0.1.8 -> 0.1.9" in text
    assert "已安排重启 Bot" in text


def test_apply_update_config_command_patches_pb_webui():
    with patch(
        "pallas.console.webui.plugin_api.apply_plugin_config_patch",
        return_value={},
    ) as patch_cfg:
        text = apply_update_config_command(parse_update_config_command("牛牛更新 自动 bot 开"))
        assert "Bot自动更新：开" in text
        patch_cfg.assert_called_once_with("pb_webui", {"pallas_bot_auto_update_enabled": True})

        text2 = apply_update_config_command(parse_update_config_command("牛牛更新 汇报号 0"))
        assert "任选" in text2
        assert patch_cfg.call_args_list[-1].args == (
            "pb_webui",
            {"pallas_auto_update_notify_bot_id": 0},
        )


def test_update_usage_mentions_private_superuser():
    assert "超管私聊" in update_usage_text()
    assert "汇报" in update_usage_text()
