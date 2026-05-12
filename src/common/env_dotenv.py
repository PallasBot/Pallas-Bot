"""项目根 `.env` 读写。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def repo_env_path() -> Path:
    return Path(__file__).resolve().parents[2] / ".env"


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
