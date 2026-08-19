from __future__ import annotations

import pytest

from pallas.product.llm.memory.auto_ip_knowledge import (
    _fact_to_content,
    _parse_facts,
    _transcript,
    auto_ip_status_snapshot,
    clear_auto_ip_cooldown_for_tests,
)


def test_parse_facts_handles_json_array() -> None:
    facts = _parse_facts('[{"ip":"鸣潮","fact":"声骸可镶嵌","keywords":"声骸,镶嵌"}]')
    assert facts == [{"ip": "鸣潮", "fact": "声骸可镶嵌", "keywords": "声骸,镶嵌"}]


def test_parse_facts_empty_array_returns_empty() -> None:
    assert _parse_facts("[]") == []
    assert _parse_facts("") == []


def test_parse_facts_strips_code_fence() -> None:
    facts = _parse_facts('```json\n[{"ip":"方舟","fact":"剿灭是周常","keywords":"剿灭,周常"}]\n```')
    assert len(facts) == 1
    assert facts[0]["ip"] == "方舟"


def test_parse_facts_ignores_missing_fields() -> None:
    facts = _parse_facts('[{"ip":"鸣潮","fact":"有IP有fact无keywords"}]')
    assert len(facts) == 1
    assert facts[0]["keywords"] == ""
    facts = _parse_facts('[{"fact":"没有IP"}]')
    assert facts == []
    facts = _parse_facts('[{"ip":"只有IP"}]')
    assert facts == []


def test_parse_facts_indented_multiline() -> None:
    raw = '[\n  {"ip": "A", "fact": "f1", "keywords": "k1"},\n  {"ip": "B", "fact": "f2", "keywords": "k2"}\n]'
    assert len(_parse_facts(raw)) == 2


def test_fact_to_content_formats_with_keywords() -> None:
    item = {"ip": "鸣潮", "fact": "声骸可镶嵌", "keywords": "声骸,镶嵌"}
    assert _fact_to_content(item) == "【鸣潮】声骸可镶嵌（关键词：声骸,镶嵌）"


def test_fact_to_content_omits_empty_keywords() -> None:
    item = {"ip": "鸣潮", "fact": "声骸可镶嵌", "keywords": ""}
    assert _fact_to_content(item) == "【鸣潮】声骸可镶嵌"


def test_transcript_requires_two_participants_and_three_turns() -> None:
    from types import SimpleNamespace

    single = [
        SimpleNamespace(role="user", user_id=1, content="a"),
        SimpleNamespace(role="user", user_id=1, content="b"),
        SimpleNamespace(role="user", user_id=1, content="c"),
    ]
    assert _transcript(single) == ""

    multi = [
        SimpleNamespace(role="user", user_id=1, content="a"),
        SimpleNamespace(role="user", user_id=2, content="b"),
        SimpleNamespace(role="user", user_id=1, content="c"),
        SimpleNamespace(role="assistant", user_id=0, content="bot"),
    ]
    out = _transcript(multi)
    assert "bot" not in out
    assert "a" in out
    assert "b" in out


def test_status_snapshot_and_clear() -> None:
    clear_auto_ip_cooldown_for_tests()
    snapshot = auto_ip_status_snapshot()
    assert snapshot["tracked_groups"] == 0
    assert snapshot["in_flight"] == 0


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"ip":"鸣潮","fact":"f","keywords":"k"}', 1),
        ("[invalid json", 0),
        ("无", 0),
    ],
)
def test_parse_facts_parametrized(text: str, expected: int) -> None:
    assert len(_parse_facts(text)) == expected
