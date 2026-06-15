#!/usr/bin/env python3
"""单进程 unified → 分片：恢复配置并同步 worker 端口（回滚测试用）。"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PALLAS_TOML = REPO_ROOT / "config/pallas.toml"
WEBUI_PATH = REPO_ROOT / "data/pallas_config/webui.json"
UNIFIED_SCRIPT = REPO_ROOT / "scripts/run_unified_bot.sh"
SHARD_SCRIPT = REPO_ROOT / "scripts/run_sharded_bot.sh"
SYNC_SCRIPT = REPO_ROOT / "scripts/sync_shard_protocol_ports.py"


def set_shard_enabled(enabled: bool) -> None:
    value = "true" if enabled else "false"
    if PALLAS_TOML.is_file():
        text = PALLAS_TOML.read_text(encoding="utf-8")
        if "PALLAS_SHARD_ENABLED" in text:
            text = re.sub(
                r'(PALLAS_SHARD_ENABLED\s*=\s*)"?(?:true|false)"?',
                rf'\1"{value}"',
                text,
                count=1,
            )
        else:
            text = text.rstrip() + f'\nPALLAS_SHARD_ENABLED = "{value}"\n'
        PALLAS_TOML.write_text(text, encoding="utf-8")

    if WEBUI_PATH.is_file():
        data = json.loads(WEBUI_PATH.read_text(encoding="utf-8"))
        env = data.get("env")
        if isinstance(env, dict):
            env["PALLAS_SHARD_ENABLED"] = value
        sections = data.get("sections")
        if isinstance(sections, dict):
            for section in sections.values():
                if isinstance(section, dict) and "PALLAS_SHARD_ENABLED" in section:
                    section["PALLAS_SHARD_ENABLED"] = value
        WEBUI_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-stop", action="store_true", help="不停止 unified 进程")
    parser.add_argument("--start", action="store_true", help="同步后执行 run_sharded_bot.sh start")
    args = parser.parse_args()

    if not args.skip_stop and UNIFIED_SCRIPT.is_file():
        subprocess.run([str(UNIFIED_SCRIPT), "stop"], cwd=REPO_ROOT, check=False)

    print("写入 PALLAS_SHARD_ENABLED=true …")
    set_shard_enabled(True)

    if SYNC_SCRIPT.is_file():
        proc = subprocess.run([sys.executable, str(SYNC_SCRIPT)], cwd=REPO_ROOT, check=False)
        if proc.returncode != 0:
            return proc.returncode

    print("\n下一步:")
    print("  1. 在协议端控制台对变更账号执行「重启」")
    if args.start and SHARD_SCRIPT.is_file():
        print("  2. 正在启动分片…")
        return subprocess.run([str(SHARD_SCRIPT), "start"], cwd=REPO_ROOT).returncode
    print("  2. ./scripts/run_sharded_bot.sh start")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
