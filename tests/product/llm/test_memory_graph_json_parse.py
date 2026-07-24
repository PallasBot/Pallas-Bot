"""parse_llm_json 单测。"""

import json

import pytest

from pallas.product.llm.memory.graph.json_parse import parse_llm_json


def test_plain_object() -> None:
    assert parse_llm_json('{"a": 1, "b": "x"}') == {"a": 1, "b": "x"}


def test_plain_array() -> None:
    assert parse_llm_json("[1, 2, 3]") == [1, 2, 3]


def test_markdown_fence_json() -> None:
    raw = '```json\n{"entities": [], "edges": []}\n```'
    assert parse_llm_json(raw) == {"entities": [], "edges": []}


def test_markdown_fence_bare() -> None:
    raw = '```\n{"n": "咖啡"}\n```'
    assert parse_llm_json(raw) == {"n": "咖啡"}


def test_prose_around_json() -> None:
    raw = '结果如下：\n{"entities":[{"n":"小明"}],"edges":[]}\n以上。'
    assert parse_llm_json(raw) == {"entities": [{"n": "小明"}], "edges": []}


def test_nested_and_brace_in_string() -> None:
    assert parse_llm_json('{"a": {"b": 1}, "msg": "a}b"}') == {"a": {"b": 1}, "msg": "a}b"}


def test_trailing_comma_repaired() -> None:
    assert parse_llm_json('{"a": 1, "b": 2,}') == {"a": 1, "b": 2}


def test_empty_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        parse_llm_json("   ")


def test_prose_without_json_raises() -> None:
    with pytest.raises(ValueError, match="failed to parse"):
        parse_llm_json("没有 JSON 内容")


def test_unicode_roundtrip() -> None:
    raw = '{"msg": "你好世界"}'
    result = parse_llm_json(raw)
    assert isinstance(result, dict)
    assert result["msg"] == "你好世界"
    assert json.loads(json.dumps(result, ensure_ascii=False)) == result
