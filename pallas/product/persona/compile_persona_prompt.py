from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from pallas.core.foundation.config.repo_settings import repo_root
from pallas.core.foundation.db import make_bot_config_repository, make_group_config_repository

from .affect_axes import (
    assertiveness_behavior_hint,
    bluntness_behavior_hint,
    warmth_behavior_hint,
)
from .group_expression_profile import resolve_group_expression_profile
from .loader import resolve_persona, resolve_persona_for_message
from .peer_bots_prompt import (
    compile_peer_bots_prompt,
    compile_peer_bots_prompt_for_message,
)
from .prompt_guard import (
    ALLOWED_TONES,
    guard_system_prompt,
    normalize_enum,
    sanitize_prompt_block,
    wrap_stats_block,
)
from .seed import normalize_seed_prefs, resolve_effective_seed_prefs
from .self_identity import (
    compile_self_identity_prompt,
    resolve_login_nickname,
)

if TYPE_CHECKING:
    from .model import ResolvedPersona

_PROMPT_VERSION = 1
_DEFAULT_BASE_PROMPT_PATH = Path(__file__).resolve().parent / "base_system_prompt.txt"
_AT_CHAT_BASE_PROMPT_PATH = Path(__file__).resolve().parent / "at_chat_system_prompt.txt"
PROMPT_PROFILE_DEFAULT = "default"
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

_ARCHETYPE_FINGERPRINTS: dict[str, str] = {
    "terse": "- 少展开，能一句接完就一句接完，别起哄加戏。",
    "chaotic": "- 可短促接梗，少总结陈词，别把梗抻成长段。",
    "polite": "- 先应一句再吐槽，少抢话下结论，给人留接茬口。",
}

_SEED_FINGERPRINTS: dict[str, str] = {
    "warm": "- 先把对方的话接住，再顺势回一句。",
    "chaotic": "- 可顺手接梗反抛半句，但别连着抖包袱。",
    "restrained": "- 收着点火候，别追着一个梗反复拱。",
}

_DRUNK_CHAT_OVERLAY = (
    "【醉酒状态】你此刻微醺，语气更随意、更爱调侃与接梗，但仍像群友说话，勿失分寸、勿冗长铺陈，勿主动扯庆典或干员设定。"
)


class PersonaPromptSections(BaseModel):
    base: str
    self_identity: str = ""
    bot_behavior: str


class PersonaPromptMetadata(BaseModel):
    version: int = _PROMPT_VERSION
    bot_id: int
    group_id: int | None = None
    persona: dict[str, Any]
    group_expression_profile: dict[str, Any] = Field(default_factory=dict)


class PersonaPromptBundle(BaseModel):
    """LLM system 总装结果，供 AI 仓与 WebUI 人工 review。"""

    system: str
    metadata: PersonaPromptMetadata
    sections: PersonaPromptSections


def resolve_at_chat_system_prompt_path() -> Path:
    return _AT_CHAT_BASE_PROMPT_PATH


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


def build_bot_behavior_prompt(
    persona: ResolvedPersona,
    *,
    seed_prefs: list[str] | None = None,
) -> str:
    tone = normalize_enum(str(persona.tone or ""), ALLOWED_TONES, "neutral")
    tone_hint = _TONE_HINTS[tone]

    lines = [
        "【接话风格】",
        f"- 基调：{tone_hint}",
    ]
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
    fingerprint_lines: list[str] = []
    archetype_fingerprint = _ARCHETYPE_FINGERPRINTS.get(str(persona.archetype or "").strip().lower())
    if archetype_fingerprint:
        fingerprint_lines.extend(["【接话指纹】", archetype_fingerprint])
    normalized_seed_prefs = normalize_seed_prefs(seed_prefs or [])
    if normalized_seed_prefs:
        if not fingerprint_lines:
            fingerprint_lines.append("【接话指纹】")
        for pref in normalized_seed_prefs:
            seed_line = _SEED_FINGERPRINTS.get(pref)
            if seed_line and seed_line not in fingerprint_lines:
                fingerprint_lines.append(seed_line)
        fingerprint_lines.append("- 少反复同一隐喻起手。")
    if fingerprint_lines:
        lines.extend(fingerprint_lines)
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
        sections.bot_behavior,
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
    login_nickname: str | None = None,
    plain_text: str = "",
) -> PersonaPromptBundle:
    profile = str(prompt_profile or PROMPT_PROFILE_DEFAULT).strip() or PROMPT_PROFILE_DEFAULT
    base = sanitize_prompt_block(
        (base_system or "").strip() or load_base_system_prompt(custom_path=base_system_path),
        max_len=12000,
    )
    seed_prefs, _seed_source = resolve_effective_seed_prefs(bot_persona, int(bot_id))
    bot_behavior = (
        ""
        if profile == PROMPT_PROFILE_CHAT
        else build_bot_behavior_prompt(
            persona,
            seed_prefs=seed_prefs,
        )
    )
    self_identity = compile_self_identity_prompt(
        bot_persona,
        login_nickname=login_nickname,
    )
    peer = (
        compile_peer_bots_prompt_for_message(
            self_bot_id=int(bot_id),
            plain_text=plain_text,
            bot_persona=bot_persona,
        )
        if profile == PROMPT_PROFILE_CHAT
        else compile_peer_bots_prompt(self_bot_id=int(bot_id), bot_persona=bot_persona)
    )
    if peer:
        self_identity = f"{self_identity}\n\n{peer}" if self_identity.strip() else peer
    sections = PersonaPromptSections(
        base=base,
        self_identity=self_identity,
        bot_behavior=bot_behavior,
    )
    metadata = PersonaPromptMetadata(
        bot_id=int(bot_id),
        group_id=int(group_id) if group_id is not None else None,
        persona=persona.model_dump(),
        group_expression_profile=resolve_group_expression_profile(style_profile).model_dump(mode="json"),
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
    login_nickname = await resolve_login_nickname(bid)
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
        login_nickname=login_nickname or None,
        plain_text=message_text,
    )
