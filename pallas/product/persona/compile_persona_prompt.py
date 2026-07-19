from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from pallas.core.foundation.config.repo_settings import repo_root
from pallas.core.foundation.db import make_bot_config_repository, make_group_config_repository

from .affect_axes import (
    assertiveness_behavior_hint,
    bluntness_behavior_hint,
    warmth_behavior_hint,
)
from .compile_group_style import compile_group_style_prompt, compile_group_style_snapshot
from .config import persona_preset_layers_enabled
from .group_expression import compile_group_expression_prompt
from .loader import resolve_persona, resolve_persona_for_message
from .preset_layers import compile_preset_layers_prompt, extract_preset_layers
from .prompt_guard import (
    ALLOWED_LENGTH_PREFS,
    ALLOWED_TONES,
    guard_system_prompt,
    normalize_enum,
    sanitize_prompt_block,
    wrap_stats_block,
)
from .self_identity import compile_repeater_self_identity_prompt, compile_self_identity_prompt

if TYPE_CHECKING:
    from .model import ResolvedPersona

_PROMPT_VERSION = 1
_DEFAULT_BASE_PROMPT_PATH = Path(__file__).resolve().parent / "base_system_prompt.txt"
_AT_CHAT_BASE_PROMPT_PATH = Path(__file__).resolve().parent / "at_chat_system_prompt.txt"
_REPEATER_BASE_PROMPT_PATH = Path(__file__).resolve().parent / "repeater_system_prompt.txt"
_SELECT_BASE_PROMPT_PATH = Path(__file__).resolve().parent / "select_system_prompt.txt"
_POLISH_LITE_PROMPT_PATH = Path(__file__).resolve().parent / "polish_lite_system_prompt.txt"
_FALLBACK_LITE_PROMPT_PATH = Path(__file__).resolve().parent / "fallback_lite_system_prompt.txt"
REPEATER_PROMPT_PURPOSES = frozenset({"fallback", "polish"})
LITE_REPEATER_PROMPT_PURPOSES = frozenset({"fallback_lite", "polish_lite"})
SELECT_PROMPT_PURPOSES = frozenset({"select"})
PROMPT_PROFILE_DEFAULT = "default"
PROMPT_PROFILE_REPEATER = "repeater"
PROMPT_PROFILE_CHAT = "chat"

_base_lock = Lock()
_base_cached_path: Path | None = None
_base_cached_mtime: float | None = None
_base_cached_text: str = ""

_TONE_HINTS: dict[str, str] = {
    "neutral": "语气平和自然",
    "calm": "语气沉稳克制",
    "enthusiastic": "语气热情积极",
    "dramatic": "可略带戏剧感，但像群友顺口接话",
    "terse": "回复精简，避免冗长铺陈",
}

_REPEATER_TONE_HINTS: dict[str, str] = {
    "neutral": "语气平和，像群友接一句",
    "calm": "语气沉稳克制，别展开解释",
    "enthusiastic": "语气可稍热情，但仍像群友短接",
    "dramatic": "可稍张扬接梗，但勿主动扯庆典或游戏设定",
    "terse": "回复精简，1 句为主",
}

_LENGTH_HINTS: dict[str, str] = {
    "any": "按对话情境灵活把握长度",
    "short": "优先简短回复（1-2 句）",
    "medium": "适中长度（2-3 句）",
    "long": "可稍详细展开，但仍保持口语",
}

_DRUNK_CHAT_OVERLAY = (
    "【醉酒状态】你此刻微醺，语气更随意、更爱调侃与接梗，但仍像群友说话，勿失分寸、勿冗长铺陈，勿主动扯庆典或干员设定。"
)


def resolve_prompt_profile_for_purpose(purpose: str) -> str:
    normalized = str(purpose or "").strip().lower()
    if normalized in REPEATER_PROMPT_PURPOSES:
        return PROMPT_PROFILE_REPEATER
    if normalized == "chat":
        return PROMPT_PROFILE_CHAT
    return PROMPT_PROFILE_DEFAULT


