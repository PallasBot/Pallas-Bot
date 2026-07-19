"""六星干员 JSON 与头像读写（底层）。"""

from __future__ import annotations

import json
import operator
import urllib.request
from pathlib import Path  # noqa: TC003
from typing import Any

from pallas.core.domain.arknights.skill_text import skill_last_level_plain
from pallas.core.domain.arknights.sources import (
    AVATAR_URL_TEMPLATE,
    MIN_AVATAR_BYTES,
    NATION_CN,
    PAYLOAD_SOURCE,
    PROFESSION_CN,
)
from pallas.core.foundation.paths import resource_dir

ARKNIGHTS_DIR = resource_dir("arknights")
OPERATORS_JSON = ARKNIGHTS_DIR / "operators_6star.json"
OPERATORS_KB_JSON = ARKNIGHTS_DIR / "operators.json"
AVATARS_DIR = ARKNIGHTS_DIR / "avatars"


def avatar_remote_url(char_id: str) -> str:
    return AVATAR_URL_TEMPLATE.format(char_id=char_id)


def avatar_local_path(char_id: str) -> Path:
    return AVATARS_DIR / f"{char_id}.png"


def operator_avatar_bytes(char_id: str) -> bytes | None:
    """本地头像 PNG 二进制。"""
    path = avatar_local_path(char_id)
    if not is_avatar_file_valid(path):
        return None
    try:
        return path.read_bytes()
    except OSError:
        return None


def avatar_relpath(char_id: str) -> str:
    return f"avatars/{char_id}.png"


def fetch_json_sync(url: str, *, timeout: float = 120.0) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "Pallas-Bot-ark-sync/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not isinstance(data, dict):
        msg = f"expected JSON object from {url}"
        raise TypeError(msg)
    return data


def skill_name_and_desc_m3(skill_table: dict[str, Any], skill_id: str) -> tuple[str, str]:
    info = skill_table.get(skill_id)
    if not info or not isinstance(info, dict):
        return "", ""
    levels = info.get("levels")
    if not isinstance(levels, list) or not levels:
        return "", ""
    last = levels[-1]
    if not isinstance(last, dict):
        return "", ""
    name = str(last.get("name", "") or "")
    desc = skill_last_level_plain(info, max_len=240)
    return name, desc


def build_operators_payload(
    char_table: dict[str, Any],
    skill_table: dict[str, Any],
    *,
    rarity_filter: str | None = "TIER_6",
) -> dict[str, Any]:
    operators: list[dict[str, Any]] = []
    for char_id, row in char_table.items():
        if not isinstance(row, dict):
            continue
        if not str(char_id).startswith("char_"):
            continue
        rarity = str(row.get("rarity") or "")
        if rarity_filter is not None and rarity != rarity_filter:
            continue
        name = row.get("name")
        if not name or not isinstance(name, str):
            continue
        prof = str(row.get("profession", "WARRIOR"))
        if prof == "TOKEN":
            continue
        sub_prof = str(row.get("subProfessionId") or "")
        skills_raw = row.get("skills")
        skills_out: list[dict[str, str]] = []
        if isinstance(skills_raw, list):
            for slot in skills_raw[:3]:
                if not isinstance(slot, dict):
                    continue
                sid = slot.get("skillId")
                if not sid:
                    continue
                sn, sd = skill_name_and_desc_m3(skill_table, str(sid))
                skills_out.append({"skill_id": str(sid), "name": sn, "description": sd})

        cid = str(char_id)
        nation_id = str(row.get("nationId") or "").strip()
        tags_raw = row.get("tagList") if isinstance(row.get("tagList"), list) else []
        operators.append({
            "id": cid,
            "name": name.strip(),
            "rarity": rarity,
            "profession": prof,
            "profession_cn": PROFESSION_CN.get(prof, prof),
            "sub_profession_id": sub_prof,
            "nation_id": nation_id,
            "nation_cn": NATION_CN.get(nation_id, ""),
            "display_number": str(row.get("displayNumber") or "").strip(),
            "item_desc": str(row.get("itemDesc") or "").strip(),
            "item_usage": str(row.get("itemUsage") or "").strip(),
            "tags": [str(tag).strip() for tag in tags_raw if str(tag).strip()][:8],
            "skills": skills_out,
            "avatar_relpath": avatar_relpath(cid),
            "avatar_url": avatar_remote_url(cid),
        })

    operators.sort(key=operator.itemgetter("id"))
    rarity_label = rarity_filter or "ALL"
    return {
        "source": PAYLOAD_SOURCE,
        "rarity_filter": rarity_label,
        "count": len(operators),
        "operators": operators,
    }


def write_operators_json(payload: dict[str, Any], path: Path | None = None) -> Path:
    dest = path or OPERATORS_JSON
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return dest


def operator_ids_from_payload(payload: dict[str, Any]) -> list[str]:
    ops = payload.get("operators")
    if not isinstance(ops, list):
        return []
    return [str(op["id"]) for op in ops if isinstance(op, dict) and op.get("id")]


def load_operators_payload(path: Path | None = None) -> dict[str, Any] | None:
    dest = path or OPERATORS_JSON
    if not dest.is_file():
        return None
    try:
        data = json.loads(dest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def load_kb_operators_payload() -> dict[str, Any] | None:
    """知识库优先读全量 operators.json，回退六星表。"""
    payload = load_operators_payload(OPERATORS_KB_JSON)
    if payload:
        return payload
    return load_operators_payload(OPERATORS_JSON)


def is_avatar_file_valid(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size >= MIN_AVATAR_BYTES
    except OSError:
        return False


def count_valid_avatars(operator_ids: list[str]) -> int:
    return sum(1 for cid in operator_ids if is_avatar_file_valid(avatar_local_path(cid)))


def download_avatar_sync(char_id: str, dest: Path | None = None) -> bool:
    out = dest or avatar_local_path(char_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    url = avatar_remote_url(char_id)
    req = urllib.request.Request(url, headers={"User-Agent": "Pallas-Bot-ark-sync/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
    except OSError:
        return False
    if len(data) < MIN_AVATAR_BYTES:
        return False
    out.write_bytes(data)
    return True


def sync_avatars_sync(
    operator_ids: list[str],
    *,
    missing_only: bool = True,
) -> tuple[int, int]:
    """返回 (成功数, 尝试数)。"""
    tried = 0
    ok = 0
    for cid in operator_ids:
        dest = avatar_local_path(cid)
        if missing_only and is_avatar_file_valid(dest):
            continue
        tried += 1
        if download_avatar_sync(cid, dest):
            ok += 1
    return ok, tried
