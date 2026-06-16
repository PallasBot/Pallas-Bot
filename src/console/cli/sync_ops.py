"""uv sync 封装。"""

from __future__ import annotations

import sys

from src.console.webui.extension_install import ExtensionInstallError, run_uv_command, tail_output

SYNC_TIMEOUT_S = 900.0
SYNC_ALIAS_EXTRAS: dict[str, tuple[str, ...]] = {
    "deploy-full": ("deploy-full",),
    "deploy-all": ("deploy-all",),
}


async def sync_dependencies(
    *,
    extras: list[str],
    no_dev: bool = True,
) -> tuple[int, str, str]:
    args: list[str] = ["sync"]
    if no_dev:
        args.append("--no-dev")
    for extra in extras:
        name = (extra or "").strip()
        if not name:
            continue
        args.extend(["--extra", name])
    return await run_uv_command(SYNC_TIMEOUT_S, *args)


def expand_sync_extras(
    extras: list[str],
    *,
    deploy_full: bool = False,
    deploy_all: bool = False,
) -> list[str]:
    out: list[str] = []
    if deploy_full:
        out.extend(SYNC_ALIAS_EXTRAS["deploy-full"])
    if deploy_all:
        out.extend(SYNC_ALIAS_EXTRAS["deploy-all"])
    for item in extras:
        key = (item or "").strip()
        if not key:
            continue
        alias = SYNC_ALIAS_EXTRAS.get(key)
        if alias:
            out.extend(alias)
        else:
            out.append(key)
    seen: set[str] = set()
    ordered: list[str] = []
    for name in out:
        if name in seen:
            continue
        seen.add(name)
        ordered.append(name)
    return ordered


async def run_sync_cli(
    *,
    extras: list[str],
    no_dev: bool,
    deploy_full: bool,
    deploy_all: bool,
) -> int:
    merged = expand_sync_extras(extras, deploy_full=deploy_full, deploy_all=deploy_all)
    try:
        code, out, err = await sync_dependencies(extras=merged, no_dev=no_dev)
    except ExtensionInstallError as e:
        print(e.detail, file=sys.stderr)
        return 1 if e.status_code < 500 else 1
    if code != 0:
        detail = err or out or "(无输出)"
        print(f"uv sync 失败：{tail_output(detail)}", file=sys.stderr)
        return code or 1
    if out.strip():
        print(out)
    print("依赖同步完成。")
    return 0
