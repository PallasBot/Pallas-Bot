from __future__ import annotations

import json
import multiprocessing
import threading
import time
from pathlib import Path

import pytest


def _write_person_fact_in_process(operation: str, payload: dict, start_event) -> None:
    if not start_event.wait(timeout=5):
        raise TimeoutError("test writer start gate timed out")
    original_write_text = Path.write_text

    def delayed_write_text(path: Path, text: str, *args, **kwargs):
        if path.name == "person_facts.json":
            with path.open("w", encoding=kwargs.get("encoding")) as stream:
                stream.write("")
                time.sleep(0.05)
                stream.write(text)
            return len(text)
        if path.name.startswith("person_facts.") and path.suffix == ".tmp":
            time.sleep(0.05)
        return original_write_text(path, text, *args, **kwargs)

    Path.write_text = delayed_write_text
    from pallas.product.llm.memory import person_facts

    if operation == "save":
        person_facts.save_person_fact(**payload)
    elif operation == "replace":
        person_facts.replace_person_fact_by_source(**payload)
    elif operation == "correct":
        person_facts.correct_person_fact(**payload)
    elif operation == "status":
        person_facts.update_person_fact_status(**payload)
    elif operation == "forget":
        person_facts.forget_person_facts_by_source(**payload)
    else:
        raise AssertionError(f"unknown write operation: {operation}")


def _hold_person_fact_lock(lock_path: str, locked_event) -> None:
    from pallas.core.foundation.fs_lock import interprocess_file_lock

    with interprocess_file_lock(Path(lock_path)):
        locked_event.set()
        while True:
            time.sleep(0.05)


@pytest.mark.asyncio
async def test_person_facts_injection_does_not_block_event_loop(monkeypatch) -> None:
    import asyncio

    from pallas.product.llm.memory import person_facts
    from pallas.product.llm.memory.inject import enrich_system_with_person_facts

    callback_ran = asyncio.Event()
    callback_observed_during_read: list[bool] = []
    loop = asyncio.get_running_loop()
    loop.call_later(0.01, callback_ran.set)

    def slow_read() -> list:
        time.sleep(0.05)
        callback_observed_during_read.append(callback_ran.is_set())
        return []

    monkeypatch.setattr(person_facts, "_read_facts", slow_read)

    await enrich_system_with_person_facts("prompt", bot_id=1, group_id=2, user_id=3)

    assert callback_observed_during_read == [True]


