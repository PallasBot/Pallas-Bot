from pathlib import Path

from tools.check_fixture_health import check_fixture_health
from tools.check_golden_principles import check_golden_principles


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_fixture_health_clean(tmp_path: Path) -> None:
    _write(
        tmp_path / "harness_command.jsonl",
        '{"journey": "command", "name": "a", "event": {"post_type": "message", "message_type": "group", "user_id": 1, "message_id": 1}, "expect": {"route": "direct", "status": "delivered", "outbound": 1}}\n',
    )
    assert check_fixture_health(tmp_path) == []


def test_fixture_health_reports_issues(tmp_path: Path) -> None:
    _write(
        tmp_path / "harness_command.jsonl",
        '{"journey": "bogus", "name": "a", "event": {"post_type": "message"}}\n'
        '{"journey": "command", "name": "a", "event": {"post_type": "message", "message_type": "group", "user_id": 1, "message_id": 1}}\n'
        "not-json\n",
    )
    errors = check_fixture_health(tmp_path)
    assert any("journey" in e for e in errors)
    assert any("重复" in e for e in errors)
    assert any("JSON 解析失败" in e for e in errors)


def test_fixture_health_ignores_non_harness(tmp_path: Path) -> None:
    _write(tmp_path / "llm_prompt_lab.zh.jsonl", '{"user_text": "x"}\n')
    errors = check_fixture_health(tmp_path)
    assert any("无 harness_*.jsonl" in e for e in errors)


def test_fixture_health_missing_dir(tmp_path: Path) -> None:
    errors = check_fixture_health(tmp_path / "nope")
    assert errors


def test_golden_principles_clean(tmp_path: Path) -> None:
    _write(tmp_path / "developer" / "architecture" / "overview.md", "# 概览\n")
    _write(
        tmp_path / "developer" / "harness" / "index.md",
        "| 主题 | 文档 | Owner | 验证状态 |\n"
        "| --- | --- | --- | --- |\n"
        "| 架构 | [overview](/developer/architecture/overview) | platform | manual |\n",
    )
    assert check_golden_principles(tmp_path, tmp_path / "developer" / "harness" / "index.md") == []


def test_golden_principles_reports_missing_doc_and_owner(tmp_path: Path) -> None:
    _write(
        tmp_path / "developer" / "harness" / "index.md",
        "| 主题 | 文档 | Owner | 验证状态 |\n"
        "| --- | --- | --- | --- |\n"
        "| 架构 | [missing](/developer/architecture/nope) | - | manual |\n",
    )
    errors = check_golden_principles(tmp_path, tmp_path / "developer" / "harness" / "index.md")
    assert any("不存在" in e for e in errors)
    assert any("owner" in e for e in errors)
