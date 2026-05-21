import pytest

from src.common.ingress import (
    IngressConfig,
    acquire_slow_event_slot,
    clear_ingress_config_cache,
    ingress_group_message_fanout_all_bots,
    ingress_message_uses_duel_claim,
    is_command_like_plaintext,
    is_duel_ingress_priority_plaintext,
    notice_shard_key,
    release_slow_event_slot,
    should_apply_ingress_slow_path,
    should_repeater_skip_group_message,
    should_sample_keep_notice,
    slow_event_overflow_held,
    slow_event_slot_held,
)
from src.common.ingress import dispatch as ingress_dispatch_mod
from src.common.ingress import fast_lane as ingress_fast_lane_mod
from src.common.ingress.gate import should_skip_ingress_dispatch_for_bot
from src.common.multi_bot import try_claim_cross_bot_message_memory
from src.plugins.duel.duel_bots import duel_narrator_bot_id


def test_ingress_fanout_greeting_only():
    class Ev:
        def __init__(self, plain: str, raw: str | None = None):
            self._plain = plain
            self.raw_message = raw if raw is not None else plain

        def get_plaintext(self):
            return self._plain

    assert ingress_group_message_fanout_all_bots(Ev("牛牛"))  # type: ignore[arg-type]
    assert ingress_group_message_fanout_all_bots(Ev("帕拉斯"))  # type: ignore[arg-type]
    assert not ingress_group_message_fanout_all_bots(Ev("牛牛喝酒"))  # type: ignore[arg-type]
    assert not ingress_group_message_fanout_all_bots(Ev("牛牛干杯"))  # type: ignore[arg-type]
    assert not ingress_group_message_fanout_all_bots(Ev("牛牛帮助"))  # type: ignore[arg-type]
    assert not ingress_group_message_fanout_all_bots(Ev("牛牛决斗 @1"))  # type: ignore[arg-type]


def test_is_command_like_plaintext_niuniu():
    assert is_command_like_plaintext("牛牛MAA状态")
    assert is_command_like_plaintext("  牛牛帮助  ")
    assert not is_command_like_plaintext("今天天气不错")
    assert is_command_like_plaintext("随便", is_tome=True)


def test_duel_cage_is_fast_lane_and_skips_slow_path():
    assert is_duel_ingress_priority_plaintext("八角笼牛")
    assert is_duel_ingress_priority_plaintext("八角笼斗 7幕")
    assert is_command_like_plaintext("八角笼牛")

    class Meta:
        pass

    class Ev:
        def get_plaintext(self):
            return "八角笼牛"

    assert not should_apply_ingress_slow_path(Meta())
    assert not should_apply_ingress_slow_path(Ev())  # type: ignore[arg-type]


def test_notice_shard_key_poke():
    class Ev:
        notice_type = "notify"
        sub_type = "poke"
        group_id = 123
        user_id = 1
        target_id = 2

    assert notice_shard_key(Ev()) == "poke:123:1:2"  # type: ignore[arg-type]


def test_notice_sample_always_keep_when_prob_one(monkeypatch):
    clear_ingress_config_cache()
    monkeypatch.setenv("PALLAS_NOTICE_EMOJI_LIKE_KEEP", "1.0")
    assert should_sample_keep_notice("group_msg_emoji_like", None) is True


def test_ingress_config_fast_lane_prefix(monkeypatch):
    clear_ingress_config_cache()
    monkeypatch.setenv("PALLAS_INGRESS_FAST_LANE_PREFIX", "牛牛")
    cfg = IngressConfig.from_env()
    assert cfg.fast_lane_command_prefix == "牛牛"
    assert is_command_like_plaintext("牛牛决斗 @1")


def test_duel_narrator_dual_bot_uses_min_id():
    assert duel_narrator_bot_id("100", "200", dual_bot=True) == 100
    assert duel_narrator_bot_id("200", "100", dual_bot=True) == 100


@pytest.mark.asyncio
async def test_slow_path_overflow_when_drop_disabled(monkeypatch):
    clear_ingress_config_cache()
    monkeypatch.setenv("PALLAS_INGRESS_SLOW_DROP", "false")
    monkeypatch.setenv("PALLAS_INGRESS_SLOW_CONCURRENCY", "1")
    monkeypatch.setenv("PALLAS_INGRESS_SLOW_OVERFLOW", "1")
    monkeypatch.setenv("PALLAS_INGRESS_SLOW_ACQUIRE_SEC", "0.05")

    ingress_fast_lane_mod._SLOW_EVENT_SEM = None
    ingress_fast_lane_mod._SLOW_SEM_LIMIT = None
    ingress_fast_lane_mod._SLOW_OVERFLOW_SEM = None
    ingress_fast_lane_mod._SLOW_OVERFLOW_LIMIT = None
    ingress_fast_lane_mod._SLOW_SLOT_HELD.clear()
    ingress_fast_lane_mod._SLOW_OVERFLOW_HELD.clear()
    monkeypatch.setattr(ingress_fast_lane_mod, "should_apply_ingress_slow_path", lambda _e: True)

    class Ev:
        pass

    ev = Ev()
    assert await acquire_slow_event_slot(ev) is True
    assert slow_event_slot_held(ev)

    ev2 = Ev()
    assert await acquire_slow_event_slot(ev2) is True
    assert slow_event_overflow_held(ev2)

    ev3 = Ev()
    assert await acquire_slow_event_slot(ev3) is False

    release_slow_event_slot(ev)
    release_slow_event_slot(ev2)


