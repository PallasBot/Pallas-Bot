from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from src.foundation.config.repo_settings import repo_root
from src.foundation.db import make_group_config_repository

from .compile_group_style import compile_group_style_prompt, compile_group_style_snapshot
from .loader import resolve_persona
from .prompt_guard import (
    ALLOWED_LENGTH_PREFS,
    ALLOWED_TONES,
    guard_system_prompt,
    normalize_enum,
    sanitize_prompt_block,
    wrap_stats_block,
)

if TYPE_CHECKING:
    from .model import ResolvedPersona

_PROMPT_VERSION = 1
_DEFAULT_BASE_PROMPT_PATH = Path(__file__).resolve().parent / "base_system_prompt.txt"

_base_lock = Lock()
_base_cached_path: Path | None = None
_base_cached_mtime: float | None = None
_base_cached_text: str = ""

_TONE_HINTS: dict[str, str] = {
    "neutral": "语气平和自然",
    "calm": "语气沉稳克制",
    "enthusiastic": "语气热情积极",
    "dramatic": "可略带戏剧感与庆典氛围",
    "terse": "回复精简，避免冗长铺陈",
}

_LENGTH_HINTS: dict[str, str] = {
    "any": "按对话情境灵活把握长度",
    "short": "优先简短回复（1-2 句）",
    "medium": "适中长度（2-3 句）",
    "long": "可稍详细展开，但仍保持口语",
}


class PersonaPromptSections(BaseModel):
    base: str
    bot_behavior: str
    group_style: str


class PersonaPromptMetadata(BaseModel):
    version: int = _PROMPT_VERSION
    bot_id: int
    group_id: int | None = None
    persona: dict[str, Any]
    group_style: dict[str, Any]


class PersonaPromptBundle(BaseModel):
    """LLM system 总装结果，供 AI 仓与 WebUI 人工 review。"""

    system: str
    metadata: PersonaPromptMetadata
    sections: PersonaPromptSections


def resolve_base_system_prompt_path(custom_path: str | None = None) -> Path:
    custom = (custom_path or "").strip()
    if custom:
        path = Path(custom)
        if not path.is_absolute():
            path = repo_root() / custom
        return path
    return _DEFAULT_BASE_PROMPT_PATH


def load_base_system_prompt(*, custom_path: str | None = None) -> str:
    global _base_cached_path, _base_cached_mtime, _base_cached_text
    path = resolve_base_system_prompt_path(custom_path)
    with _base_lock:
        if not path.is_file():
            return ""
        mtime = path.stat().st_mtime
        if path != _base_cached_path or mtime != _base_cached_mtime:
            _base_cached_text = path.read_text(encoding="utf-8").strip()
            _base_cached_path = path
            _base_cached_mtime = mtime
        return _base_cached_text


def clear_base_system_prompt_cache() -> None:
    global _base_cached_path, _base_cached_mtime, _base_cached_text
    with _base_lock:
        _base_cached_path = None
        _base_cached_mtime = None
        _base_cached_text = ""


def build_bot_behavior_prompt(persona: ResolvedPersona) -> str:
    tone = normalize_enum(str(persona.tone or ""), ALLOWED_TONES, "neutral")
    length_pref = normalize_enum(str(persona.length_pref or ""), ALLOWED_LENGTH_PREFS, "any")
    tone_hint = _TONE_HINTS[tone]
    length_hint = _LENGTH_HINTS[length_pref]

    lines = [
        "【接话风格】",
        f"- 基调：{tone_hint}",
        f"- 长度：{length_hint}",
    ]
    if persona.chaos_bias >= 0.12:
        lines.append("- 本群/本牛接话偏复读链与短句，回复宜更口语、更短促。")
    elif persona.chaos_bias > 0 and persona.chaos_bias < 0.08:
        lines.append("- 接话句型较分散，避免机械复读同一模板。")
    if persona.warmth >= 0.15:
        lines.append("- 态度偏温和，优先接住话题，少生硬拒绝。")
    elif persona.warmth <= -0.15:
        lines.append("- 态度偏冷，非必要不多接话。")
    if persona.assertiveness >= 0.15:
        lines.append("- 可适度接梗、反抛或短促顶一句，但保持帕拉斯身份。")
    elif persona.assertiveness <= -0.15:
        lines.append("- 少反呛，优先顺着群聊节奏。")
    return wrap_stats_block("bot_behavior", "\n".join(lines))


def assemble_persona_system(sections: PersonaPromptSections) -> str:
    section_values = (sections.base, sections.bot_behavior, sections.group_style)
    parts = [section.strip() for section in section_values if section.strip()]
    core = "\n\n".join(parts)
    return guard_system_prompt(core)


def compile_persona_prompt(
    persona: ResolvedPersona,
    style_profile: dict[str, Any] | None,
    *,
    bot_id: int,
    group_id: int | None = None,
    base_system: str | None = None,
    base_system_path: str | None = None,
) -> PersonaPromptBundle:
    base = sanitize_prompt_block(
        (base_system or "").strip() or load_base_system_prompt(custom_path=base_system_path),
        max_len=12000,
    )
    bot_behavior = build_bot_behavior_prompt(persona)
    group_style = compile_group_style_prompt(style_profile)
    sections = PersonaPromptSections(
        base=base,
        bot_behavior=bot_behavior,
        group_style=group_style,
    )
    metadata = PersonaPromptMetadata(
        bot_id=int(bot_id),
        group_id=int(group_id) if group_id is not None else None,
        persona=persona.model_dump(),
        group_style=compile_group_style_snapshot(style_profile),
    )
    return PersonaPromptBundle(
        system=assemble_persona_system(sections),
        metadata=metadata,
        sections=sections,
    )


async def compile_persona_prompt_for(
    bot_id: int,
    group_id: int | None = None,
    *,
    base_system: str | None = None,
    base_system_path: str | None = None,
) -> PersonaPromptBundle:
    bid = int(bot_id)
    gid = int(group_id) if group_id is not None else None
    persona = await resolve_persona(bid, gid)
    style_profile: dict[str, Any] | None = None
    if gid is not None:
        group_config = await make_group_config_repository().get(gid)
        if group_config is not None:
            raw_profile = getattr(group_config, "style_profile", None)
            if isinstance(raw_profile, dict):
                style_profile = raw_profile
    return compile_persona_prompt(
        persona,
        style_profile,
        bot_id=bid,
        group_id=gid,
        base_system=base_system,
        base_system_path=base_system_path,
    )
