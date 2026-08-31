#!/usr/bin/env python3
"""fixture 失效扫描：检查行为实验室 fixture 的结构健康度。

阶段 4「持续治理」的 fixture 健康扫描。扫描 ``tools/fixtures/*.jsonl``，
校验每行 JSON 可解析、字段结构符合 ``llm_event_harness`` 契约、case 名唯一、
journey 合法、expect 字段类型正确，并报告问题与修复方向。

只做静态结构检查，不运行事件（运行验证由 ``llm_event_harness.py`` 负责）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tools" / "fixtures"

VALID_JOURNEYS = {"command", "matcher", "llm"}
REQUIRED_EVENT_KEYS = {"post_type", "message_type", "user_id", "message_id"}
EXPECT_KEYS = {"route", "status", "outbound"}


def _check_fixture_file(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [f"{path.name}: 无法读取：{exc}"]
    seen_names: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{path.name}:{line_number} JSON 解析失败：{exc}")
            continue
        if not isinstance(raw, dict):
            errors.append(f"{path.name}:{line_number} 必须是 JSON 对象")
            continue
        name = raw.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"{path.name}:{line_number} 缺少非空 name")
        elif name in seen_names:
            errors.append(f"{path.name}:{line_number} case 名重复 [{name}]")
        else:
            seen_names.add(name)
        journey = raw.get("journey", "llm")
        if journey not in VALID_JOURNEYS:
            errors.append(f"{path.name}:{line_number} journey [{journey}] 非法（应为 {sorted(VALID_JOURNEYS)}）")
        event = raw.get("event")
        if not isinstance(event, dict):
            errors.append(f"{path.name}:{line_number} event 必须是对象")
        else:
            errors.extend(
                f"{path.name}:{line_number} event 缺少必需字段 [{key}]"
                for key in REQUIRED_EVENT_KEYS
                if key not in event
            )
        expect = raw.get("expect")
        if expect is not None:
            if not isinstance(expect, dict):
                errors.append(f"{path.name}:{line_number} expect 必须是对象")
            else:
                errors.extend(
                    f"{path.name}:{line_number} expect 含未知字段 [{key}]" for key in expect if key not in EXPECT_KEYS
                )
    return errors


def check_fixture_health(fixtures_dir: Path) -> list[str]:
    errors: list[str] = []
    if not fixtures_dir.is_dir():
        return [f"fixtures 目录不存在：{fixtures_dir}"]
    files = sorted(fixtures_dir.glob("harness_*.jsonl"))
    if not files:
        return [f"fixtures 目录无 harness_*.jsonl 文件：{fixtures_dir}"]
    for path in files:
        errors.extend(_check_fixture_file(path))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="检查行为实验室 fixture 结构健康度。")
    parser.add_argument("--fixtures", type=Path, default=FIXTURES, help="fixtures 目录。")
    args = parser.parse_args()

    errors = check_fixture_health(args.fixtures)
    if errors:
        print("fixture 健康扫描未通过：", file=sys.stderr)
        for item in errors:
            print(f"  ✗ {item}", file=sys.stderr)
        print("修复方向：修正 JSON 结构、补全必需字段、保证 case 名唯一。", file=sys.stderr)
        return 1

    print("✓ fixture 健康扫描通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