class PersonaPromptSections(BaseModel):
    base: str
    self_identity: str = ""
    preset_layers: str = ""
    bot_behavior: str
    group_style: str
    group_expression: str = ""


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


def resolve_repeater_system_prompt_path() -> Path:
    return _REPEATER_BASE_PROMPT_PATH


def resolve_at_chat_system_prompt_path() -> Path:
    return _AT_CHAT_BASE_PROMPT_PATH


def resolve_select_system_prompt_path() -> Path:
    return _SELECT_BASE_PROMPT_PATH


def resolve_polish_lite_system_prompt_path() -> Path:
    return _POLISH_LITE_PROMPT_PATH


def resolve_fallback_lite_system_prompt_path() -> Path:
    return _FALLBACK_LITE_PROMPT_PATH


def load_lite_system_prompt(path: Path) -> str:
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return ""


def load_polish_lite_system_prompt() -> str:
    return load_lite_system_prompt(resolve_polish_lite_system_prompt_path())


def load_fallback_lite_system_prompt() -> str:
    return load_lite_system_prompt(resolve_fallback_lite_system_prompt_path())


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


def load_at_chat_system_prompt() -> str:
    return load_base_system_prompt(custom_path=str(resolve_at_chat_system_prompt_path()))


def clear_base_system_prompt_cache() -> None:
    global _base_cached_path, _base_cached_mtime, _base_cached_text
    with _base_lock:
        _base_cached_path = None
        _base_cached_mtime = None
        _base_cached_text = ""


def build_bot_behavior_prompt(persona: ResolvedPersona, *, profile: str = PROMPT_PROFILE_DEFAULT) -> str:
    tone = normalize_enum(str(persona.tone or ""), ALLOWED_TONES, "neutral")
    length_pref = normalize_enum(str(persona.length_pref or ""), ALLOWED_LENGTH_PREFS, "any")
    tone_map = _REPEATER_TONE_HINTS if profile == PROMPT_PROFILE_REPEATER else _TONE_HINTS
    tone_hint = tone_map[tone]
    length_hint = _LENGTH_HINTS[length_pref]

    lines = [
        "【接话风格】",
        f"- 基调：{tone_hint}",
        f"- 长度：{length_hint}",
    ]
    if profile == PROMPT_PROFILE_REPEATER:
        lines.append("- 像本群群友接话，以假乱真；用户未聊设定时不要表演角色或扯庆典。")
    if persona.chaos_bias >= 0.12:
        lines.extend([
            "- 本群/本牛接话偏复读链与短句，回复宜更口语、更短促。",
            "- 少写客服式完整解释，像被点到名后顺手接一句。",
        ])
    elif persona.chaos_bias > 0 and persona.chaos_bias < 0.08:
        lines.append("- 接话句型较分散，避免机械复读同一模板。")

    warmth_hint = warmth_behavior_hint(float(persona.warmth))
    if warmth_hint:
        lines.append(warmth_hint)
    assertiveness_hint = assertiveness_behavior_hint(float(persona.assertiveness))
    if assertiveness_hint:
        lines.append(assertiveness_hint)
    bluntness_hint = bluntness_behavior_hint(float(persona.bluntness))
    if bluntness_hint:
        lines.append(bluntness_hint)
    return wrap_stats_block("bot_behavior", "\n".join(lines))


def apply_drunk_chat_overlay(system: str) -> str:
    core = (system or "").strip()
    if not core:
        return _DRUNK_CHAT_OVERLAY
    if _DRUNK_CHAT_OVERLAY in core:
        return core
    return guard_system_prompt(f"{core}\n\n{_DRUNK_CHAT_OVERLAY}")


