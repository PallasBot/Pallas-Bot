from __future__ import annotations

import argparse
import json
from pathlib import Path

import nonebot
from fastapi import FastAPI


def export_console_openapi(*, api_base: str = "/pallas/api") -> dict:
    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()

    from packages.pb_webui.api import register_api
    from packages.pb_webui.config import Config
    from packages.pb_webui.extended_api import build_console_openapi_schema, register_extended_api

    app = FastAPI()
    plugin_config = Config()
    register_api(app, api_base=api_base, extra_meta={})
    register_extended_api(app, api_base=api_base, plugin_config=plugin_config, enable_runtime_hooks=False)
    return build_console_openapi_schema(app, api_base=api_base)


def main() -> int:
    parser = argparse.ArgumentParser(description="导出 Pallas 控制台 OpenAPI schema")
    parser.add_argument(
        "--output",
        default="openspec/pallas-console-v1.json",
        help="输出文件路径，默认 openspec/pallas-console-v1.json",
    )
    parser.add_argument(
        "--api-base",
        default="/pallas/api",
        help="控制台 API 前缀，默认 /pallas/api",
    )
    args = parser.parse_args()

    payload = export_console_openapi(api_base=args.api_base)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
