"""账号级处事风格：只为 direct chat 提供稳定且有界的约束。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .prompt_guard import sanitize_prompt_literal, wrap_stats_block


class PersonaDisposition(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    version: int = Field(default=1, ge=1, le=16)
    approach: str = ""
    initiative: str = ""
    conflict: str = ""
    do: list[str] = Field(default_factory=list)
    dont: list[str] = Field(default_factory=list)


def normalize_disposition_lines(raw: object, *, limit: int = 4, max_len: int = 80) -> list[str]:
    if not isinstance(raw, list):
        return []
    lines: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = sanitize_prompt_literal(str(item or ""), max_len=max_len)
        if not text or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        lines.append(text)
        if len(lines) >= limit:
            break
    return lines


def resolve_persona_disposition(bot_persona: dict[str, Any] | None) -> PersonaDisposition:
    raw = bot_persona.get("disposition") if isinstance(bot_persona, dict) else None
    if not isinstance(raw, dict):
        return PersonaDisposition()
    try:
        return PersonaDisposition(
            version=raw.get("version", 1),
            approach=sanitize_prompt_literal(str(raw.get("approach") or ""), max_len=120),
            initiative=sanitize_prompt_literal(str(raw.get("initiative") or ""), max_len=120),
            conflict=sanitize_prompt_literal(str(raw.get("conflict") or ""), max_len=120),
            do=normalize_disposition_lines(raw.get("do")),
            dont=normalize_disposition_lines(raw.get("dont")),
        )
    except (TypeError, ValueError):
        return PersonaDisposition()


def compile_disposition_prompt(bot_persona: dict[str, Any] | None) -> str:
    disposition = resolve_persona_disposition(bot_persona)
    lines: list[str] = []
    if disposition.approach:
        lines.append(f"处事：{disposition.approach}")
    if disposition.initiative:
        lines.append(f"主动：{disposition.initiative}")
    if disposition.conflict:
        lines.append(f"分歧：{disposition.conflict}")
    if disposition.do:
        lines.append("偏好：" + "；".join(disposition.do))
    if disposition.dont:
        lines.append("避免：" + "；".join(disposition.dont))
    if not lines:
        return ""
    return wrap_stats_block("account_disposition", "\n".join(["【账号处事风格】", *lines]))