def test_person_facts_cross_process_writes_are_atomic_and_visible(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))

    fact_path = tmp_path / "pallas_llm" / "person_facts.json"
    fact_path.parent.mkdir(parents=True)
    original_write_text = Path.write_text
    original_write_text(fact_path, '{"items": []}\n', encoding="utf-8")
    from pallas.product.llm.memory.person_facts import list_person_facts

    assert list_person_facts(bot_id=1, group_id=2, status=None) == []
    stop_reader = threading.Event()
    invalid_snapshots: list[str] = []

    def read_snapshots() -> None:
        while not stop_reader.is_set():
            try:
                json.loads(fact_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                invalid_snapshots.append(str(exc))
            time.sleep(0.001)

    ctx = multiprocessing.get_context("spawn")
    start_event = ctx.Event()
    processes = [
        ctx.Process(
            target=_write_person_fact_in_process,
            args=(
                "save",
                {
                    "bot_id": 1,
                    "group_id": 2,
                    "user_id": index,
                    "content": f"process-{index}",
                    "source": "process_test",
                },
                start_event,
            ),
        )
        for index in range(8)
    ]
    reader = threading.Thread(target=read_snapshots)
    try:
        for process in processes:
            process.start()
        reader.start()
        start_event.set()
        for process in processes:
            process.join(timeout=10)
            assert process.exitcode == 0
    finally:
        stop_reader.set()
        reader.join(timeout=2)

    assert not invalid_snapshots

    facts = list_person_facts(bot_id=1, group_id=2, status=None)
    assert {fact.content for fact in facts} == {f"process-{index}" for index in range(8)}


def test_different_person_fact_writes_do_not_overwrite_each_other(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    from pallas.product.llm.memory.person_facts import list_person_facts, save_person_fact

    correct = save_person_fact(bot_id=1, group_id=2, user_id=10, content="before correction", source="correction")
    freeze = save_person_fact(bot_id=1, group_id=2, user_id=11, content="freeze me", source="status")
    replace = save_person_fact(bot_id=1, group_id=2, user_id=12, content="old", source="replace")
    forget = save_person_fact(bot_id=1, group_id=2, user_id=13, content="remove", source="cleanup")

    writes = [
        ("save", {"bot_id": 1, "group_id": 2, "user_id": 14, "content": "concurrent add"}),
        ("correct", {"fact_id": correct.fact_id, "content": "corrected"}),
        ("status", {"fact_id": freeze.fact_id, "status": "frozen"}),
        (
            "replace",
            {"bot_id": 1, "group_id": 2, "user_id": 12, "source": "replace", "content": "new"},
        ),
        ("forget", {"bot_id": 1, "group_id": 2, "user_id": 13, "sources": ["cleanup"]}),
    ]
    ctx = multiprocessing.get_context("spawn")
    start_event = ctx.Event()
    processes = [ctx.Process(target=_write_person_fact_in_process, args=(*write, start_event)) for write in writes]
    for process in processes:
        process.start()
    start_event.set()
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0

    facts = list_person_facts(bot_id=1, group_id=2, status=None)
    by_id = {fact.fact_id: fact for fact in facts}
    assert by_id[correct.fact_id].content == "corrected"
    assert by_id[correct.fact_id].version == 2
    assert by_id[freeze.fact_id].status == "frozen"
    assert by_id[replace.fact_id].status == "forgotten"
    assert by_id[forget.fact_id].status == "forgotten"
    assert {fact.content for fact in facts} >= {"concurrent add", "new"}


def test_person_fact_lock_recovers_after_holder_process_is_killed(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    fact_path = tmp_path / "pallas_llm" / "person_facts.json"
    ctx = multiprocessing.get_context("spawn")
    locked_event = ctx.Event()
    process = ctx.Process(
        target=_hold_person_fact_lock,
        args=(str(fact_path.with_suffix(".lock")), locked_event),
    )
    process.start()
    try:
        assert locked_event.wait(timeout=5)
    finally:
        process.terminate()
        process.join(timeout=5)

    assert process.exitcode is not None
    from pallas.product.llm.memory.person_facts import list_person_facts, save_person_fact

    save_person_fact(bot_id=1, group_id=2, user_id=3, content="after lock recovery")

    assert [fact.content for fact in list_person_facts(bot_id=1, group_id=2)] == ["after lock recovery"]


def _valid_fact_row(**overrides) -> dict:
    return {
        "fact_id": "valid-fact",
        "bot_id": 1,
        "group_id": 2,
        "user_id": 3,
        "content": "valid content",
        "source": "test",
        **overrides,
    }


def _attempt_person_fact_write(person_facts, operation: str) -> None:
    if operation == "save":
        person_facts.save_person_fact(bot_id=1, group_id=2, user_id=3, content="new")
    elif operation == "replace":
        person_facts.replace_person_fact_by_source(bot_id=1, group_id=2, user_id=3, source="test", content="new")
    elif operation == "batch":
        person_facts.replace_person_facts_by_source_batch(bot_id=1, group_id=2, replacements=[(3, "test", "new", 0.5)])
    elif operation == "forget_user":
        person_facts.forget_person_facts_by_source(bot_id=1, group_id=2, user_id=3, sources=["test"])
    elif operation == "forget_group":
        person_facts.forget_group_person_facts_by_source(bot_id=1, group_id=2, sources=["test"])
    elif operation == "correct":
        person_facts.correct_person_fact("missing", "new")
    else:
        person_facts.update_person_fact_status("missing", "frozen")


@pytest.mark.parametrize(
    "bad_text",
    [
        "{not-json",
        '{"items": [], "items": []}',
        "{}",
        '{"items": "not-a-list"}',
        '{"items": [{}]}',
        '{"items": [null]}',
        json.dumps({"items": [_valid_fact_row(), {}]}),
    ],
)
@pytest.mark.parametrize("operation", ["save", "replace", "batch", "forget_user", "forget_group", "correct", "status"])
def test_all_mutations_reject_corrupt_store_without_changing_bytes(monkeypatch, tmp_path, bad_text, operation) -> None:
    from pallas.product.llm.memory import person_facts

    path = tmp_path / "person_facts.json"
    path.write_text(bad_text, encoding="utf-8")
    before = path.read_bytes()
    monkeypatch.setattr(person_facts, "_store_path", lambda: path)

    with pytest.raises(person_facts.PersonFactsStoreError):
        _attempt_person_fact_write(person_facts, operation)

    assert path.read_bytes() == before


def test_read_skips_invalid_rows_and_logs_without_fact_contents(monkeypatch, tmp_path) -> None:
    from pallas.product.llm.memory import person_facts

    path = tmp_path / "person_facts.json"
    path.write_text(
        json.dumps({
            "items": [
                _valid_fact_row(),
                {
                    "fact_id": "private",
                    "bot_id": 1,
                    "group_id": 2,
                    "user_id": 4,
                    "private_note": "PRIVATE_FACT_TEXT",
                },
            ]
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(person_facts, "_store_path", lambda: path)
    warnings: list[tuple] = []
    monkeypatch.setattr(person_facts, "log_rate_limited", lambda *args, **kwargs: warnings.append(args))

    facts = person_facts.list_person_facts(bot_id=1, group_id=2, status=None)

    assert [fact.fact_id for fact in facts] == ["valid-fact"]
    assert warnings
    assert "PRIVATE_FACT_TEXT" not in repr(warnings)


def test_read_tolerates_invalid_structure_and_warns(monkeypatch, tmp_path) -> None:
    from pallas.product.llm.memory import person_facts

    path = tmp_path / "person_facts.json"
    path.write_text("not-json", encoding="utf-8")
    monkeypatch.setattr(person_facts, "_store_path", lambda: path)
    warnings: list[tuple] = []
    monkeypatch.setattr(person_facts, "log_rate_limited", lambda *args, **kwargs: warnings.append(args))

    assert person_facts.list_person_facts(bot_id=1, group_id=2) == []
    assert warnings
    assert all("not-json" not in repr(warning) for warning in warnings)


def test_store_path_initialization_error_degrades_reads_and_rejects_writes(monkeypatch) -> None:
    from pallas.product.llm.memory import person_facts

    def fail_store_path():
        raise OSError("private path detail")

    monkeypatch.setattr(person_facts, "_store_path", fail_store_path)
    warnings: list[tuple] = []
    monkeypatch.setattr(person_facts, "log_rate_limited", lambda *args, **kwargs: warnings.append(args))

    assert person_facts.list_person_facts(bot_id=1) == []
    assert warnings
    assert "private path detail" not in repr(warnings)
    with pytest.raises(OSError, match="private path detail"):
        person_facts.save_person_fact(bot_id=1, group_id=2, user_id=3, content="refused")


def test_write_read_error_preserves_existing_store(monkeypatch, tmp_path) -> None:
    from pallas.product.llm.memory import person_facts

    path = tmp_path / "person_facts.json"
    path.write_text(json.dumps({"items": [_valid_fact_row()]}), encoding="utf-8")
    before = path.read_bytes()
    monkeypatch.setattr(person_facts, "_store_path", lambda: path)
    original_read_text = Path.read_text

    def fail_store_read(candidate: Path, *args, **kwargs):
        if candidate == path:
            raise OSError("sensitive filesystem detail")
        return original_read_text(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_store_read)

    with pytest.raises(person_facts.PersonFactsStoreError, match="person facts store could not be read") as error:
        person_facts.save_person_fact(bot_id=1, group_id=2, user_id=4, content="new")

    assert "sensitive filesystem detail" not in str(error.value)
    assert path.read_bytes() == before


@pytest.mark.parametrize("failure_stage", ["partial_write", "replace"])
def test_atomic_write_failure_preserves_existing_store(monkeypatch, tmp_path, failure_stage) -> None:
    from pallas.product.llm.memory import person_facts

    path = tmp_path / "person_facts.json"
    path.write_text(json.dumps({"items": [_valid_fact_row()]}), encoding="utf-8")
    before = path.read_bytes()
    monkeypatch.setattr(person_facts, "_store_path", lambda: path)

    if failure_stage == "partial_write":
        original_write_text = Path.write_text

        def fail_mid_write(candidate: Path, text: str, *args, **kwargs):
            if candidate.parent == path.parent and candidate.suffix == ".tmp":
                with candidate.open("w", encoding=kwargs.get("encoding", "utf-8")) as stream:
                    stream.write(text[: max(1, len(text) // 2)])
                raise OSError("simulated interrupted temp write")
            return original_write_text(candidate, text, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", fail_mid_write)
        expected_error = "simulated interrupted temp write"
    else:
        original_replace = Path.replace

        def fail_replace(candidate: Path, target: Path):
            if candidate.parent == path.parent and candidate.suffix == ".tmp":
                raise OSError("simulated replace failure")
            return original_replace(candidate, target)

        monkeypatch.setattr(Path, "replace", fail_replace)
        expected_error = "simulated replace failure"

    with pytest.raises(OSError, match=expected_error):
        person_facts.save_person_fact(bot_id=1, group_id=2, user_id=4, content="new")

    assert path.read_bytes() == before
    assert not list(tmp_path.glob("person_facts.*.tmp"))


def test_batch_projection_noop_frozen_cleanup_and_user_isolation(monkeypatch, tmp_path) -> None:
    from pallas.product.llm.memory import person_facts

    path = tmp_path / "person_facts.json"
    monkeypatch.setattr(person_facts, "_store_path", lambda: path)
    person_facts.save_person_fact(bot_id=1, group_id=2, user_id=10, source="sticker_habit", content="Cat")
    frozen = person_facts.save_person_fact(bot_id=1, group_id=2, user_id=10, source="sticker_habit:2", content="Frozen")
    person_facts.freeze_person_fact(frozen.fact_id)
    person_facts.save_person_fact(bot_id=1, group_id=2, user_id=10, source="sticker_habit:3", content="Cleanup")
    person_facts.save_person_fact(bot_id=1, group_id=2, user_id=10, source="conversation", content="Keep")
    person_facts.save_person_fact(bot_id=1, group_id=2, user_id=20, source="sticker_habit:3", content="Other user")

    created = person_facts.replace_person_facts_by_source_batch(
        bot_id=1,
        group_id=2,
        replacements=[(10, "sticker_habit", "cat", 0.9)],
        forget_sources_by_user={10: ["sticker_habit:2", "sticker_habit:3"]},
    )

    assert created == []
    facts = person_facts.list_person_facts(bot_id=1, group_id=2, status=None)
    by_key = {(fact.user_id, fact.source): fact for fact in facts}
    assert by_key[(10, "sticker_habit")].content == "Cat"
    assert by_key[(10, "sticker_habit")].status == "active"
    assert by_key[(10, "sticker_habit:2")].status == "frozen"
    assert by_key[(10, "sticker_habit:3")].status == "forgotten"
    assert by_key[(10, "conversation")].status == "active"
    assert by_key[(20, "sticker_habit:3")].status == "active"


def test_scope_batch_commits_multiple_groups_with_one_read_and_write(monkeypatch, tmp_path) -> None:
    from pallas.product.llm.memory import person_facts

    path = tmp_path / "person_facts.json"
    monkeypatch.setattr(person_facts, "_store_path", lambda: path)
    existing = person_facts.save_person_fact(
        bot_id=1, group_id=10, user_id=3, source="sticker_habit:2", content="stale"
    )
    original_read = person_facts._read_facts_unlocked
    original_write = person_facts._write_facts_unlocked
    counts = {"read": 0, "write": 0}

    def count_read(store_path):
        counts["read"] += 1
        return original_read(store_path)

    def count_write(facts, store_path):
        counts["write"] += 1
        return original_write(facts, store_path)

    monkeypatch.setattr(person_facts, "_read_facts_unlocked", count_read)
    monkeypatch.setattr(person_facts, "_write_facts_unlocked", count_write)

    created = person_facts.replace_person_facts_by_scope_batch(
        replacements=[
            (1, 10, 3, "sticker_habit", "Cat", 0.8),
            (2, 20, 4, "sticker_habit", "Dog", 0.8),
        ],
        forget_sources_by_scope={(1, 10, 3): ["sticker_habit:2"]},
    )

    assert len(created) == 2
    assert counts == {"read": 1, "write": 1}
    facts = person_facts.list_person_facts(bot_id=None, status=None)
    assert next(fact for fact in facts if fact.fact_id == existing.fact_id).status == "forgotten"


def test_scope_batch_interleaves_safely_with_concurrent_fact_write(monkeypatch, tmp_path) -> None:
    from pallas.product.llm.memory import person_facts

    path = tmp_path / "person_facts.json"
    monkeypatch.setattr(person_facts, "_store_path", lambda: path)
    existing = person_facts.save_person_fact(
        bot_id=1,
        group_id=10,
        user_id=3,
        source="sticker_habit:2",
        content="stale",
    )
    original_read = person_facts._read_facts_unlocked
    batch_read = threading.Event()
    release_batch = threading.Event()
    concurrent_started = threading.Event()
    concurrent_done = threading.Event()
    results: list[list] = []
    errors: list[Exception] = []

    def block_batch_read(store_path):
        if threading.current_thread().name == "scope-fact-batch":
            batch_read.set()
            if not release_batch.wait(timeout=3):
                raise TimeoutError("test batch release timed out")
        return original_read(store_path)

    monkeypatch.setattr(person_facts, "_read_facts_unlocked", block_batch_read)

    def run_batch() -> None:
        try:
            results.append(
                person_facts.replace_person_facts_by_scope_batch(
                    replacements=[
                        (1, 10, 3, "sticker_habit", "Cat", 0.8),
                        (2, 20, 4, "sticker_habit", "Dog", 0.8),
                    ],
                    forget_sources_by_scope={(1, 10, 3): ["sticker_habit:2"]},
                )
            )
        except Exception as exc:
            errors.append(exc)

    def run_concurrent_save() -> None:
        concurrent_started.set()
        try:
            person_facts.save_person_fact(bot_id=3, group_id=30, user_id=5, content="concurrent")
        except Exception as exc:
            errors.append(exc)
        finally:
            concurrent_done.set()

    batch_thread = threading.Thread(target=run_batch, name="scope-fact-batch")
    save_thread = threading.Thread(target=run_concurrent_save, name="concurrent-fact-save")
    batch_thread.start()
    assert batch_read.wait(timeout=2)
    save_thread.start()
    assert concurrent_started.wait(timeout=2)
    assert not concurrent_done.wait(timeout=0.05)
    release_batch.set()
    batch_thread.join(timeout=3)
    save_thread.join(timeout=3)

    assert not batch_thread.is_alive()
    assert not save_thread.is_alive()
    assert errors == []
    assert len(results) == 1
    assert len(results[0]) == 2
    facts = person_facts.list_person_facts(bot_id=None, status=None)
    by_id = {fact.fact_id: fact for fact in facts}
    assert by_id[existing.fact_id].status == "forgotten"
    assert {(fact.group_id, fact.content) for fact in facts if fact.status == "active"} >= {
        (10, "Cat"),
        (20, "Dog"),
        (30, "concurrent"),
    }