@pytest.mark.asyncio
async def test_slow_path_drop_when_enabled(monkeypatch):
    clear_ingress_config_cache()
    monkeypatch.setenv("PALLAS_INGRESS_SLOW_DROP", "true")
    monkeypatch.setenv("PALLAS_INGRESS_SLOW_CONCURRENCY", "1")
    monkeypatch.setenv("PALLAS_INGRESS_SLOW_ACQUIRE_SEC", "0.05")

    ingress_fast_lane_mod._SLOW_EVENT_SEM = None
    ingress_fast_lane_mod._SLOW_SEM_LIMIT = None
    ingress_fast_lane_mod._SLOW_SLOT_HELD.clear()
    monkeypatch.setattr(ingress_fast_lane_mod, "should_apply_ingress_slow_path", lambda _e: True)

    class Ev:
        pass

    ev = Ev()
    assert await acquire_slow_event_slot(ev) is True
    ev2 = Ev()
    assert await acquire_slow_event_slot(ev2) is False
    release_slow_event_slot(ev)


def test_should_repeater_skip_group_message():
    class Ev:
        def __init__(self, plain: str, *, to_me: bool = False):
            self._plain = plain
            self._to_me = to_me

        def get_plaintext(self):
            return self._plain

        def is_tome(self):
            return self._to_me

    assert not should_repeater_skip_group_message(Ev("牛牛"))  # type: ignore[arg-type]
    assert not should_repeater_skip_group_message(Ev("帕拉斯"))  # type: ignore[arg-type]
    assert should_repeater_skip_group_message(Ev("牛牛帮助"))  # type: ignore[arg-type]
    assert should_repeater_skip_group_message(Ev("随便", to_me=True))  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_dispatch_entry_skip_uses_memory_claim_before_file(monkeypatch):
    clear_ingress_config_cache()
    monkeypatch.setenv("PALLAS_INGRESS_MULTI_BOT_SHARD", "true")

    class Ev:
        group_id = 733291779
        user_id = 3023094357
        time = 100

        def get_plaintext(self):
            return "牛牛帮助"

    gid, uid, body, t = Ev.group_id, Ev.user_id, Ev().get_plaintext(), Ev.time
    assert await try_claim_cross_bot_message_memory("ingress", gid, uid, body, t, 111) is True
    assert await should_skip_ingress_dispatch_for_bot(222, Ev()) is True  # type: ignore[arg-type]
    assert await should_skip_ingress_dispatch_for_bot(111, Ev()) is False  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_ingress_dispatch_fast_lane_schedules_task(monkeypatch):
    clear_ingress_config_cache()
    calls: list[str] = []

    async def fake_handle(bot, event):
        calls.append(getattr(event, "tag", "unknown"))

    import nonebot.message as nb_message

    nb_message.handle_event = fake_handle
    ingress_dispatch_mod._orig_handle_event = fake_handle
    ingress_dispatch_mod._dispatch_installed = True
    ingress_dispatch_mod._slow_queue = None
    ingress_dispatch_mod._slow_worker_tasks = []

    class FastEv:
        tag = "fast"

    class SlowEv:
        tag = "slow"

    monkeypatch.setattr(ingress_dispatch_mod, "ingress_fast_lane_enabled", lambda: True)
    monkeypatch.setattr(ingress_dispatch_mod, "should_apply_ingress_slow_path", lambda e: e.tag == "slow")
    async def no_shard_drop(_b, _e):
        return False

    monkeypatch.setattr(ingress_dispatch_mod, "_ingress_dispatch_shard_drop", no_shard_drop)

    class Bot:
        type = "test"
        self_id = "1"

    await ingress_dispatch_mod.ingress_handle_event(Bot(), FastEv())  # type: ignore[arg-type]
    assert calls == []
    await __import__("asyncio").sleep(0.05)
    assert calls == ["fast"]

    ingress_dispatch_mod._slow_queue = __import__("asyncio").Queue(maxsize=8)
    ingress_dispatch_mod.start_ingress_slow_dispatch_workers()
    await ingress_dispatch_mod.ingress_handle_event(Bot(), SlowEv())  # type: ignore[arg-type]
    await __import__("asyncio").sleep(0.05)
    assert calls == ["fast", "slow"]
    await ingress_dispatch_mod.stop_ingress_slow_dispatch_workers()
    ingress_dispatch_mod._dispatch_installed = False
    ingress_dispatch_mod._orig_handle_event = None


