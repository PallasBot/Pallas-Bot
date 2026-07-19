from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from types import SimpleNamespace

import pytest

from packages.repeater.responder import Responder


def test_should_skip_context_lookup_for_pure_cq_message() -> None:
    chat_data = SimpleNamespace(
        is_plain_text=False,
        plain_text="",
        to_me=False,
        keywords_len=0,
    )

    assert Responder.should_skip_context_lookup(chat_data, "[CQ:image,file=a.jpg]") is True


def test_should_not_skip_context_lookup_for_non_plain_with_text() -> None:
    chat_data = SimpleNamespace(
        is_plain_text=False,
        plain_text="诡异吗",
        to_me=False,
        keywords_len=1,
    )

    assert Responder.should_skip_context_lookup(chat_data, "诡异") is False


def test_should_skip_short_plain_text_in_unified_mode(monkeypatch) -> None:
    monkeypatch.setattr(
        "packages.repeater.responder.shard_ctx.sharding_active",
        lambda: False,
    )
    chat_data = SimpleNamespace(
        is_plain_text=True,
        plain_text="草",
        to_me=False,
        keywords_len=1,
    )

    assert Responder.should_skip_context_lookup(chat_data, "草") is True


def test_should_not_skip_short_plain_text_in_sharded_mode(monkeypatch) -> None:
    monkeypatch.setattr(
        "packages.repeater.responder.shard_ctx.sharding_active",
        lambda: True,
    )
    chat_data = SimpleNamespace(
        is_plain_text=True,
        plain_text="草",
        to_me=False,
        keywords_len=1,
    )

    assert Responder.should_skip_context_lookup(chat_data, "草") is False


def test_should_not_skip_empty_keyword_plain_text_in_sharded_mode(monkeypatch) -> None:
    monkeypatch.setattr(
        "packages.repeater.responder.shard_ctx.sharding_active",
        lambda: True,
    )
    chat_data = SimpleNamespace(
        is_plain_text=True,
        plain_text="啊？",
        to_me=False,
        keywords_len=0,
    )

    assert Responder.should_skip_context_lookup(chat_data, "啊？") is False


@pytest.mark.asyncio
async def test_context_find_pure_cq_skips_before_keywords(monkeypatch) -> None:
    from collections import defaultdict, deque

    class _ChatData:
        group_id = 1
        raw_message = "[CQ:image,file=a.jpg]"
        plain_text = ""
        bot_id = 2
        is_plain_text = False
        is_image = True
        to_me = False

        @property
        def keywords(self) -> str:
            raise AssertionError("keywords should not be accessed for pure CQ skip")

    class _Config:
        async def drunkenness(self) -> int:
            return 0

    monkeypatch.setattr(
        "packages.repeater.responder.get_bots",
        dict,
    )

    result = await Responder._context_find(
        _ChatData(),
        _Config(),
        defaultdict(lambda: defaultdict(list)),
        defaultdict(list),
        defaultdict(lambda: deque(maxlen=16)),
    )

    assert result is None


@pytest.mark.asyncio
async def test_answer_still_skips_one_char_plain_text_in_unified_mode(monkeypatch) -> None:
    from collections import defaultdict, deque

    monkeypatch.setattr(
        "packages.repeater.responder.shard_ctx.sharding_active",
        lambda: False,
    )

    chat_data = SimpleNamespace(
        is_plain_text=True,
        plain_text="草",
        group_id=1,
        bot_id=2,
    )

    result = await Responder.answer(
        chat_data,
        SimpleNamespace(),
        defaultdict(lambda: defaultdict(list)),
        asyncio.Lock(),
        defaultdict(lambda: deque(maxlen=16)),
        asyncio.Lock(),
    )

    assert result is None


@pytest.mark.asyncio
async def test_answer_allows_one_char_plain_text_in_sharded_mode(monkeypatch) -> None:
    from collections import defaultdict, deque

    monkeypatch.setattr(
        "packages.repeater.responder.shard_ctx.sharding_active",
        lambda: True,
    )

    bundle = object()

    async def fake_find_reply_bundle(*args, **kwargs):
        return bundle

    async def fake_answer_from_bundle(*args, **kwargs):
        return "sentinel"

    monkeypatch.setattr(Responder, "find_reply_bundle", fake_find_reply_bundle)
    monkeypatch.setattr(Responder, "answer_from_bundle", fake_answer_from_bundle)

    chat_data = SimpleNamespace(
        is_plain_text=True,
        plain_text="草",
        group_id=1,
        bot_id=2,
    )

    result = await Responder.answer(
        chat_data,
        SimpleNamespace(),
        defaultdict(lambda: defaultdict(list)),
        asyncio.Lock(),
        defaultdict(lambda: deque(maxlen=16)),
        asyncio.Lock(),
    )

    assert result == "sentinel"


