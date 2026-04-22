"""
跨后端切换测试：注册一个纯内存的 fake backend，验证通过 DB_BACKEND 切换时，
make_*_repository 工厂会返回该后端的实例，保护"切换后端不需要改业务代码"契约。
"""

from __future__ import annotations

import pytest


class _FakeContextRepo:
    async def find_by_keywords(self, keywords):  # noqa: ARG002
        return None

    async def save(self, context):  # noqa: ARG002
        return None

    async def insert(self, context):  # noqa: ARG002
        return None

    async def delete_expired(self, expiration, threshold):  # noqa: ARG002
        return None

    async def find_for_cleanup(self, trigger_threshold, expiration):  # noqa: ARG002
        return []

    async def upsert_answer(self, keywords, group_id, answer_keywords, answer_time, message, append_on_existing):  # noqa: ARG002
        return None

    async def replace_answers(self, keywords, answers, clear_time):  # noqa: ARG002
        return None

    async def append_ban(self, keywords, ban):  # noqa: ARG002
        return None


class _FakeMessageRepo:
    async def bulk_insert(self, messages):  # noqa: ARG002
        return None


class _FakeBlackListRepo:
    async def find_all(self):
        return []

    async def upsert_answers(self, group_id, answers):  # noqa: ARG002
        return None

    async def upsert_answers_reserve(self, group_id, answers):  # noqa: ARG002
        return None


async def _fake_init():
    return None


@pytest.fixture
def fake_backend():
    """注册名为 'fake' 的内存后端，测试结束后清理。"""
    from src.common.db import (
        BLACKLIST_REPO_REGISTRY,
        CONTEXT_REPO_REGISTRY,
        INIT_DB_REGISTRY,
        MESSAGE_REPO_REGISTRY,
        register_backend,
    )

    register_backend(
        "fake",
        _FakeContextRepo,
        _FakeMessageRepo,
        _FakeBlackListRepo,
        _fake_init,
    )
    try:
        yield "fake"
    finally:
        CONTEXT_REPO_REGISTRY.pop("fake", None)
        MESSAGE_REPO_REGISTRY.pop("fake", None)
        BLACKLIST_REPO_REGISTRY.pop("fake", None)
        INIT_DB_REGISTRY.pop("fake", None)


def _set_db_backend(monkeypatch, backend: str) -> None:
    """同时覆盖 nonebot driver config 与 env，兼容 get_db_backend 的双源读取。

    get_db_backend() 优先从 nonebot.get_driver().config.db_backend 读取，fallback 到
    DB_BACKEND 环境变量；.env 里若已设置 DB_BACKEND，nonebot 启动时会把它写进 config，
    单纯 monkeypatch.setenv 不会生效。
    """
    import nonebot

    monkeypatch.setenv("DB_BACKEND", backend)
    try:
        cfg = nonebot.get_driver().config
        monkeypatch.setattr(cfg, "db_backend", backend, raising=False)
    except Exception:
        pass


def test_factories_switch_by_db_backend_env(monkeypatch, fake_backend):
    """当 DB_BACKEND=fake 时，所有 Repository 工厂应返回 fake 实例。"""
    from src.common.db import (
        make_blacklist_repository,
        make_context_repository,
        make_message_repository,
    )

    _set_db_backend(monkeypatch, fake_backend)

    ctx = make_context_repository()
    msg = make_message_repository()
    bl = make_blacklist_repository()

    assert isinstance(ctx, _FakeContextRepo)
    assert isinstance(msg, _FakeMessageRepo)
    assert isinstance(bl, _FakeBlackListRepo)


def test_unknown_backend_raises(monkeypatch):
    """未注册的后端应抛 ValueError，明确提示已注册的后端列表。"""
    from src.common.db import make_context_repository

    _set_db_backend(monkeypatch, "nonexistent-backend")

    with pytest.raises(ValueError, match="不支持的数据库后端"):
        make_context_repository()


@pytest.mark.asyncio
async def test_init_db_dispatches_to_registered_backend(fake_backend):
    """init_db 应根据 backend 参数分发到对应后端的 init 函数。"""
    from src.common.db import init_db

    # fake backend 的 init 直接返回 None 不抛异常
    await init_db(backend=fake_backend)
