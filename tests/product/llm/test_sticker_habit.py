from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

CAT_CQ = "[CQ:image,file=CAT.image,subType=0,url=https://gchat.qpic.cn/a?term=2&amp;x=1]"
CAT_CODE = "[CQ:image,file=CAT.image]"
DOG_CQ = "[CQ:image,file=DOG.image]"
DOG_CODE = "[CQ:image,file=DOG.image]"
CAT_HASH = "a" * 64
DOG_HASH = "b" * 64


def _msg(message_id: int, user_id: int, raw_message: str, *, time_ts: int, bot_id: int = 0):
    return SimpleNamespace(
        message_id=message_id,
        user_id=user_id,
        bot_id=bot_id,
        raw_message=raw_message,
        plain_text="",
        time=time_ts,
    )


class _DummyMessageRepo:
    """模拟 list_group_messages_after：(time, message_id) 复合边界 + 升序翻页。"""

    def __init__(self, messages):
        self._messages = messages

    async def list_group_messages_after(self, group_id, *, after_time, after_message_id=None, limit=2000):
        items = []
        for message in self._messages:
            if int(message.time) < int(after_time):
                continue
            if after_message_id is not None and int(message.time) == int(after_time):
                if int(message.message_id) <= int(after_message_id):
                    continue
            items.append(message)
        items.sort(key=lambda m: (int(m.time), int(m.message_id)))
        cap = max(1, min(int(limit), 4096))
        return items[:cap]


class _DummyStatRepo:
    def __init__(self):
        self.rows: dict[tuple[int, int, str], dict] = {}
        self.prune_calls: list[tuple[int, int]] = []

    async def increment(self, *, group_id, user_id, content_hash, sent_at, count=1):
        key = (int(group_id), int(user_id), content_hash)
        row = self.rows.setdefault(key, {"send_count": 0, "last_sent_at": 0})
        row["send_count"] += int(count)
        row["last_sent_at"] = max(row["last_sent_at"], int(sent_at))

    async def delete_cold(self, *, before_ts, max_count):
        self.prune_calls.append((int(before_ts), int(max_count)))
        return 0

    async def get(self, *, group_id, user_id, content_hash):
        row = self.rows.get((int(group_id), int(user_id), content_hash))
        if row is None:
            return None
        return SimpleNamespace(
            group_id=int(group_id),
            user_id=int(user_id),
            content_hash=content_hash,
            send_count=row["send_count"],
            last_sent_at=row["last_sent_at"],
        )

    async def list_group_candidates(self, *, group_id, min_count, limit=5):
        hits = [
            (key, row)
            for key, row in self.rows.items()
            if key[0] == int(group_id) and row["send_count"] >= int(min_count)
        ]
        hits.sort(key=lambda item: (-item[1]["send_count"], -item[1]["last_sent_at"]))
        return [
            SimpleNamespace(
                group_id=key[0],
                user_id=key[1],
                content_hash=key[2],
                send_count=row["send_count"],
                last_sent_at=row["last_sent_at"],
            )
            for key, row in hits[: max(1, min(int(limit), 100))]
        ]


class _DummyImageRepo:
    def __init__(self, hash_by_code):
        self._hash_by_code = hash_by_code

    async def find_by_cq_code(self, cq_code):
        content_hash = self._hash_by_code.get(cq_code)
        return SimpleNamespace(content_hash=content_hash) if content_hash else None


class _DummyLabelRepo:
    def __init__(self, labels):
        self._labels = labels

    async def get(self, content_hash):
        return self._labels.get(content_hash)


