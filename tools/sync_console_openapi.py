#!/usr/bin/env python3
"""导出控制台 OpenAPI；若存在同级 WebUI 仓则同步生成 TS 类型。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from tools.export_pb_webui_openapi import export_console_openapi, openapi_for_compare

DEFAULT_SPEC = Path("openspec/pallas-console-v1.json")
WEBUI_TYPES = Path("src/api/generated/pallasConsoleOpenapi.ts")


def bot_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_webui_root(explicit: str = "") -> Path | None:
    candidates: list[Path] = []
    if explicit.strip():
        candidates.append(Path(explicit).expanduser().resolve())
    env = (os.environ.get("PALLAS_WEBUI_ROOT") or "").strip()
    if env:
        candidates.append(Path(env).expanduser().resolve())
    candidates.append((bot_root().parent / "Pallas-Bot-WebUI").resolve())
    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        if (path / "package.json").is_file():
            return path
    return None


def write_openspec_if_needed(spec_path: Path, *, api_base: str) -> bool:
    """写入 openspec；仅在忽略 version 后仍有差异时落盘。返回是否改写了文件。"""
    live = export_console_openapi(api_base=api_base)
    if spec_path.is_file():
        committed = json.loads(spec_path.read_text(encoding="utf-8"))
        if openapi_for_compare(committed) == openapi_for_compare(live):
            print(f"[sync-console-openapi] openspec unchanged: {spec_path}")
            return False
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(json.dumps(live, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[sync-console-openapi] openspec updated: {spec_path}")
    return True


def sync_webui_types(webui_root: Path, spec_path: Path) -> bool | None:
    """生成 WebUI 类型。True=有改动，False=无改动，None=跳过。"""
    cli = webui_root / "node_modules" / "openapi-typescript" / "bin" / "cli.js"
    if not cli.is_file():
        print(
            f"[sync-console-openapi] skip WebUI types: missing deps at {webui_root} (run npm ci there)",
            file=sys.stderr,
        )
        return None

    types_path = webui_root / WEBUI_TYPES
    before = types_path.read_text(encoding="utf-8") if types_path.is_file() else None
    abs_spec = spec_path if spec_path.is_absolute() else (bot_root() / spec_path)
    proc = subprocess.run(
        ["npm", "run", "gen:console-openapi-types", "--", "--input", str(abs_spec)],
        cwd=webui_root,
        check=False,
    )
    if proc.returncode != 0:
        print("[sync-console-openapi] WebUI gen:console-openapi-types failed", file=sys.stderr)
        return None

    after = types_path.read_text(encoding="utf-8") if types_path.is_file() else ""
    if before == after:
        print(f"[sync-console-openapi] WebUI types unchanged: {types_path}")
        return False

    print(f"[sync-console-openapi] WebUI types updated: {types_path}")
    print(
        "[sync-console-openapi] 请在 WebUI 仓另行提交生成文件 "
        f"（建议：cd {webui_root} && git add {WEBUI_TYPES.as_posix()} && git commit）",
        file=sys.stderr,
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="同步控制台 OpenAPI（Bot openspec + 可选 WebUI 类型）")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_SPEC),
        help="Bot openspec 路径，默认 openspec/pallas-console-v1.json",
    )
    parser.add_argument("--api-base", default="/pallas/api", help="控制台 API 前缀")
    parser.add_argument(
        "--webui-root",
        default="",
        help="WebUI 仓路径；默认读 PALLAS_WEBUI_ROOT 或同级 ../Pallas-Bot-WebUI",
    )
    parser.add_argument(
        "--skip-webui",
        action="store_true",
        help="只导出 Bot openspec，不同步 WebUI",
    )
    parser.add_argument(
        "--require-webui",
        action="store_true",
        help="找不到 WebUI 仓或无法生成类型时失败（默认仅警告）",
    )
    parser.add_argument(
        "--pre-commit",
        action="store_true",
        help="pre-commit 模式：openspec 有改动时 exit 1 以便重新 stage",
    )
    args = parser.parse_args()

    os.chdir(bot_root())
    spec_path = Path(args.output)
    openspec_changed = write_openspec_if_needed(spec_path, api_base=args.api_base)

    webui_touched: bool | None = False
    if not args.skip_webui:
        webui = resolve_webui_root(args.webui_root)
        if webui is None:
            msg = (
                "[sync-console-openapi] no WebUI checkout found "
                "(set PALLAS_WEBUI_ROOT or clone sibling Pallas-Bot-WebUI)"
            )
            if args.require_webui:
                print(msg, file=sys.stderr)
                return 1
            print(msg)
        else:
            webui_touched = sync_webui_types(webui, spec_path)
            if webui_touched is None and args.require_webui:
                return 1

    if args.pre_commit and openspec_changed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