def assemble_persona_system(sections: PersonaPromptSections, *, mode: str = "normal") -> str:
    section_values = (
        sections.base,
        sections.self_identity,
        sections.preset_layers,
        sections.bot_behavior,
        sections.group_style,
        sections.group_expression,
    )
    parts = [section.strip() for section in section_values if section.strip()]
    core = "\n\n".join(parts)
    system = guard_system_prompt(core)
    if str(mode or "normal").strip().lower() == "drunk":
        return apply_drunk_chat_overlay(system)
    return system


def compile_persona_prompt(
    persona: ResolvedPersona,
    style_profile: dict[str, Any] | None,
    *,
    bot_id: int,
    group_id: int | None = None,
    base_system: str | None = None,
    base_system_path: str | None = None,
    mode: str = "normal",
    bot_persona: dict[str, Any] | None = None,
    prompt_profile: str = PROMPT_PROFILE_DEFAULT,
) -> PersonaPromptBundle:
    profile = str(prompt_profile or PROMPT_PROFILE_DEFAULT).strip() or PROMPT_PROFILE_DEFAULT
    base = sanitize_prompt_block(
        (base_system or "").strip() or load_base_system_prompt(custom_path=base_system_path),
        max_len=12000,
    )
    bot_behavior = build_bot_behavior_prompt(persona, profile=profile)
    group_style = compile_group_style_prompt(style_profile)
    group_expression = compile_group_expression_prompt(style_profile)
    if profile == PROMPT_PROFILE_REPEATER:
        self_identity = compile_repeater_self_identity_prompt(bot_persona)
    else:
        self_identity = compile_self_identity_prompt(bot_persona)
    preset_layers = ""
    if profile != PROMPT_PROFILE_REPEATER and persona_preset_layers_enabled():
        sample = style_profile.get("sample") if isinstance(style_profile, dict) else None
        layers = extract_preset_layers(bot_persona, sample if isinstance(sample, dict) else None)
        preset_layers = compile_preset_layers_prompt(layers)
    sections = PersonaPromptSections(
        base=base,
        self_identity=self_identity,
        preset_layers=preset_layers,
        bot_behavior=bot_behavior,
        group_style=group_style,
        group_expression=group_expression,
    )
    metadata = PersonaPromptMetadata(
        bot_id=int(bot_id),
        group_id=int(group_id) if group_id is not None else None,
        persona=persona.model_dump(),
        group_style=compile_group_style_snapshot(style_profile),
    )
    return PersonaPromptBundle(
        system=assemble_persona_system(sections, mode=mode),
        metadata=metadata,
        sections=sections,
    )


async def compile_persona_prompt_for(
    bot_id: int,
    group_id: int | None = None,
    *,
    plain_text: str | None = None,
    base_system: str | None = None,
    base_system_path: str | None = None,
    mode: str = "normal",
    prompt_profile: str | None = None,
) -> PersonaPromptBundle:
    bid = int(bot_id)
    gid = int(group_id) if group_id is not None else None
    message_text = (plain_text or "").strip()
    if gid is not None and message_text:
        persona = await resolve_persona_for_message(bid, gid, message_text)
    else:
        persona = await resolve_persona(bid, gid)
    style_profile: dict[str, Any] | None = None
    bot_persona: dict[str, Any] | None = None
    bot_repo = make_bot_config_repository()
    bot_config = await bot_repo.get(bid)
    if bot_config is not None:
        raw_persona = getattr(bot_config, "persona", None)
        if isinstance(raw_persona, dict):
            bot_persona = raw_persona
    if gid is not None:
        group_config = await make_group_config_repository().get(gid)
        if group_config is not None:
            raw_profile = getattr(group_config, "style_profile", None)
            if isinstance(raw_profile, dict):
                style_profile = raw_profile
    resolved_profile = str(prompt_profile or PROMPT_PROFILE_DEFAULT).strip() or PROMPT_PROFILE_DEFAULT
    return compile_persona_prompt(
        persona,
        style_profile,
        bot_id=bid,
        group_id=gid,
        base_system=base_system,
        base_system_path=base_system_path,
        mode=mode,
        bot_persona=bot_persona,
        prompt_profile=resolved_profile,
    )
