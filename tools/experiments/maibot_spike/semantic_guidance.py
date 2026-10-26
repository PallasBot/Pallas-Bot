"""Isolated semantic-style guidance probe; not a registered MaiBot hook.

Pass a temporary data root explicitly. Do not call this from a live Pallas
process: it briefly redirects the Pallas style data path to that root.
"""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import gettempdir
from unittest.mock import patch

from pallas.core.foundation import paths
from pallas.product.llm import repeater_semantic_style as semantic_style
from pallas.product.llm.assembler.chat_prompt import ChatPromptAssembler, ResolvedGroupExpression


def _positive_id(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a positive integer")
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be a positive integer") from exc
    if result <= 0 or isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{label} must be a positive integer")
    return result


def _temporary_profiles(bot_id: int, group_id: int, query_text: str, request_id: str) -> str:
    settings = semantic_style.load_semantic_style_settings(bot_id=bot_id, group_id=group_id)
    if not settings.injection_enabled:
        return ""

    resolution = semantic_style.resolve_cached_semantic_style(
        bot_id,
        group_id,
        "group_chat",
        request_id=request_id,
        query_text=query_text,
    )
    patterns = []
    for pattern in resolution.behavior_patterns:
        action = pattern.interaction_action
        relation = pattern.semantic_relation
        form = pattern.form
        trigger = semantic_style.prompt_safe_expression_sample(
            pattern.representative_triggers[-1] if pattern.representative_triggers else ""
        )
        if (
            trigger
            and action in semantic_style.INTERACTION_ACTION_VOCABULARY
            and relation in semantic_style.SEMANTIC_RELATION_VOCABULARY
            and form in semantic_style.FORM_VOCABULARY
        ):
            patterns.append(pattern.model_copy(update={"representative_triggers": [trigger]}))

    strategies = [
        strategy
        for strategy in resolution.behavior_strategies
        if semantic_style.prompt_safe_expression_sample(strategy.scene)
        and semantic_style.prompt_safe_expression_sample(strategy.action)
    ]
    expression = ResolvedGroupExpression(
        matched_examples=resolution.matched_examples,
        prompt_block=semantic_style.append_cached_semantic_style_block("", resolution.style_anchor, ""),
        behavior_strategies=strategies,
        behavior_patterns=patterns,
        continuation_patterns=resolution.continuation_patterns,
    )
    blocks = (
        ChatPromptAssembler._group_expression_block(expression),
        ChatPromptAssembler._group_behavior_reference_block(expression),
    )
    return "\n\n".join(block for block in blocks if block)


def build_style_guidance(
    bot_id: int,
    group_id: int,
    query_text: str,
    *,
    request_id: str,
    data_dir: str | Path,
) -> str:
    """Return sanitized text guidance for future extra_prompt composition.

    The probe redirects process-global path/env settings to data_dir while it
    runs. Use only in an isolated, non-concurrent experiment process; it honors
    the normal A/B, circuit-breaker, and injection-enabled gates.
    """
    bot = _positive_id(bot_id, "bot_id")
    group = _positive_id(group_id, "group_id")
    data_root = Path(data_dir).resolve()
    production_data_root = paths.DATA_ROOT.resolve()
    temporary_root = Path(gettempdir()).resolve()
    if data_root == temporary_root or not data_root.is_relative_to(temporary_root):
        raise ValueError("data_dir must be a dedicated directory under the system temporary directory")
    if data_root == production_data_root or data_root.is_relative_to(production_data_root):
        raise ValueError("data_dir must be isolated from the repository data directory")

    with semantic_style._profiles_lock:
        prior_profiles = semantic_style._profiles
        prior_revision = semantic_style._profiles_revision
    try:
        with (
            patch.object(paths, "DATA_ROOT", data_root),
            patch.dict(os.environ, {"PALLAS_DATA_DIR": str(data_root)}),
        ):
            semantic_style.refresh_semantic_style_cache(force=True)
            return _temporary_profiles(bot, group, str(query_text or ""), str(request_id or ""))
    finally:
        with semantic_style._profiles_lock:
            semantic_style._profiles = prior_profiles
            semantic_style._profiles_revision = prior_revision


if __name__ == "__main__":
    raise SystemExit("Import build_style_guidance() from an isolated experiment; no production profile is read.")
