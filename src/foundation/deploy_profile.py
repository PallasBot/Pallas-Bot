"""可选部署模板：uv extra 与落盘标记。"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path  # noqa: TC003
from typing import Any

from src.foundation.paths import DATA_ROOT, PROJECT_ROOT

DEPLOY_DIR = PROJECT_ROOT / "deploy"
DEPLOY_MARKER_PATH = DATA_ROOT / "pallas_config" / "deploy_profiles.json"


@dataclass(frozen=True)
class DeployProfileSpec:
    id: str
    title: str
    description: str
    uv_extras: tuple[str, ...]
    fragment_relpath: str | None


DEPLOY_PROFILES: dict[str, DeployProfileSpec] = {
    "default": DeployProfileSpec(
        id="default",
        title="单进程（默认）",
        description="``bot.py`` / ``nb run``；不启用分片与 message_scrub 模板。",
        uv_extras=(),
        fragment_relpath=None,
    ),
    "shard": DeployProfileSpec(
        id="shard",
        title="多进程分片",
        description="hub + worker；推荐 ``uv sync --extra deploy-shard`` 并配合 ``run_sharded_bot.sh``。",
        uv_extras=("deploy-shard",),
        fragment_relpath="shard/pallas.fragment.toml",
    ),
    "message-scrub": DeployProfileSpec(
        id="message-scrub",
        title="消息审查",
        description="启用 ``PALLAS_MESSAGE_SCRUB_ENABLED``；``uv sync --extra message-scrub``。",
        uv_extras=("message-scrub",),
        fragment_relpath="message-scrub/pallas.fragment.toml",
    ),
}


def deploy_marker_path() -> Path:
    return DEPLOY_MARKER_PATH


def clear_deploy_profile_cache() -> None:
    load_deploy_marker.cache_clear()


@lru_cache(maxsize=1)
def load_deploy_marker() -> dict[str, Any]:
    path = deploy_marker_path()
    if not path.is_file():
        return {"profiles": [], "extras": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"profiles": [], "extras": []}
    profiles = raw.get("profiles")
    extras = raw.get("extras")
    return {
        "profiles": [str(x) for x in profiles] if isinstance(profiles, list) else [],
        "extras": [str(x) for x in extras] if isinstance(extras, list) else [],
        "applied_at": raw.get("applied_at"),
    }


def is_deploy_profile_active(profile_id: str) -> bool:
    return profile_id in load_deploy_marker().get("profiles", [])


def list_deploy_profile_specs() -> list[DeployProfileSpec]:
    return list(DEPLOY_PROFILES.values())


def get_deploy_profile_spec(profile_id: str) -> DeployProfileSpec:
    spec = DEPLOY_PROFILES.get(profile_id)
    if spec is None:
        known = ", ".join(sorted(DEPLOY_PROFILES))
        raise ValueError(f"未知部署模板: {profile_id!r}（可选: {known}）")
    return spec


def profile_fragment_path(profile_id: str) -> Path | None:
    spec = get_deploy_profile_spec(profile_id)
    if not spec.fragment_relpath:
        return None
    return DEPLOY_DIR / spec.fragment_relpath


def read_profile_env_fragment(profile_id: str) -> dict[str, str]:
    path = profile_fragment_path(profile_id)
    if path is None or not path.is_file():
        return {}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    env = data.get("env")
    if not isinstance(env, dict):
        return {}
    out: dict[str, str] = {}
    for key, val in env.items():
        if val is None:
            continue
        if isinstance(val, bool):
            out[str(key).upper()] = "true" if val else "false"
        else:
            out[str(key).upper()] = str(val).strip()
    return out


def record_deploy_profile(profile_id: str) -> dict[str, Any]:
    spec = get_deploy_profile_spec(profile_id)
    path = deploy_marker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = load_deploy_marker()
    profiles = sorted(set(current.get("profiles", [])) | {profile_id})
    extras = sorted(set(current.get("extras", [])) | set(spec.uv_extras))
    payload = {
        "profiles": profiles,
        "extras": extras,
        "applied_at": datetime.now(UTC).isoformat(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    clear_deploy_profile_cache()
    return payload


def merge_profile_env_into_webui(env_patch: dict[str, str]) -> Path:
    from src.foundation.config.repo_settings import repo_webui_settings_path

    path = repo_webui_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {"env": {}}
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
    env = data.setdefault("env", {})
    if not isinstance(env, dict):
        env = {}
        data["env"] = env
    env.update(env_patch)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def message_scrub_webui_available() -> bool:
    if is_deploy_profile_active("message-scrub"):
        return True
    from src.features.message_scrub.config import is_message_scrub_enabled

    return is_message_scrub_enabled()


def uv_sync_hint_for_profile(profile_id: str) -> str:
    spec = get_deploy_profile_spec(profile_id)
    if not spec.uv_extras:
        return "uv sync"
    extras = " --extra ".join(spec.uv_extras)
    return f"uv sync --extra {extras}"