@pytest.mark.asyncio
async def test_context_find_skips_when_pg_pool_under_pressure(monkeypatch) -> None:
    from collections import defaultdict, deque

    class _ChatData:
        group_id = 1
        raw_message = "hello world"
        plain_text = "hello world"
        bot_id = 2
        is_plain_text = True
        is_image = False
        to_me = False
        keywords_len = 2

        @property
        def keywords(self) -> str:
            return "hello world"

    class _Config:
        async def drunkenness(self) -> int:
            return 0

    async def fail_find(*args, **kwargs):
        raise AssertionError("find_by_keywords should not run under pool pressure")

    monkeypatch.setattr(
        "packages.repeater.responder.pg_pool_under_pressure",
        lambda threshold=0.55: True,
    )
    monkeypatch.setattr(
        "packages.repeater.responder.context_repo.find_by_keywords",
        fail_find,
    )

    result = await Responder._context_find(
        _ChatData(),
        _Config(),
        defaultdict(lambda: defaultdict(list)),
        defaultdict(list),
        defaultdict(lambda: deque(maxlen=16)),
    )

    assert result is None


@pytest.mark.asyncio
async def test_context_find_db_timeout_returns_none(monkeypatch) -> None:
    from sqlalchemy.exc import TimeoutError as SATimeoutError

    class _ChatData:
        group_id = 1
        raw_message = "hello world"
        plain_text = "hello world"
        bot_id = 2
        is_plain_text = True
        is_image = False
        to_me = False
        keywords_len = 2

        @property
        def keywords(self) -> str:
            return "hello world"

    class _Config:
        async def drunkenness(self) -> int:
            return 0

    async def timeout_find(keywords: str):
        raise SATimeoutError("QueuePool limit of size 8 overflow 4 reached", None, None)

    monkeypatch.setattr(
        "packages.repeater.responder.pg_pool_under_pressure",
        lambda threshold=0.55: False,
    )

    class _Repo:
        async def find_by_keywords_for_reply(self, keywords: str):
            return await timeout_find(keywords)

    monkeypatch.setattr("packages.repeater.responder.context_repo", _Repo())

    result = await Responder._context_find(
        _ChatData(),
        _Config(),
        defaultdict(lambda: defaultdict(list)),
        defaultdict(list),
        defaultdict(lambda: deque(maxlen=16)),
    )

    assert result is None


@pytest.mark.asyncio
async def test_context_find_passes_group_id_to_resolve_persona(monkeypatch) -> None:
    from pallas.core.foundation.db.modules import Answer, Context

    class _ChatData:
        group_id = 123
        raw_message = "hello world"
        plain_text = "hello world"
        bot_id = 456
        is_plain_text = True
        is_image = False
        to_me = False
        keywords_len = 2
        _keywords_list = ["hello", "world"]

        @property
        def keywords(self) -> str:
            return "hello world"

    class _Config:
        async def drunkenness(self) -> int:
            return 1

    seen: list[tuple[int, int, str]] = []

    async def fake_resolve_persona_for_message(bot_id: int, group_id: int, plain_text: str):
        from pallas.product.persona.model import ResolvedPersona

        seen.append((bot_id, group_id, plain_text))
        return ResolvedPersona()

    async def fake_load_affect_triggers(_group_id: int):
        return []

    async def fake_find(_keywords: str):
        return Context.model_construct(
            keywords="hello world",
            time=1,
            trigger_count=1,
            answers=[Answer(keywords="ans", group_id=123, count=2, time=1, messages=["收到"])],
            ban=[],
            clear_time=0,
        )

    monkeypatch.setattr("packages.repeater.responder.pg_pool_under_pressure", lambda threshold=0.55: False)
    monkeypatch.setattr("pallas.product.persona.resolve_persona_for_message", fake_resolve_persona_for_message)
    monkeypatch.setattr("pallas.product.persona.loader.load_affect_triggers", fake_load_affect_triggers)

    class _Repo:
        async def find_by_keywords_for_reply(self, keywords: str):
            return await fake_find(keywords)

    monkeypatch.setattr("packages.repeater.responder.context_repo", _Repo())

    async def fake_find_ban_keywords(**_kwargs):
        return set()

    monkeypatch.setattr("packages.repeater.ban_manager.BanManager.find_ban_keywords", fake_find_ban_keywords)
    monkeypatch.setattr("packages.repeater.activity_gate.group_has_hosted_activity", lambda _gid: False)

    result = await Responder._context_find(
        _ChatData(),
        _Config(),
        defaultdict(lambda: defaultdict(list)),
        defaultdict(list, {123: []}),
        defaultdict(lambda: deque(maxlen=16)),
    )

    assert result is not None
    assert seen == [(456, 123, "hello world")]
