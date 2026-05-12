"""项目根 `.env` 读写。"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


def repo_env_path() -> Path:
    return Path(__file__).resolve().parents[2] / ".env"


def nonebot_repo_dotenv_environment() -> str:
    """与 NoneBot ``Env.environment`` 默认一致，用于定位 ``.env.{name}``。"""
    raw = os.environ.get("ENVIRONMENT") or os.environ.get("environment") or "prod"
    s = str(raw).strip()
    return s or "prod"


def repo_layered_dotenv_files_exist() -> bool:
    """仓库根是否存在 ``.env`` 或 ``.env.{ENVIRONMENT}``（与 NoneBot ``init`` 加载组合对齐）。"""
    root = repo_env_path()
    layered = root.parent / f".env.{nonebot_repo_dotenv_environment()}"
    return root.is_file() or layered.is_file()


def merged_repo_dotenv_upper() -> dict[str, str]:
    """合并项目根 ``.env`` 与 ``.env.{ENVIRONMENT}``（后者覆盖前者），键名为大写。

    每次调用都会重新读盘，供 message_scrub 等在热重载后对齐磁盘上的注释/删除。
    """
    from dotenv import dotenv_values

    root = repo_env_path()
    env_name = nonebot_repo_dotenv_environment()
    layered = root.parent / f".env.{env_name}"
    merged: dict[str, str] = {}
    if root.is_file():
        for k, v in (dotenv_values(root) or {}).items():
            if not k:
                continue
            merged[str(k).upper()] = "" if v is None else str(v)
    if layered.is_file():
        for k, v in (dotenv_values(layered) or {}).items():
            if not k:
                continue
            merged[str(k).upper()] = "" if v is None else str(v)
    return merged


def env_value_to_str(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    if v is None:
        return ""
    return str(v)


def upsert_env_dotenv_items(items: dict[str, str]) -> None:
    path = repo_env_path()
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    else:
        lines = []
    remained = set(items.keys())
    out: list[str] = []
    for line in lines:
        replaced = False
        for k, v in items.items():
            if re.match(rf"^\s*#?\s*{re.escape(k)}\s*=", line):
                out.append(f"{k}={v}")
                remained.discard(k)
                replaced = True
                break
        if not replaced:
            out.append(line)
    if remained:
        if out and out[-1].strip() != "":
            out.append("")
        out.extend(f"{k}={items[k]}" for k in sorted(remained))
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
