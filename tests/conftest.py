"""
Pytest configuration and fixtures for beanie ODM testing.

Uses mongomock_motor to provide in-memory MongoDB for async tests.
"""

import pytest


@pytest.fixture(autouse=True)
def _reset_embedding_runtime_state() -> None:
    """每个测试后清理 embedding 模块全局状态，避免跨文件顺序污染。"""
    yield
    try:
        from pallas.product.llm.feedback_embedding_cache import clear_feedback_embedding_caches_for_tests

        clear_feedback_embedding_caches_for_tests()
    except Exception:
        pass
    try:
        from pallas.product.llm.knowledge import embedding_client

        embedding_client._last_embedding_error = ""
    except Exception:
        pass


@pytest.fixture
async def beanie_fixture(monkeypatch: pytest.MonkeyPatch):
    """
    Initialize beanie with mongomock_motor for in-memory MongoDB testing.

    Registers all Document models and clears collections after each test.
    """
    monkeypatch.setenv("DB_BACKEND", "mongodb")
    import nonebot

    monkeypatch.setattr(nonebot.get_driver().config, "db_backend", "mongodb", raising=False)

    from beanie import init_beanie
    from mongomock_motor import AsyncMongoMockClient

    from pallas.core.foundation.db.modules import (
        BlackList,
        BotConfigModule,
        Context,
        GroupConfigModule,
        ImageCache,
        LlmChatMessage,
        LlmMemoryEntry,
        LlmRelationshipNote,
        Message,
        StickerLabel,
        UserConfigModule,
        UserStickerStat,
    )

    motor_client = AsyncMongoMockClient()
    motor_db = motor_client["test_pallas_bot"]

    # mongomock_motor 的 list_collection_names 不接受 nameOnly 等 kwargs，
    # Beanie init 会向其传递 kwargs，这里做一层 shim 让 kwargs 被丢弃
    original_motor_list = motor_db.list_collection_names

    async def patched_motor_list(session=None, **kwargs):  # noqa: ARG001
        return original_motor_list(session=session)

    motor_db.list_collection_names = patched_motor_list

    await init_beanie(
        database=motor_db,
        document_models=[
            BotConfigModule,
            GroupConfigModule,
            UserConfigModule,
            Message,
            Context,
            BlackList,
            ImageCache,
            LlmChatMessage,
            LlmMemoryEntry,
            LlmRelationshipNote,
            StickerLabel,
            UserStickerStat,
        ],
        allow_index_dropping=True,
    )

    yield

    await motor_db.drop_collection("config")
    await motor_db.drop_collection("group_config")
    await motor_db.drop_collection("user_config")
    await motor_db.drop_collection("message")
    await motor_db.drop_collection("context")
    await motor_db.drop_collection("blacklist")
    await motor_db.drop_collection("image_cache")
    await motor_db.drop_collection("llm_chat_message")
    await motor_db.drop_collection("llm_memory_entry")
    await motor_db.drop_collection("llm_relationship_note")
    await motor_db.drop_collection("sticker_label")
    await motor_db.drop_collection("user_sticker_stat")
    motor_client.close()


def pytest_configure(config):  # noqa: ARG001
    """Initialize NoneBot before running tests."""
    import nonebot

    # Check if NoneBot is already initialized
    try:
        nonebot.get_driver()
    except ValueError:
        # Not initialized, so initialize it
        nonebot.init()


@pytest.fixture(autouse=True)
def _reset_nonebot_plugin_registry():
    """恢复测试期间变更的 NoneBot 插件注册状态。"""
    from nonebot import plugin as nb_plugin
    from nonebot.plugin import manager as nb_manager

    saved_plugins = dict(nb_plugin._plugins)
    saved_managers = list(nb_plugin._managers)
    saved_current_plugin = nb_manager._current_plugin.get()
    yield
    nb_plugin._plugins.clear()
    nb_plugin._plugins.update(saved_plugins)
    nb_plugin._managers[:] = saved_managers
    nb_manager._current_plugin.set(saved_current_plugin)
