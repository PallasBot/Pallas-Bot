"""
Pytest configuration and fixtures for beanie ODM testing.

Uses mongomock_motor to provide in-memory MongoDB for async tests.
"""

import pytest


@pytest.fixture
async def beanie_fixture():
    """
    Initialize beanie with mongomock_motor for in-memory MongoDB testing.

    Registers all Document models and clears collections after each test.
    """
    from beanie import init_beanie
    from mongomock_motor import AsyncMongoMockClient

    from src.common.db.modules import (
        BlackList,
        BotConfigModule,
        Context,
        GroupConfigModule,
        ImageCache,
        Message,
        UserConfigModule,
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
