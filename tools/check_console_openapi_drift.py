#!/usr/bin/env python3
"""校验 openspec/pallas-console-v1.json 与当前代码导出一致。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tools.export_pb_webui_openapi import export_console_openapi, openapi_for_compare


def main() -> int:
    spec_path = Path("openspec/pallas-console-v1.json")
    if not spec_path.is_file():
        print(f"missing committed spec: {spec_path}", file=sys.stderr)
        return 1

    committed = json.loads(spec_path.read_text(encoding="utf-8"))
    live = export_console_openapi(api_base="/pallas/api")
    if openapi_for_compare(committed) == openapi_for_compare(live):
        print("console OpenAPI spec is up to date")
        return 0

    print("console OpenAPI drift detected: re-run", file=sys.stderr)
    print("  uv run python tools/sync_console_openapi.py", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
