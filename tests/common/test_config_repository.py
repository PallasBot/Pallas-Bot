"""
ConfigRepository 的 MongoDB 实现 + Config 基类契约测试。

覆盖：
- MongoConfigRepository.get / get_or_create / upsert_field / invalidate_cache
- BotConfig / GroupConfig / UserConfig 通过 repo 路径正确读写
"""

from __future__ import annotations

import pytest

from src.common.db.modules import BotConfigModule, GroupConfigModule, UserConfigModule
from src.common.db.repository import ConfigRepository
from src.common.db.repository_impl import MongoConfigRepository


def test_mongo_config_repo_satisfies_protocol():
    assert isinstance(MongoConfigRepository(BotConfigModule, "account"), ConfigRepository)
    assert isinstance(MongoConfigRepository(GroupConfigModule, "group_id"), ConfigRepository)
    assert isinstance(MongoConfigRepository(UserConfigModule, "user_id"), ConfigRepository)


@pytest.mark.asyncio
async def test_get_returns_none_when_missing(beanie_fixture):
    repo = MongoConfigRepository(BotConfigModule, "account")
    assert await repo.get(42) is None


@pytest.mark.asyncio
async def test_get_or_create_creates_document(beanie_fixture):
    repo = MongoConfigRepository(BotConfigModule, "account")
    doc, created = await repo.get_or_create(100, disabled_plugins=["foo"])
    assert created is True
    assert doc.account == 100
    assert doc.disabled_plugins == ["foo"]

    # Second call should return existing
    doc2, created2 = await repo.get_or_create(100, disabled_plugins=["bar"])
    assert created2 is False
    assert doc2.disabled_plugins == ["foo"]  # 不覆盖


@pytest.mark.asyncio
async def test_upsert_field_creates_then_updates(beanie_fixture):
    repo = MongoConfigRepository(BotConfigModule, "account")

    # 不存在时 upsert_field 应创建新文档
    await repo.upsert_field(200, "disabled_plugins", ["a"])
    doc = await repo.get(200, ignore_cache=True)
    assert doc is not None
    assert doc.disabled_plugins == ["a"]

    # 存在时 upsert_field 应更新字段
    await repo.upsert_field(200, "disabled_plugins", ["a", "b"])
    doc = await repo.get(200, ignore_cache=True)
    assert doc is not None
    assert doc.disabled_plugins == ["a", "b"]


@pytest.mark.asyncio
async def test_invalidate_cache_is_safe(beanie_fixture):
    repo = MongoConfigRepository(BotConfigModule, "account")
    # 不应抛错，即使没有任何缓存条目
    await repo.invalidate_cache()


@pytest.mark.asyncio
async def test_bot_config_class_uses_repo(beanie_fixture):
    from src.common.config import BotConfig

    bot = BotConfig(bot_id=999)
    assert await bot.security() is False  # default
    assert await bot.auto_accept_friend() is False
    assert await bot.auto_accept_group() is False


@pytest.mark.asyncio
async def test_group_config_class_uses_repo(beanie_fixture):
    from src.common.config import GroupConfig

    group = GroupConfig(group_id=500)
    assert await group.is_banned() is False
    await group.ban()
    assert await group.is_banned() is True
    # roulette_mode 默认值兜底
    assert await group.roulette_mode() == 1
    await group.set_roulette_mode(0)
    assert await group.roulette_mode() == 0


@pytest.mark.asyncio
async def test_user_config_class_uses_repo(beanie_fixture):
    from src.common.config import UserConfig

    user = UserConfig(user_id=700)
    assert await user.is_banned() is False
    await user.ban()
    assert await user.is_banned() is True