@pytest.mark.asyncio
async def test_ingress_dispatch_shard_drop_skips_handle(monkeypatch):
    clear_ingress_config_cache()
    calls: list[str] = []

    async def fake_handle(bot, event):
        calls.append("run")

    ingress_dispatch_mod._orig_handle_event = fake_handle
    monkeypatch.setattr(ingress_dispatch_mod, "ingress_fast_lane_enabled", lambda: True)
    monkeypatch.setattr(ingress_dispatch_mod, "should_apply_ingress_slow_path", lambda _e: False)
    async def shard_drop(_b, _e):
        return True

    monkeypatch.setattr(ingress_dispatch_mod, "_ingress_dispatch_shard_drop", shard_drop)

    class Bot:
        self_id = "99"

    class Ev:
        pass

    await ingress_dispatch_mod.ingress_handle_event(Bot(), Ev())  # type: ignore[arg-type]
    await __import__("asyncio").sleep(0.05)
    assert calls == []


def test_slow_dispatch_worker_count_auto_cap(monkeypatch):
    clear_ingress_config_cache()
    monkeypatch.setenv("PALLAS_INGRESS_SLOW_CONCURRENCY", "96")
    monkeypatch.delenv("PALLAS_INGRESS_SLOW_DISPATCH_WORKERS", raising=False)
    assert ingress_dispatch_mod.slow_dispatch_worker_count() == 24

    clear_ingress_config_cache()
    monkeypatch.setenv("PALLAS_INGRESS_SLOW_DISPATCH_WORKERS", "8")
    assert ingress_dispatch_mod.slow_dispatch_worker_count() == 8


@pytest.mark.asyncio
async def test_acquire_slow_event_slot_reentrant_after_worker(monkeypatch):
    clear_ingress_config_cache()
    monkeypatch.setenv("PALLAS_INGRESS_SLOW_DROP", "false")
    monkeypatch.setenv("PALLAS_INGRESS_SLOW_CONCURRENCY", "1")
    monkeypatch.setenv("PALLAS_INGRESS_SLOW_OVERFLOW", "0")

    ingress_fast_lane_mod._SLOW_EVENT_SEM = None
    ingress_fast_lane_mod._SLOW_SEM_LIMIT = None
    ingress_fast_lane_mod._SLOW_SLOT_HELD.clear()
    monkeypatch.setattr(ingress_fast_lane_mod, "should_apply_ingress_slow_path", lambda _e: True)

    class Ev:
        pass

    ev = Ev()
    assert await acquire_slow_event_slot(ev) is True
    assert await acquire_slow_event_slot(ev) is True
    release_slow_event_slot(ev)


@pytest.mark.asyncio
async def test_reload_ingress_dispatch_runtime_rebuilds_workers(monkeypatch):
    clear_ingress_config_cache()
    monkeypatch.setenv("PALLAS_INGRESS_SLOW_CONCURRENCY", "2")
    monkeypatch.setenv("PALLAS_INGRESS_SLOW_OVERFLOW", "4")

    ingress_fast_lane_mod._SLOW_EVENT_SEM = None
    ingress_fast_lane_mod._SLOW_SEM_LIMIT = None
    ingress_fast_lane_mod._SLOW_OVERFLOW_SEM = None
    ingress_fast_lane_mod._SLOW_OVERFLOW_LIMIT = None
    ingress_fast_lane_mod._SLOW_SLOT_HELD.clear()
    ingress_fast_lane_mod._SLOW_OVERFLOW_HELD.clear()

    ingress_dispatch_mod._slow_queue = None
    ingress_dispatch_mod._slow_worker_tasks = []

    async def fake_handle(bot, event):
        pass

    ingress_dispatch_mod._orig_handle_event = fake_handle
    ingress_dispatch_mod.start_ingress_slow_dispatch_workers()
    assert len(ingress_dispatch_mod._slow_worker_tasks) == 2

    monkeypatch.setenv("PALLAS_INGRESS_SLOW_CONCURRENCY", "3")
    monkeypatch.setenv("PALLAS_INGRESS_SLOW_DISPATCH_WORKERS", "3")
    await ingress_dispatch_mod.reload_ingress_dispatch_runtime()
    assert len(ingress_dispatch_mod._slow_worker_tasks) == 3
    await ingress_dispatch_mod.stop_ingress_slow_dispatch_workers()


def test_ingress_message_uses_duel_claim():
    class Ev:
        def get_plaintext(self):
            return "牛牛决斗 @1"

    assert ingress_message_uses_duel_claim(Ev())  # type: ignore[arg-type]
    assert ingress_message_uses_duel_claim(
        type("E", (), {"get_plaintext": lambda self: "八角笼牛 7幕"})()  # type: ignore[arg-type]
    )
