"""版本化基础提示词覆盖资产：append/replace 模式 + 最多 10 个历史版本，落盘于 pb_webui 插件数据目录。"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import TYPE_CHECKING

from nonebot import logger
from pydantic import BaseModel, Field

from pallas.core.foundation.fs_lock import atomic_write_text, interprocess_file_lock
from pallas.core.foundation.paths import plugin_data_dir
from pallas.product.persona.compile_persona_prompt import clear_base_system_prompt_cache

if TYPE_CHECKING:
    from pathlib import Path

_APPEND = "append"
_REPLACE = "replace"
_MAX_VERSIONS = 10


class BasePromptOverrideVersion(BaseModel):
    id: str
    mode: str
    text: str
    builtin_sha256: str = ""
    updated_at: str = ""


class BasePromptOverride(BaseModel):
    enabled: bool = False
    mode: str = _APPEND
    text: str = ""
    builtin_sha256: str = ""
    updated_at: str = ""
    versions: list[BasePromptOverrideVersion] = Field(default_factory=list)


def base_prompt_override_path() -> Path:
    return plugin_data_dir("pb_webui") / "base_prompt_override.json"


def base_prompt_override_lock_path() -> Path:
    return base_prompt_override_path().with_suffix(".lock")


def _sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()


def _current_builtin_sha256() -> str:
    from pallas.product.persona.compile_persona_prompt import resolve_base_system_prompt_path

    path = resolve_base_system_prompt_path()
    try:
        return _sha256_text(path.read_text(encoding="utf-8"))
    except OSError:
        return ""


def load_base_prompt_override() -> BasePromptOverride | None:
    """读取覆盖资产；缺失或损坏时返回 None（内部使用）。"""
    try:
        raw = json.loads(base_prompt_override_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    try:
        return BasePromptOverride.model_validate(raw)
    except (ValueError, TypeError):
        return None


def base_prompt_override_status() -> dict:
    asset = load_base_prompt_override()
    current_sha = _current_builtin_sha256()
    if asset is None:
        return {
            "enabled": False,
            "mode": _APPEND,
            "text": "",
            "builtin_sha256": current_sha,
            "builtin_updated": False,
            "updated_at": "",
            "versions": [],
        }
    stored = (asset.builtin_sha256 or "").strip()
    builtin_updated = (not stored) or stored != current_sha
    return {
        "enabled": asset.enabled,
        "mode": asset.mode,
        "text": asset.text,
        "builtin_sha256": asset.builtin_sha256,
        "builtin_updated": builtin_updated,
        "updated_at": asset.updated_at,
        "versions": [version.model_dump() for version in asset.versions],
    }


def save_base_prompt_override(*, mode: str, text: str, builtin_text: str) -> dict:
    """保存覆盖资产；enabled 置 True，记录内置基线哈希并归档历史版本，返回最新状态。

    builtin_sha256 始终锚定内置基线文件，builtin_text 仅作参考。
    """
    mode = _REPLACE if mode == _REPLACE else _APPEND
    text = (text or "").strip()
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    sha = _current_builtin_sha256()
    with interprocess_file_lock(base_prompt_override_lock_path()):
        asset = load_base_prompt_override() or BasePromptOverride()
        asset.enabled = True
        asset.mode = mode
        asset.text = text
        asset.builtin_sha256 = sha
        asset.updated_at = now
        if text and (not asset.versions or asset.versions[0].text != text or asset.versions[0].mode != mode):
            asset.versions.insert(
                0,
                BasePromptOverrideVersion(
                    id=uuid.uuid4().hex[:12],
                    mode=mode,
                    text=text,
                    builtin_sha256=sha,
                    updated_at=now,
                ),
            )
        asset.versions = asset.versions[:_MAX_VERSIONS]
        atomic_write_text(base_prompt_override_path(), asset.model_dump_json(indent=2))
    clear_base_system_prompt_cache()
    logger.info("基础提示词覆盖已保存，模式为 [{}]", mode)
    return base_prompt_override_status()


def restore_base_prompt_override(*, version_id: str) -> dict:
    """将历史版本恢复为当前覆盖；版本号不存在时抛 KeyError。"""
    with interprocess_file_lock(base_prompt_override_lock_path()):
        asset = load_base_prompt_override()
        if asset is None:
            raise KeyError(version_id)
        target = next((version for version in asset.versions if version.id == version_id), None)
        if target is None:
            raise KeyError(version_id)
        asset.enabled = True
        asset.mode = target.mode
        asset.text = target.text
        asset.builtin_sha256 = target.builtin_sha256
        asset.updated_at = target.updated_at
        atomic_write_text(base_prompt_override_path(), asset.model_dump_json(indent=2))
    clear_base_system_prompt_cache()
    logger.info("基础提示词覆盖已恢复到历史版本 [{}]", version_id)
    return base_prompt_override_status()


def set_base_prompt_override_enabled(*, enabled: bool) -> dict:
    with interprocess_file_lock(base_prompt_override_lock_path()):
        asset = load_base_prompt_override()
        if asset is None:
            return base_prompt_override_status()
        asset.enabled = bool(enabled)
        atomic_write_text(base_prompt_override_path(), asset.model_dump_json(indent=2))
    clear_base_system_prompt_cache()
    logger.info("基础提示词覆盖启用状态已设置为 [{}]", asset.enabled)
    return base_prompt_override_status()


def clear_base_prompt_override() -> None:
    with interprocess_file_lock(base_prompt_override_lock_path()):
        try:
            base_prompt_override_path().unlink(missing_ok=True)
        except OSError:
            pass
    clear_base_system_prompt_cache()
    logger.info("基础提示词覆盖已清除")


def resolve_base_prompt(*, builtin_text: str) -> str:
    """按覆盖资产应用模式：append 追加到基线，replace 全量替换；禁用或缺失时返回原基线。"""
    asset = load_base_prompt_override()
    text = (asset.text or "").strip() if asset is not None else ""
    if asset is None or not asset.enabled or not text:
        return builtin_text or ""
    if asset.mode == _REPLACE:
        return text
    core = (builtin_text or "").strip()
    if not core:
        return text
    return f"{core}\n\n{text}"
