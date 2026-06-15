"""导出toml"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from src.foundation.paths import PROJECT_ROOT

from .repo_settings import _atomic_write_text, repo_webui_settings_path

_EXPORT_PATH = PROJECT_ROOT / "config" / "pallas.webui.export.toml"

_RE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


def repo_webui_export_toml_path() -> Path:
    return _EXPORT_PATH


def _toml_quote(s: str) -> str:
    if not s:
        return '""'
    if _RE_IDENT.match(s) and "\n" not in s:
        return s
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _toml_key(name: str) -> str:
    if _RE_IDENT.match(name):
        return name
    escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


@lru_cache(maxsize=1)
def env_key_to_section_label() -> dict[str, str]:
    """环境变量键 → 分组标签。"""
    index: dict[str, str] = {}

    def claim(env_key: str, label: str) -> None:
        k = (env_key or "").strip().upper()
        lab = (label or "").strip()
        if not k or not lab:
            return
        if k not in index:
            index[k] = lab

    try:
        from src.console.webui.env_sections import _registered_sections

        for sec in _registered_sections():
            for ek in sec.field_to_env.values():
                claim(ek, f"common.{sec.id}")
    except Exception:
        pass

    try:
        from src.console.webui.plugin_api import plugin_field_env_key
        from src.console.webui.plugin_catalog import discover_plugin_packages, load_config_class_for_package

        for pkg in discover_plugin_packages():
            cfg_cls = load_config_class_for_package(pkg)
            if cfg_cls is None:
                continue
            for fname in cfg_cls.model_fields:
                claim(plugin_field_env_key(pkg, fname), f"plugin.{pkg}")
    except Exception:
        pass

    return index


def rebuild_webui_json_sections(env: dict[str, str]) -> dict[str, dict[str, str]]:
    """由扁平 ``env`` 生成分组 ``sections``。"""
    index = env_key_to_section_label()
    sections: dict[str, dict[str, str]] = {}
    for raw_k, raw_v in env.items():
        k = str(raw_k).upper()
        label = index.get(k, "other")
        bucket = sections.setdefault(label, {})
        bucket[k] = "" if raw_v is None else str(raw_v)
    return sections


def render_webui_export_toml(
    env: dict[str, str],
    sections: dict[str, dict[str, str]] | None = None,
    *,
    source_path: Path | None = None,
) -> str:
    grouped = sections or rebuild_webui_json_sections(env)
    src = source_path or repo_webui_settings_path()
    lines = [
        "# 本文件由 Pallas-Bot 根据 WebUI 保存自动生成，请勿手动编辑。",
        f"# 来源：{src.as_posix()}",
        "# 基础设施见 config/pallas.toml [bootstrap]。",
        "# 修改配置请使用控制台「插件 / 通用配置」，或编辑 pallas.toml / webui.json。",
        "",
    ]
    for label in sorted(grouped.keys(), key=lambda x: (x != "other", x)):
        table = grouped.get(label) or {}
        if not table:
            continue
        lines.extend((f"[webui.{label}]", f"# {label}"))
        lines.extend(f"{_toml_key(k)} = {_toml_quote(table[k])}" for k in sorted(table.keys()))
        lines.append("")
    if not grouped:
        lines.extend(("# 当前 webui.json 无写入项", ""))
    return "\n".join(lines)


def export_webui_inspection_toml(
    env: dict[str, str] | None = None,
    sections: dict[str, dict[str, str]] | None = None,
) -> Path:
    """写入 ``config/pallas.webui.export.toml``；返回路径。"""
    if env is None:
        path = repo_webui_settings_path()
        env = {}
        sections = None
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}
            if isinstance(data, dict):
                raw_env = data.get("env")
                if isinstance(raw_env, dict):
                    env = {str(k).upper(): "" if v is None else str(v) for k, v in raw_env.items() if k}
                raw_sec = data.get("sections")
                if isinstance(raw_sec, dict):
                    parsed: dict[str, dict[str, str]] = {}
                    for lab, bucket in raw_sec.items():
                        if not lab or not isinstance(bucket, dict):
                            continue
                        parsed[str(lab)] = {str(k).upper(): "" if v is None else str(v) for k, v in bucket.items() if k}
                    sections = parsed
    text = render_webui_export_toml(env or {}, sections)
    out = repo_webui_export_toml_path()
    _atomic_write_text(out, text)
    return out


def clear_env_key_section_cache() -> None:
    env_key_to_section_label.cache_clear()
