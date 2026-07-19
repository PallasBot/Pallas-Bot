#!/usr/bin/env python3
"""校验 openspec/pallas-console-v1.json 与当前代码导出一致。"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

from tools.export_pb_webui_openapi import export_console_openapi


def _for_compare(spec: dict[str, Any]) -> dict[str, Any]:
    """忽略随 git describe 变动的 info.version，避免每次提交后假漂移。"""
    data = copy.deepcopy(spec)
    info = data.get("info")
    if isinstance(info, dict):
        info.pop("version", None)
    return data


def main() -> int:
    spec_path = Path("openspec/pallas-console-v1.json")
    if not spec_path.is_file():
        print(f"missing committed spec: {spec_path}", file=sys.stderr)
        return 1

    committed = json.loads(spec_path.read_text(encoding="utf-8"))
    live = export_console_openapi(api_base="/pallas/api")
    if _for_compare(committed) == _for_compare(live):
        print("console OpenAPI spec is up to date")
        return 0

    print("console OpenAPI drift detected: re-run", file=sys.stderr)
    print("  uv run python tools/export_pb_webui_openapi.py", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
