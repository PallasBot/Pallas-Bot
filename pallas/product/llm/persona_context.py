"""LLM 提交前：按消息解析 persona 并派生 prompt / 推理参数。"""

from __future__ import annotations

from pallas.product.persona.compile_persona_prompt import (
    REPEATER_PROMPT_PURPOSES,
    PersonaPromptBundle,
    compile_persona_prompt_for,
    resolve_at_chat_system_prompt_path,
    resolve_prompt_profile_for_purpose,
    resolve_repeater_system_prompt_path,
)
from pallas.product.persona.model import ResolvedPersona

from .inference_params import derive_llm_inference_params


async def build_persona_llm_context(
    bot_id: int,
    group_id: int | None,
    plain_text: str | None,
    *,
    mode: str = "normal",
    purpose: str = "chat",
    base_system: str | None = None,
    base_system_path: str | None = None,
) -> tuple[PersonaPromptBundle, float | None, int | None]:
    resolved_base_path = base_system_path
    if not resolved_base_path and purpose in REPEATER_PROMPT_PURPOSES:
        resolved_base_path = str(resolve_repeater_system_prompt_path())
    if not resolved_base_path and purpose == "chat":
        resolved_base_path = str(resolve_at_chat_system_prompt_path())
    bundle = await compile_persona_prompt_for(
        bot_id,
        group_id,
        plain_text=plain_text,
        base_system=base_system,
        base_system_path=resolved_base_path,
        mode=mode,
        prompt_profile=resolve_prompt_profile_for_purpose(purpose),
    )
    persona_raw = bundle.metadata.persona
    persona = ResolvedPersona(**persona_raw) if isinstance(persona_raw, dict) else ResolvedPersona()
    temperature, token_count = derive_llm_inference_params(persona, mode=mode, purpose=purpose)
    return bundle, temperature, token_count