def _cfg(**overrides):
    values = {
        "llm_sticker_habit_enabled": True,
        "llm_sticker_habit_min_count": 5,
        "llm_sticker_habit_top_k": 1,
        "llm_sticker_habit_backfill_days": 7,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
def habit_env(monkeypatch, tmp_path):
    """patch 仓储工厂、游标文件与 person facts 存储；返回可断言的假仓储集合。"""
    from pallas.product.llm import sticker_habit as mod

    stat_repo = _DummyStatRepo()
    image_repo = _DummyImageRepo({CAT_CODE: CAT_HASH, DOG_CODE: DOG_HASH})
    label_repo = _DummyLabelRepo({CAT_HASH: SimpleNamespace(is_sticker=True, caption="一只歪头的橘猫")})
    monkeypatch.setattr(mod, "make_user_sticker_stat_repository", lambda: stat_repo)
    monkeypatch.setattr(mod, "make_image_cache_repository", lambda: image_repo)
    monkeypatch.setattr(mod, "make_sticker_label_repository", lambda: label_repo)
    monkeypatch.setattr(mod, "_sticker_habit_cursor_path", lambda: tmp_path / "group_cursors.json")
    monkeypatch.setattr(mod, "_sticker_habit_prune_state_path", lambda: tmp_path / "prune_state.json")
    monkeypatch.setattr("pallas.product.llm.memory.person_facts._store_path", lambda: tmp_path / "person_facts.json")
    monkeypatch.setattr("pallas.product.llm.config.get_llm_config", lambda: _cfg())
    monkeypatch.setattr("pallas.product.llm.group_insight_processor._resolve_semantic_bot", _resolve_bot_101)
    return SimpleNamespace(stat_repo=stat_repo, label_repo=label_repo, tmp_path=tmp_path, mod=mod)


async def _resolve_bot_101(group_id: int) -> int:
    return 101


def test_extract_image_cq_codes_matches_capture_normalization() -> None:
    from pallas.product.llm.sticker_habit import extract_image_cq_codes

    raw = f"看这个{CAT_CQ}还有{DOG_CQ}"
    assert extract_image_cq_codes(raw) == [CAT_CODE, DOG_CODE]
    assert extract_image_cq_codes("纯文本消息") == []
    # 与 media_cache.normalize_image_cq_code 对同一 segment 的输出一致
    from nonebot.adapters.onebot.v11 import Message

    from pallas.core.shared.utils.media_cache import normalize_image_cq_code

    assert extract_image_cq_codes(CAT_CQ) == [normalize_image_cq_code(Message(CAT_CQ)[0])]


@pytest.mark.asyncio
async def test_scan_group_dedupes_multi_bot_rows_and_skips_bot_senders(habit_env, monkeypatch) -> None:
    mod = habit_env.mod
    # 测试环境无 bot catalog，直接指定身份判定
    monkeypatch.setattr(mod, "sender_kind", lambda user_id, *, self_bot_id: "peer_bot" if user_id == 101 else "human")
    now = int(time.time())
    messages = [
        _msg(1, 100, CAT_CQ, time_ts=now - 50, bot_id=1),
        _msg(1, 100, CAT_CQ, time_ts=now - 50, bot_id=2),  # 多账号重复录制
        _msg(2, 101, CAT_CQ, time_ts=now - 40, bot_id=1),  # peer bot 发送，跳过
        _msg(3, 200, "纯文本", time_ts=now - 30, bot_id=1),
        _msg(4, 300, DOG_CQ, time_ts=now - 20, bot_id=1),
    ]
    repo = _DummyMessageRepo(messages)

    cursor, events, scanned = await mod._scan_group_messages(group_id=1, cursor=(0, 0), repo=repo)

    # 重复录制行被 (time, message_id) 游标比较跳过，不消耗扫描预算
    assert scanned == 4
    assert cursor == (now - 20, 4)
    assert [(user_id, code) for user_id, code, _t in events] == [(100, CAT_CODE), (300, DOG_CODE)]


@pytest.mark.asyncio
async def test_scan_group_pays_attention_to_cursor_budget(habit_env) -> None:
    mod = habit_env.mod
    now = int(time.time())
    messages = [_msg(index, 100, "文本", time_ts=now - 1000 + index, bot_id=1) for index in range(12)]
    repo = _DummyMessageRepo(messages)

    _cursor, events, scanned = await mod._scan_group_messages(group_id=1, cursor=(now - 996, 0), repo=repo)

    # 游标 (now-996, 0) 之后：time > 游标秒的 7 行 + 同秒 mid>0 的 1 行
    assert scanned == 8
    assert events == []


@pytest.mark.asyncio
async def test_run_pass_records_stats_and_projects_fact(habit_env, monkeypatch) -> None:
    mod = habit_env.mod
    now = int(time.time())
    messages = [_msg(index + 1, 100, CAT_CQ, time_ts=now - 100 + index, bot_id=1) for index in range(5)]
    monkeypatch.setattr(mod, "make_message_repository", lambda: _DummyMessageRepo(messages))
    # 预置游标让群进入本轮扫描集合
    habit_env.tmp_path.joinpath("group_cursors.json").write_text(json.dumps({"777": [now - 1000, 0]}), encoding="utf-8")

    totals = await mod.run_sticker_habit_pass()

    assert totals["groups"] == 1
    assert totals["messages"] == 5
    assert totals["images"] == 5
    assert totals["facts"] == 1
    stat = await habit_env.stat_repo.get(group_id=777, user_id=100, content_hash=CAT_HASH)
    assert stat is not None
    assert stat.send_count == 5

    from pallas.product.llm.memory.person_facts import list_person_facts

    facts = list_person_facts(bot_id=101, group_id=777, user_id=100)
    assert [fact.content for fact in facts] == ["常用表情包：一只歪头的橘猫"]
    assert [fact.source for fact in facts] == ["sticker_habit"]

    cursor_state = json.loads(habit_env.tmp_path.joinpath("group_cursors.json").read_text(encoding="utf-8"))
    assert cursor_state["777"] == [now - 96, 5]

    # 第二轮无增量：游标推进、不重复写 fact
    monkeypatch.setattr(mod, "make_message_repository", lambda: _DummyMessageRepo([]))
    totals_again = await mod.run_sticker_habit_pass()
    assert totals_again["messages"] == 0
    facts_again = list_person_facts(bot_id=101, group_id=777, user_id=100)
    assert len(facts_again) == 1


@pytest.mark.asyncio
async def test_run_pass_replaces_fact_when_favorite_changes(habit_env, monkeypatch) -> None:
    mod = habit_env.mod
    now = int(time.time())

    async def fake_enqueue(content_hash: str) -> bool:
        return False

    monkeypatch.setattr(mod, "_enqueue_sticker_label_for_hash", fake_enqueue)
    habit_env.tmp_path.joinpath("group_cursors.json").write_text(json.dumps({"777": [now - 1000, 0]}), encoding="utf-8")

    first = [_msg(index + 1, 100, CAT_CQ, time_ts=now - 100 + index, bot_id=1) for index in range(5)]
    monkeypatch.setattr(mod, "make_message_repository", lambda: _DummyMessageRepo(first))
    await mod.run_sticker_habit_pass()

    second = [_msg(10 + index, 100, DOG_CQ, time_ts=now + index, bot_id=1) for index in range(6)]
    monkeypatch.setattr(mod, "make_message_repository", lambda: _DummyMessageRepo(second))
    # 让狗图也有标签
    habit_env.label_repo._labels[DOG_HASH] = SimpleNamespace(is_sticker=True, caption="一只吐舌的柴犬")
    await mod.run_sticker_habit_pass()

    from pallas.product.llm.memory.person_facts import list_person_facts

    facts = list_person_facts(bot_id=101, group_id=777, user_id=100)
    assert [fact.content for fact in facts] == ["常用表情包：一只吐舌的柴犬"]
    assert [fact.status for fact in facts] == ["active"]


@pytest.mark.asyncio
async def test_run_pass_below_threshold_or_unlabeled_falls_back(habit_env, monkeypatch) -> None:
    mod = habit_env.mod
    now = int(time.time())
    habit_env.tmp_path.joinpath("group_cursors.json").write_text(json.dumps({"777": [now - 1000, 0]}), encoding="utf-8")
    enqueue_calls: list[str] = []

    async def fake_enqueue(content_hash: str) -> bool:
        enqueue_calls.append(content_hash)
        return True

    monkeypatch.setattr(mod, "_enqueue_sticker_label_for_hash", fake_enqueue)

    # 阈值未到：只计数、不投影也不补标
    few = [_msg(index + 1, 100, CAT_CQ, time_ts=now - 100 + index, bot_id=1) for index in range(2)]
    monkeypatch.setattr(mod, "make_message_repository", lambda: _DummyMessageRepo(few))
    totals = await mod.run_sticker_habit_pass()
    assert totals["facts"] == 0
    assert totals["label_queued"] == 0
    assert enqueue_calls == []

    # 跨过阈值但无标签：本轮触发一次补标，不写 fact
    unlabeled = [_msg(10 + index, 100, DOG_CQ, time_ts=now - 50 + index, bot_id=1) for index in range(5)]
    monkeypatch.setattr(mod, "make_message_repository", lambda: _DummyMessageRepo(unlabeled))
    totals = await mod.run_sticker_habit_pass()
    assert totals["facts"] == 0
    assert totals["label_queued"] == 1
    assert enqueue_calls == [DOG_HASH]

    from pallas.product.llm.memory.person_facts import list_person_facts

    assert list_person_facts(bot_id=101, group_id=777, user_id=100) == []


@pytest.mark.asyncio
async def test_run_pass_disabled_is_noop(habit_env, monkeypatch) -> None:
    mod = habit_env.mod
    monkeypatch.setattr("pallas.product.llm.config.get_llm_config", lambda: _cfg(llm_sticker_habit_enabled=False))
    monkeypatch.setattr(mod, "make_message_repository", lambda: (_ for _ in ()).throw(AssertionError("不应扫描")))

    totals = await mod.run_sticker_habit_pass()

    assert totals == {"groups": 0, "messages": 0, "images": 0, "facts": 0, "label_queued": 0}


@pytest.mark.asyncio
async def test_run_pass_jumps_stale_cursor(habit_env, monkeypatch) -> None:
    mod = habit_env.mod
    now = int(time.time())
    habit_env.tmp_path.joinpath("group_cursors.json").write_text(
        json.dumps({"777": [now - 30 * 86400, 7]}), encoding="utf-8"
    )
    messages = [
        _msg(1, 100, CAT_CQ, time_ts=now - 20 * 86400, bot_id=1),  # 回填窗口之外，陈旧游标跳过后不计
        _msg(2, 100, CAT_CQ, time_ts=now - 60, bot_id=1),
        _msg(3, 100, CAT_CQ, time_ts=now - 59, bot_id=1),
        _msg(4, 100, CAT_CQ, time_ts=now - 58, bot_id=1),
        _msg(5, 100, CAT_CQ, time_ts=now - 57, bot_id=1),
        _msg(6, 100, CAT_CQ, time_ts=now - 56, bot_id=1),
    ]
    monkeypatch.setattr(mod, "make_message_repository", lambda: _DummyMessageRepo(messages))

    totals = await mod.run_sticker_habit_pass()

    assert totals["messages"] == 5
    stat = await habit_env.stat_repo.get(group_id=777, user_id=100, content_hash=CAT_HASH)
    assert stat is not None
    assert stat.send_count == 5


@pytest.mark.asyncio
async def test_run_pass_projects_top_k_facts(habit_env, monkeypatch) -> None:
    mod = habit_env.mod
    now = int(time.time())
    monkeypatch.setattr("pallas.product.llm.config.get_llm_config", lambda: _cfg(llm_sticker_habit_top_k=2))
    habit_env.tmp_path.joinpath("group_cursors.json").write_text(json.dumps({"777": [now - 1000, 0]}), encoding="utf-8")
    messages = [_msg(index + 1, 100, CAT_CQ, time_ts=now - 100 + index, bot_id=1) for index in range(5)] + [
        _msg(10 + index, 100, DOG_CQ, time_ts=now - 50 + index, bot_id=1) for index in range(6)
    ]
    monkeypatch.setattr(mod, "make_message_repository", lambda: _DummyMessageRepo(messages))
    habit_env.label_repo._labels[DOG_HASH] = SimpleNamespace(is_sticker=True, caption="一只吐舌的柴犬")

    totals = await mod.run_sticker_habit_pass()

    assert totals["facts"] == 2
    from pallas.product.llm.memory.person_facts import list_person_facts

    facts = list_person_facts(bot_id=101, group_id=777, user_id=100)
    assert [(fact.source, fact.content) for fact in facts] == [
        ("sticker_habit", "常用表情包：一只吐舌的柴犬"),
        ("sticker_habit:2", "也常发表情包：一只歪头的橘猫"),
    ]

    # K 调回 1 且群有新消息时，多余的键控事实被清理
    monkeypatch.setattr("pallas.product.llm.config.get_llm_config", lambda: _cfg(llm_sticker_habit_top_k=1))
    monkeypatch.setattr(
        mod, "make_message_repository", lambda: _DummyMessageRepo([_msg(30, 100, DOG_CQ, time_ts=now + 50, bot_id=1)])
    )
    await mod.run_sticker_habit_pass()

    facts_after = list_person_facts(bot_id=101, group_id=777, user_id=100)
    assert [(fact.source, fact.status) for fact in facts_after] == [("sticker_habit", "active")]


@pytest.mark.asyncio
async def test_prune_cold_stats_runs_once_per_day(habit_env, monkeypatch) -> None:
    mod = habit_env.mod
    now = int(time.time())
    habit_env.tmp_path.joinpath("group_cursors.json").write_text(json.dumps({"777": [now - 1000, 0]}), encoding="utf-8")
    monkeypatch.setattr(mod, "make_message_repository", lambda: _DummyMessageRepo([]))

    await mod.run_sticker_habit_pass()
    await mod.run_sticker_habit_pass()

    assert len(habit_env.stat_repo.prune_calls) == 1
    before_ts, max_count = habit_env.stat_repo.prune_calls[0]
    assert max_count == 2
    assert now - before_ts == 90 * 86400


@pytest.mark.asyncio
async def test_enqueue_label_respects_gates(monkeypatch) -> None:
    from pallas.product.llm import sticker_habit as mod
    from pallas.product.llm import sticker_label_jobs as jobs_mod

    created = []

    class _FakeStore:
        async def requeue_terminal(self, job):
            created.append(job)
            return job, True

    monkeypatch.setattr(jobs_mod, "lazy_sticker_labels_paused", lambda: False)
    monkeypatch.setattr(jobs_mod, "sticker_label_circuit_open", lambda: False)
    monkeypatch.setattr(jobs_mod, "sticker_label_realtime_budget_ok", lambda: True)
    monkeypatch.setattr("pallas.core.platform.work_jobs.runtime.build_work_job_store", lambda: _FakeStore())
    monkeypatch.setattr("pallas.product.llm.task_metrics.record_bot_llm_task", lambda *a, **k: None)

    assert await mod._enqueue_sticker_label_for_hash(CAT_HASH) is True
    assert len(created) == 1
    assert created[0].payload["content_hash"] == CAT_HASH

    monkeypatch.setattr(jobs_mod, "sticker_label_realtime_budget_ok", lambda: False)
    assert await mod._enqueue_sticker_label_for_hash(CAT_HASH) is False
    assert len(created) == 1

    monkeypatch.setattr(jobs_mod, "sticker_label_realtime_budget_ok", lambda: True)
    monkeypatch.setattr(jobs_mod, "lazy_sticker_labels_paused", lambda: True)
    assert await mod._enqueue_sticker_label_for_hash(CAT_HASH) is False
    assert len(created) == 1


@pytest.mark.asyncio
async def test_replace_person_fact_by_source_semantics(habit_env) -> None:
    from pallas.product.llm.memory.person_facts import (
        list_person_facts,
        replace_person_fact_by_source,
    )

    first = replace_person_fact_by_source(
        bot_id=1, group_id=2, user_id=3, source="sticker_habit", content="常用表情包：猫猫", confidence=0.8
    )
    assert first is not None

    # 同文 no-op
    assert (
        replace_person_fact_by_source(
            bot_id=1, group_id=2, user_id=3, source="sticker_habit", content="常用表情包：猫猫"
        )
        is None
    )
    assert len(list_person_facts(bot_id=1, group_id=2, user_id=3)) == 1

    # 换文：旧 active 置 forgotten，新条 active；其它来源事实不受影响
    replace_person_fact_by_source(bot_id=1, group_id=2, user_id=3, source="conversation", content="喜欢玩游戏")
    replaced = replace_person_fact_by_source(
        bot_id=1, group_id=2, user_id=3, source="sticker_habit", content="常用表情包：柴犬"
    )
    assert replaced is not None
    facts = list_person_facts(bot_id=1, group_id=2, user_id=3)
    assert sorted((fact.source, fact.status) for fact in facts) == [
        ("conversation", "active"),
        ("sticker_habit", "active"),
    ]
    all_rows = list_person_facts(bot_id=1, group_id=2, user_id=3, status=None)
    assert sorted((fact.source, fact.status) for fact in all_rows) == [
        ("conversation", "active"),
        ("sticker_habit", "active"),
        ("sticker_habit", "forgotten"),
    ]

    # 空内容不做任何改动
    assert replace_person_fact_by_source(bot_id=1, group_id=2, user_id=3, source="sticker_habit", content="  ") is None
