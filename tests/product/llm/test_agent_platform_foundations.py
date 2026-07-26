from __future__ import annotations

from pallas.product.llm.orchestration.subagent import create_subagent_run, run_subagent_job
from pallas.product.llm.orchestration.task_store import cancel_task, create_task, list_tasks
from pallas.product.llm.tools.contracts import ProactiveDeliveryContract, TaskContract, ToolCapability
from pallas.product.persona.catchphrase_bank import (
    compile_catchphrase_prompt_lines,
    is_auto_promote_eligible,
    list_catchphrases,
    promote_catchphrase,
    propose_catchphrase_from_bot_success,
    propose_catchphrases_from_utterance,
    reject_catchphrase,
)
from pallas.product.persona.catchphrase_extract import (
    extract_catchphrase_candidates,
    is_catchphrase_habit,
    parse_llm_catchphrase_payload,
)


def test_tool_capability_and_contracts() -> None:
    assert ToolCapability.EXTERNAL_NETWORK.value == "external_network"
    task = TaskContract(task_id="t1", name="remind", group_id=1)
    assert task.status == "pending"
    delivery = ProactiveDeliveryContract(group_id=1, text="hello")
    assert delivery.source == "task"


def test_task_store_create_and_cancel(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    task = create_task("once", {"text": "hi"}, group_id=733291779)
    assert task.task_id.startswith("task-")
    assert any(item.task_id == task.task_id for item in list_tasks())
    cancelled = cancel_task(task.task_id)
    assert cancelled is not None
    assert cancelled.status == "cancelled"


def test_subagent_run_records_artifact(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    task = create_task("research", {"query": "x"}, group_id=1)
    run = create_subagent_run(task.task_id, allowed_tools=["web.search"], budget=2)
    finished = run_subagent_job(run, steps=["search", "summarize"])
    assert finished.status == "completed"
    assert finished.artifacts
    assert finished.run_id == run.run_id


def test_catchphrase_extract_prefers_short_habits() -> None:
    assert is_catchphrase_habit("我chovy")
    assert is_catchphrase_habit("那很牛了")
    assert not is_catchphrase_habit("那我能聊梗、接接梗、开开玩啊，找我玩就行")
    assert not is_catchphrase_habit("行行行")
    assert not is_catchphrase_habit("还行吧")
    assert not is_catchphrase_habit("好好好")
    cands = extract_catchphrase_candidates("哈哈我chovy真的，那很牛了")
    sayings = [s for s, _ in cands]
    assert "我chovy" in sayings
    assert "那很牛了" in sayings
    assert all(is_catchphrase_habit(s) for s in sayings)
    long_cands = extract_catchphrase_candidates("那我能聊梗、接接梗、开开玩啊，找我玩就行")
    assert long_cands == []
    soft_cands = extract_catchphrase_candidates("行行行，我闭嘴就是。还行吧。")
    assert soft_cands == []
    raw = (
        '{"items":[{"saying":"我chovy","occasion":"自称梗"},'
        '{"saying":"行行行","occasion":"口头禅"},'
        '{"saying":"那我能聊梗接接梗开开玩啊找我玩就行","occasion":"x"}]}'
    )
    assert parse_llm_catchphrase_payload(raw) == [("我chovy", "自称梗")]


def test_catchphrase_promotion_requires_evidence(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    assert propose_catchphrase_from_bot_success(1001, 11, "那我能聊梗、接接梗、开开玩啊", "介绍") is None
    first = propose_catchphrase_from_bot_success(1001, 11, "那很牛了", "口头禅")
    assert first is not None
    assert not is_auto_promote_eligible(first)
    second = propose_catchphrase_from_bot_success(1001, 22, "那很牛了", "口头禅")
    third = propose_catchphrase_from_bot_success(1001, 33, "那很牛了", "口头禅")
    assert third is not None
    assert is_auto_promote_eligible(third)
    promoted = promote_catchphrase(third.entry_id)
    assert promoted is not None
    assert promoted.status == "active"
    lines = compile_catchphrase_prompt_lines(1001)
    assert any("那很牛了" in line for line in lines)
    assert any("当「" in line and "可以自然用" in line for line in lines)
    assert lines[0].startswith("【表达习惯参考")
    rejected = reject_catchphrase(second.entry_id if second else third.entry_id)
    assert rejected is not None
    assert list_catchphrases(1001)


def test_catchphrase_rejects_weak_soft_agree(tmp_path, monkeypatch) -> None:
    from pallas.product.persona.catchphrase_bank import reject_weak_filler_catchphrases

    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    assert propose_catchphrase_from_bot_success(1001, 11, "行行行", "口头禅") is None
    # 旧数据：人工写入弱填充后应被 purge
    from pallas.product.persona.catchphrase_bank import CatchphraseEntry, _load, _save

    rows = _load()
    rows.append(
        CatchphraseEntry(
            entry_id="catch-weak-test",
            bot_id=1001,
            saying="行行行",
            occasion="口头禅",
            status="active",
        )
    )
    _save(rows)
    assert reject_weak_filler_catchphrases(1001) >= 1
    assert all(row.status == "rejected" for row in list_catchphrases(1001) if row.saying == "行行行")


def test_catchphrase_from_utterance_does_not_store_full_reply(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    long_reply = "那我能聊梗、接接梗、开开玩啊，找我玩就行"
    assert propose_catchphrases_from_utterance(1001, 733291779, long_reply) == []
    mined = propose_catchphrases_from_utterance(1001, 733291779, "今天也是我chovy的一天")
    assert len(mined) == 1
    assert mined[0].saying == "我chovy"
