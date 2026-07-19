"""部署模板应用。"""

from __future__ import annotations

import sys

from pallas.core.foundation.config.repo_settings import repo_config_path
from pallas.core.foundation.deploy_profile import (
    DEPLOY_PROFILES,
    merge_profile_env_into_webui,
    read_profile_env_fragment,
    record_deploy_profile,
    uv_sync_hint_for_profile,
)
from pallas.core.foundation.paths import PROJECT_ROOT


def apply_deploy_profile(profile: str, *, dry_run: bool = False) -> int:
    name = (profile or "").strip()
    if name not in DEPLOY_PROFILES:
        print(f"未知模板 {name!r}，可选：{', '.join(sorted(DEPLOY_PROFILES))}", file=sys.stderr)
        return 1

    if name == "default":
        print("default 模板无需应用；直接使用 uv sync 与 bot.py 即可。")
        return 0

    if not repo_config_path().is_file():
        print(
            "未找到 config/pallas.toml。请先: cp config/pallas.example.toml config/pallas.toml",
            file=sys.stderr,
        )
        return 1

    env_patch = read_profile_env_fragment(name)
    if not env_patch:
        print(f"模板 {name!r} 无 env 片段可合并。", file=sys.stderr)
        return 1

    hint = uv_sync_hint_for_profile(name)
    print(f"建议依赖: {hint}")
    print(f"将合并 {len(env_patch)} 个 env 键到 data/pallas_config/webui.json")

    if dry_run:
        for k in sorted(env_patch):
            print(f"  {k}={env_patch[k]!r}")
        return 0

    webui_path = merge_profile_env_into_webui(env_patch)
    marker = record_deploy_profile(name)
    print(f"已写入 {webui_path.relative_to(PROJECT_ROOT)}")
    print(f"已记录 {marker['profiles']}（extras: {marker['extras']}）")

    if name == "shard":
        print("下一步: pallas run shard  或  ./scripts/run_sharded_bot.sh start")
    return 0
