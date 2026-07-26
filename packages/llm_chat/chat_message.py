import asyncio
import time

from nonebot import logger, on_message
from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.rule import Rule
from ulid import ULID

from pallas.core.foundation.config import TaskManager
from pallas.core.perm import group_message_permission_for_command
from pallas.core.platform.ai_callback.task_types import LLM_CHAT_TASK_TYPE
from pallas.product.llm import ChatSubmitRequest, get_llm_config, is_llm_chat_service_enabled, submit_chat_task
from pallas.product.llm.assembler import assemble_tool_bundle
from pallas.product.llm.assembler.context import assemble_direct_chat_context
from pallas.product.llm.behavior import (
    build_behavior_hint_text,
    classify_behavior_scene,
    default_group_chat_behavior_hint,
    select_behavior_patterns,
)
from pallas.product.llm.behavior_store import ensure_default_behavior_patterns
from pallas.product.llm.chat_queue import merge_queued_chat, stash_chat_during_cooldown
from pallas.product.llm.dynamic_expression_context import (
    build_dynamic_expression_hint as build_llm_chat_dynamic_expression_hint,
)
from pallas.product.llm.dynamic_expression_context import (
    extract_chat_trigger_keywords,
    load_recent_live_expression_rows,
)
from pallas.product.llm.feedback_chat_hint import build_group_feedback_chat_hint
from pallas.product.llm.followup_window import in_followup_window, note_hard_speak_trigger
from pallas.product.llm.governance import check_llm_chat_gate, refresh_llm_chat_cooldown
from pallas.product.llm.kernel import (
    ConversationContext,
    behavior_scene_to_conversation_scene,
    can_read_behavioral_learning,
    decide_direct_chat_action,
    resolve_conversation_feature_level,
)
from pallas.product.llm.memory import (
    maybe_persist_relationship_from_utterance,
    parse_memory_teach,
    parse_relationship_teach,
    resolve_relationship_teach_target_id,
    save_memory_entry,
    save_relationship_note,
)
from pallas.product.llm.memory.auto_episode import maybe_auto_save_episode
from pallas.product.llm.message_guard import normalize_llm_chat_user_text
from pallas.product.llm.persona_context import build_persona_llm_context
from pallas.product.llm.polish_lite import submit_corpus_assist_stages
from pallas.product.llm.reply_gate import evaluate_llm_reply_gate_result, reply_gate_skip_metric
from pallas.product.llm.reply_variation import (
    build_recent_reply_ending_hint,
    build_recent_reply_variation_hint,
    repeated_assistant_openers,
    should_wait_for_more,
)
from pallas.product.llm.session_store import list_user_llm_messages
from pallas.product.llm.speak_perception import evaluate_speak_perception, speak_perception_metrics
from pallas.product.llm.task_metrics import record_bot_llm_task
from pallas.product.persona.affect_kernel import (
    build_persona_affect_contract,
    build_persona_affect_system_block,
    build_variation_hint_from_contract,
    group_flavor_summary_from_style_snapshot,
)
from pallas.product.persona.corpus_expression_habits import infer_expression_affect_stance
from pallas.product.persona.expression_habits import build_expression_context_with_entries
from pallas.product.persona.peer_bots_prompt import save_peer_alias_from_teach
from pallas.product.persona.self_identity import (
    extract_self_aliases,
    maybe_persist_self_alias_from_utterance,
    resolve_cached_login_nickname,
    resolve_login_nickname,
    save_self_alias_from_teach,
)

from . import startup as _startup  # noqa: F401
from .config import get_llm_chat_config
from .near_field_scorer import ANSWER_SOURCE as _ANSWER_SOURCE
from .near_field_scorer import recent_hint_source_label, select_scored_expression_candidates
from .prompts import get_system_prompt
from .replies import (
    LLM_CHAT_ALIAS_SAVED_REPLY,
    LLM_CHAT_MEMORY_SAVED_REPLY,
    LLM_CHAT_PEER_ALIAS_SAVED_REPLY,
    LLM_CHAT_RELATIONSHIP_SAVED_REPLY,
    LLM_CHAT_VAGUE_REPLY,
)


def llm_chat_rule(event: Event) -> bool:
    if not is_llm_chat_service_enabled():
        return False
    if bool(getattr(event, "to_me", False)):
        return True
    llm_cfg = get_llm_config()
    if not llm_cfg.llm_speak_perception_enabled:
        return False
    if not (
        llm_cfg.llm_speak_mention_enabled or llm_cfg.llm_speak_ambient_enabled or llm_cfg.llm_speak_followup_enabled
    ):
        return False
    return isinstance(event, GroupMessageEvent)


llm_chat_msg = on_message(
    priority=get_llm_chat_config().llm_chat_min_priority + 1,
    block=False,
    rule=Rule(llm_chat_rule),
    permission=group_message_permission_for_command("llm_chat.chat"),
)


async def _resolve_speak_aliases(bot_id: int) -> list[str]:
    login_nick = await resolve_login_nickname(int(bot_id))
    if not login_nick:
        login_nick = resolve_cached_login_nickname(int(bot_id))
    persona_dict = None
    try:
        from pallas.core.foundation.db import make_bot_config_repository

        doc = await make_bot_config_repository().get(int(bot_id))
        raw = getattr(doc, "persona", None) if doc is not None else None
        if isinstance(raw, dict):
            persona_dict = raw
    except Exception:
        persona_dict = None
    return extract_self_aliases(persona_dict, login_nickname=login_nick or None)


def resolve_corpus_llm_route(llm_cfg, pool: list[str], candidate: str) -> str:
    if llm_cfg.llm_polish_lite_enabled and candidate and pool:
        return "corpus_polish_lite"
    if len(pool) >= 2 and llm_cfg.llm_select_enabled:
        return "corpus_select"
    if candidate and llm_cfg.llm_polish_enabled:
        return "corpus_polish"
    return "corpus_fallback"


async def build_llm_chat_expression_suffix(
    group_id: int | None,
    plain_text: str = "",
    *,
    bot_id: int = 0,
    blocked_openers: list[str] | None = None,
) -> str:
    suffix, _entries = await build_llm_chat_expression_selection(
        group_id,
        plain_text,
        bot_id=bot_id,
        blocked_openers=blocked_openers,
    )
    return suffix


async def build_llm_chat_expression_selection(
    group_id: int | None,
    plain_text: str = "",
    *,
    bot_id: int = 0,
    blocked_openers: list[str] | None = None,
) -> tuple[str, list]:
    if group_id is None:
        return "", []
    from pallas.core.foundation.db import make_group_config_repository

    profile = None
    try:
        group_config = await make_group_config_repository().get(int(group_id))
    except Exception:
        group_config = None
    if group_config is not None:
        raw_profile = getattr(group_config, "style_profile", None)
        profile = raw_profile if isinstance(raw_profile, dict) else None
    return await build_expression_context_with_entries(
        int(group_id),
        plain_text,
        bot_id=bot_id,
        style_profile=profile,
        blocked_openers=blocked_openers,
    )


def build_llm_chat_ending_hint(turns) -> str:
    return build_recent_reply_ending_hint(turns)


async def build_llm_chat_corpus_ending_hint(
    group_id: int | None,
    text: str = "",
    *,
    bot_id: int | None = None,
    current_user_id: int | None = None,
) -> str:
    if group_id is None:
        return ""
    recent_rows = await load_recent_live_expression_rows(
        int(group_id),
        text,
        bot_id=bot_id,
        current_user_id=current_user_id,
    )
    near_field_rows = list(recent_rows)

    try:
        from pallas.core.foundation.db.context_repo_access import get_shared_context_repository
    except Exception:
        repo = None
    else:
        repo = get_shared_context_repository()

    answer_rows: list[dict[str, object]] = []
    list_answers = getattr(repo, "list_answers_for_group_since", None) if repo is not None else None
    if callable(list_answers):
        try:
            answers = await list_answers(int(group_id), 0)
        except Exception:
            answers = []
        for ans in answers:
            messages = getattr(ans, "messages", None) or []
            sample = str(messages[0] if messages else getattr(ans, "keywords", "") or "").strip()
            answer_rows.append({
                "text": sample,
                "count": int(getattr(ans, "count", 0) or 0),
                "keywords": str(getattr(ans, "keywords", "") or "").strip(),
                "source": _ANSWER_SOURCE,
                "time": int(getattr(ans, "time", 0) or 0),
                "topic_hits": 0,
            })

    trigger_keywords = extract_chat_trigger_keywords(text)
    target_stance = infer_expression_affect_stance(text)
    merged_rows = near_field_rows + answer_rows
    candidates = select_scored_expression_candidates(
        merged_rows,
        target_stance=target_stance,
        trigger_keywords=trigger_keywords,
        query_text=text,
        limit=3,
        reference_min_len=2,
        reference_min_cjk=2,
    )
    if not candidates:
        return ""
    label = recent_hint_source_label(merged_rows, trigger_keywords)
    return "\n【语料收尾参考】" + label + "：" + "、".join(candidates) + "。"


async def latest_llm_assistant_reply(bot_id: int, group_id: int | None, user_id: int) -> str:
    try:
        turns = await list_user_llm_messages(bot_id, group_id, user_id, limit=6)
    except Exception:
        return ""
    for turn in reversed(turns):
        if str(getattr(turn, "role", "")).strip() == "assistant":
            return str(getattr(turn, "content", "") or "").strip()
    return ""


@llm_chat_msg.handle()
async def handle_llm_chat(bot: Bot, event: Event):
    if not is_llm_chat_service_enabled():
        return

    cfg = get_llm_chat_config()
    plain = event.get_plaintext().strip()
    if plain.casefold() in ("clear", "unload", "model"):
        return

    session_id = event.get_session_id()
    msg = str(event.get_message()).strip()
    if not msg:
        if not plain and not getattr(event, "reply", None):
            return
        await llm_chat_msg.send(LLM_CHAT_VAGUE_REPLY)
        return

    llm_cfg = get_llm_config()
    raw_group_id = getattr(event, "group_id", None)
    group_id = int(raw_group_id) if raw_group_id is not None else None
    user_id = int(getattr(event, "user_id", 0) or 0)
    is_to_me = bool(getattr(event, "to_me", False))
    speak_trigger = "to_me" if is_to_me else ""
    followup_window_sec = int(llm_cfg.llm_speak_followup_window_sec)
    followup_max_total = int(llm_cfg.llm_speak_followup_max_total_sec)

    if is_to_me and llm_cfg.llm_speak_followup_enabled:
        note_hard_speak_trigger(
            group_id,
            user_id,
            window_seconds=followup_window_sec,
            max_total_seconds=followup_max_total,
        )

    if llm_cfg.llm_speak_perception_enabled and not is_to_me:
        followup_active = bool(
            llm_cfg.llm_speak_followup_enabled
            and in_followup_window(
                group_id,
                user_id,
                window_seconds=followup_window_sec,
                max_total_seconds=followup_max_total,
            )
        )
        speak_aliases = await _resolve_speak_aliases(int(bot.self_id))
        decision = evaluate_speak_perception(
            plain_text=plain or msg,
            aliases=speak_aliases,
            is_to_me=False,
            bot_id=int(bot.self_id),
            mention_enabled=llm_cfg.llm_speak_mention_enabled,
            ambient_enabled=llm_cfg.llm_speak_ambient_enabled,
            ambient_rate=llm_cfg.llm_speak_ambient_rate,
            ambient_min_score=llm_cfg.llm_speak_ambient_min_score,
            ambient_cooldown_sec=llm_cfg.llm_speak_ambient_cooldown_sec,
            min_alias_len=llm_cfg.llm_speak_min_alias_len,
            group_id=group_id,
            followup_active=followup_active,
        )
        for metric in speak_perception_metrics(decision):
            record_bot_llm_task(LLM_CHAT_TASK_TYPE, metric)
        if not decision.should_speak:
            return
        speak_trigger = decision.reason
        if speak_trigger == "mention" and llm_cfg.llm_speak_followup_enabled:
            note_hard_speak_trigger(
                group_id,
                user_id,
                window_seconds=followup_window_sec,
                max_total_seconds=followup_max_total,
            )

    teach_body = parse_memory_teach(plain or msg)
    if teach_body is not None and llm_cfg.llm_memory_rag_enabled:
        saved = await save_memory_entry(int(bot.self_id), group_id, teach_body, cfg=llm_cfg)
        if saved:
            await llm_chat_msg.send(LLM_CHAT_MEMORY_SAVED_REPLY)
            return

    if await save_self_alias_from_teach(int(bot.self_id), plain or msg):
        await llm_chat_msg.send(LLM_CHAT_ALIAS_SAVED_REPLY)
        return

    if await save_peer_alias_from_teach(int(bot.self_id), plain or msg):
        await llm_chat_msg.send(LLM_CHAT_PEER_ALIAS_SAVED_REPLY)
        return

    # 弱模式称呼静默沉淀，不打断闲聊
    try:
        await maybe_persist_self_alias_from_utterance(int(bot.self_id), plain or msg)
    except Exception:
        logger.debug("self_alias observe persist skipped")

    relationship_body = parse_relationship_teach(plain or msg)
    if relationship_body is not None and llm_cfg.llm_relationship_notes_enabled:
        target_id = resolve_relationship_teach_target_id(
            msg,
            speaker_id=user_id,
            bot_self_id=int(bot.self_id),
        )
        saved = await save_relationship_note(int(bot.self_id), group_id, target_id, relationship_body, cfg=llm_cfg)
        if saved:
            logger.info(
                "relationship teach saved bot={} group={} target={} fact={!r}",
                int(bot.self_id),
                group_id,
                target_id,
                relationship_body[:48],
            )
            await llm_chat_msg.send(LLM_CHAT_RELATIONSHIP_SAVED_REPLY)
            return

    # 硬触发后静默沉淀关系事实/态度；ambient 不写
    try:
        await maybe_persist_relationship_from_utterance(
            int(bot.self_id),
            group_id,
            user_id,
            plain or msg,
            speak_trigger=speak_trigger,
            cfg=llm_cfg,
        )
    except Exception:
        logger.debug("relationship silent persist skipped")

    system_prompt = ""
    bundle = None
    persona_bundle = None
    try:
        bundle, temperature, token_count = await build_persona_llm_context(
            int(bot.self_id),
            group_id,
            plain or msg,
            mode="normal",
            purpose="chat",
            base_system_path=cfg.llm_chat_system_prompt_path or None,
        )
        persona_bundle = bundle
        system_prompt = bundle.system.strip()
    except Exception:
        logger.exception("compile_persona_prompt failed, falling back to static system prompt")
        temperature = None
        token_count = None

    if not system_prompt:
        system_prompt = get_system_prompt()
    if not system_prompt:
        logger.error("llm chat system prompt file is missing or empty")
        await llm_chat_msg.send(LLM_CHAT_VAGUE_REPLY)
        return

    assembled_context = await assemble_direct_chat_context(
        system_prompt,
        bot_id=int(bot.self_id),
        group_id=group_id,
        user_id=user_id,
        query_text=plain or msg,
        cfg=llm_cfg,
    )
    system_prompt = assembled_context.system_prompt
    knowledge_retrieval_trace = assembled_context.knowledge_retrieval_trace
    hybrid_retrieval_trace = assembled_context.hybrid_retrieval_trace
    expression_suffix = ""

    persona_for_gate = None
    if persona_bundle is not None:
        try:
            persona_raw = persona_bundle.metadata.persona
            if isinstance(persona_raw, dict):
                from pallas.product.persona.model import ResolvedPersona

                persona_for_gate = ResolvedPersona(**persona_raw)
        except Exception:
            persona_for_gate = None

    user_warmth_delta = float(assembled_context.relationship_trace.get("warmth_delta") or 0.0)
    user_assertiveness_delta = float(assembled_context.relationship_trace.get("assertiveness_delta") or 0.0)

    gate_result = evaluate_llm_reply_gate_result(
        plain or msg,
        cfg=llm_cfg,
        persona=persona_for_gate,
        bot_id=int(bot.self_id),
    )
    gate_decision = gate_result.decision
    if gate_decision == "skip":
        record_bot_llm_task(LLM_CHAT_TASK_TYPE, "reply_gate_skip")
        skip_metric = reply_gate_skip_metric(gate_result.reason)
        if skip_metric:
            record_bot_llm_task(LLM_CHAT_TASK_TYPE, skip_metric)
        logger.debug(
            "llm chat reply gate skip group={} user={} reason={}",
            group_id,
            user_id,
            gate_result.reason,
        )
        return
    if should_wait_for_more(plain or msg):
        record_bot_llm_task(LLM_CHAT_TASK_TYPE, "reply_gate_defer")
        logger.debug("llm chat wait-for-more group={} user={}", group_id, user_id)
        return
    record_bot_llm_task(LLM_CHAT_TASK_TYPE, "reply_gate_proceed")

    if llm_cfg.llm_select_enabled and group_id is not None and isinstance(event, GroupMessageEvent):
        from packages.repeater.model import Chat

        chat = Chat(event)
        try:
            bundle = await chat.find_reply_bundle()
        except Exception:
            bundle = None
        if bundle is not None:
            pool = [item for item in bundle.message_pool if item and "[CQ:" not in item]
            candidate = next((item for item in bundle.answer_list if item and "[CQ:" not in item), "")
            from pallas.product.llm.repeater_capabilities import resolve_repeater_capabilities

            if (pool or candidate) and await submit_corpus_assist_stages(
                event,
                user_text=plain or msg,
                candidates=pool,
                candidate_text=candidate,
                profile="direct_chat",
                capabilities=resolve_repeater_capabilities(llm_cfg),
            ):
                gate = await check_llm_chat_gate(event, group_id, cfg=llm_cfg)
                if gate is None:
                    await refresh_llm_chat_cooldown(event, default_cd_sec=llm_cfg.llm_chat_cooldown_sec)
                return
            corpus_fallback = candidate or (pool[0] if pool else "")
            llm_route = resolve_corpus_llm_route(llm_cfg, pool, candidate)
        else:
            corpus_fallback = ""
            llm_route = "plain_llm_chat"
    else:
        corpus_fallback = ""
        llm_route = "plain_llm_chat"

    gate = await check_llm_chat_gate(event, group_id, cfg=llm_cfg)
    if gate is not None:
        if gate == "cooldown" and llm_cfg.llm_chat_queue_merge:
            stash_chat_during_cooldown(int(bot.self_id), group_id, user_id, msg, cfg=llm_cfg)
            record_bot_llm_task(LLM_CHAT_TASK_TYPE, "reply_gate_defer")
            logger.debug("llm chat queued during cooldown group={} user={}", group_id, user_id)
            return
        if gate == "cooldown":
            record_bot_llm_task(LLM_CHAT_TASK_TYPE, "reply_gate_skip")
        logger.debug("llm chat gated: reason={} group={} user={}", gate, group_id, user_id)
        return

    merge_result = merge_queued_chat(int(bot.self_id), group_id, user_id, msg, cfg=llm_cfg)
    msg = merge_result.text
    if merge_result.merged:
        logger.debug("llm chat merged queued message group={} user={}", group_id, user_id)

    request_id = str(ULID())
    recent_turns = await list_user_llm_messages(int(bot.self_id), group_id, user_id, limit=6)
    blocked_openers = repeated_assistant_openers(recent_turns)
    focus_text = plain or msg
    recent_plain = [str(getattr(turn, "content", "") or "").strip() for turn in recent_turns[-6:]]
    has_multi_party = (
        isinstance(event, GroupMessageEvent)
        and len({
            int(getattr(turn, "user_id", 0) or 0) for turn in recent_turns[-6:] if int(getattr(turn, "user_id", 0) or 0)
        })
        >= 2
    )
    behavior_scene = classify_behavior_scene(
        user_text=focus_text,
        recent_texts=recent_plain,
        has_multi_party_overlap=has_multi_party,
    )
    expression_suffix, selected_expression_entries = await build_llm_chat_expression_selection(
        group_id,
        focus_text,
        bot_id=int(bot.self_id),
        blocked_openers=blocked_openers,
    )
    selected_expression_ids = [item.entry_id for item in selected_expression_entries]
    from pallas.product.llm.situational_rules import enrich_system_with_situational_rules

    system_prompt = enrich_system_with_situational_rules(
        system_prompt,
        focus_text=focus_text,
        recent_texts=recent_plain,
    )
    variation_hint = build_recent_reply_variation_hint(recent_turns)
    affect_system_block = ""
    if persona_for_gate is not None:
        group_flavor = ""
        group_style = getattr(persona_bundle.metadata, "group_style", None)
        if persona_bundle is not None and isinstance(group_style, dict):
            group_flavor = group_flavor_summary_from_style_snapshot(group_style)
        affect_contract = build_persona_affect_contract(
            persona_for_gate,
            group_flavor_summary=group_flavor,
            repeated_openers=blocked_openers,
            user_warmth_delta=user_warmth_delta,
            user_assertiveness_delta=user_assertiveness_delta,
        )
        affect_system_block = build_persona_affect_system_block(affect_contract)
        affect_hint = build_variation_hint_from_contract(affect_contract)
        if affect_hint and affect_hint not in variation_hint:
            variation_hint = f"{variation_hint}\n{affect_hint}".strip() if variation_hint else affect_hint
    dynamic_expression_hint = await build_llm_chat_dynamic_expression_hint(
        group_id,
        focus_text,
        bot_id=int(bot.self_id),
        current_user_id=user_id,
    )
    conversation_scene = behavior_scene_to_conversation_scene(behavior_scene)
    direct_ctx = ConversationContext.for_direct_chat(
        plain_text=focus_text,
        group_id=group_id,
        bot_id=int(bot.self_id),
        user_id=user_id,
        scene=conversation_scene,
        recent_texts=recent_plain,
        has_multi_party_overlap=has_multi_party,
    )
    tool_meta = assemble_tool_bundle(task="llm_chat", user_text=focus_text)
    direct_decision = decide_direct_chat_action(
        direct_ctx,
        feature_level=resolve_conversation_feature_level(llm_cfg),
        tools_enabled=bool(tool_meta.get("tools_enabled")),
    )
    if group_id is not None:
        from packages.repeater.opportunity_trace import append_conversation_decision_trace

        append_conversation_decision_trace({
            "group_id": int(group_id),
            "bot_id": int(bot.self_id),
            **direct_decision.trace.to_trace_row(),
        })
    behavior_patterns = select_behavior_patterns(
        scene=behavior_scene,
        group_id=group_id,
        patterns=ensure_default_behavior_patterns(),
        limit=2,
    )
    behavior_actions = [item.action for item in behavior_patterns]
    from pallas.product.llm.kernel.models import ConversationMode
    from pallas.product.llm.scene_style import format_scene_style_block, resolve_scene_style_constraints
    from pallas.product.llm.turn_style_layers import (
        build_probabilistic_alt_style_hint,
        build_same_utterance_redup_hint,
        build_turn_behavior_block,
        build_turn_wording_user_hints,
        find_previous_reply_for_utterance,
    )
    from pallas.product.persona.catchphrase_bank import compile_catchphrase_prompt_lines

    scene_constraints = resolve_scene_style_constraints(
        behavior_scene,
        ConversationMode.NORMAL,
        direct_chat=True,
    )
    scene_style_block = format_scene_style_block(scene_constraints)
    behavior_hint = ""
    group_behavior_hint = ""
    feedback_hint = ""
    if can_read_behavioral_learning(llm_cfg):
        group_behavior_hint = default_group_chat_behavior_hint()
        behavior_hint = build_behavior_hint_text(scene=behavior_scene, actions=behavior_actions)
        if group_id is not None:
            feedback_hint = await asyncio.to_thread(
                build_group_feedback_chat_hint,
                group_id=int(group_id),
                user_text=focus_text,
            )
    behavior_block = build_turn_behavior_block(
        group_behavior_hint,
        behavior_hint,
        scene_style_block,
    )
    if behavior_block:
        system_prompt = f"{system_prompt.rstrip()}\n\n{behavior_block}"

    previous_same_reply = ""
    try:
        from pallas.product.llm.behavior_store import list_behavior_runs_for_session

        session_runs = list_behavior_runs_for_session(
            bot_id=int(bot.self_id),
            group_id=group_id,
            user_id=user_id,
            limit=20,
        )
        previous_same_reply = find_previous_reply_for_utterance(
            focus_text,
            recent_turns=recent_turns,
            behavior_runs=session_runs,
        )
    except Exception:
        previous_same_reply = find_previous_reply_for_utterance(focus_text, recent_turns=recent_turns)
    redup_hint = build_same_utterance_redup_hint(user_text=focus_text, previous_reply=previous_same_reply)
    alt_style_hint = build_probabilistic_alt_style_hint()
    catchphrase_lines = compile_catchphrase_prompt_lines(
        int(bot.self_id),
        user_text=focus_text,
        scene=str(behavior_scene),
        limit=2,
    )
    selected_catchphrase_ids: list[str] = []
    if catchphrase_lines:
        from pallas.product.persona.catchphrase_bank import select_catchphrases_for_turn

        selected_catchphrase_ids = [
            item.entry_id
            for item in select_catchphrases_for_turn(
                int(bot.self_id), user_text=focus_text, scene=str(behavior_scene), limit=2
            )
        ]
    catchphrase_hint = "\n".join(catchphrase_lines) if catchphrase_lines else ""
    ending_hint = build_llm_chat_ending_hint(recent_turns)
    corpus_ending_hint = await build_llm_chat_corpus_ending_hint(
        group_id,
        focus_text,
        bot_id=int(bot.self_id),
        current_user_id=user_id,
    )
    # 口癖、同句重回、换风格等走临时 user 提示；塑形块仍放 system
    if affect_system_block:
        system_prompt = f"{system_prompt.rstrip()}\n\n{affect_system_block}"
    style_user_hints = build_turn_wording_user_hints(
        expression_suffix,
        dynamic_expression_hint,
        variation_hint,
        feedback_hint,
        ending_hint,
        corpus_ending_hint,
        catchphrase_hint,
        redup_hint,
        alt_style_hint,
    )
    last_reply_text = await latest_llm_assistant_reply(int(bot.self_id), group_id, user_id)
    recent_reply_texts: list[str] = []
    if group_id is not None:
        from pallas.product.llm.repeater_persona_context import load_recent_bot_plain_replies

        try:
            recent_reply_texts = await load_recent_bot_plain_replies(
                int(bot.self_id),
                int(group_id),
                limit=6,
            )
        except Exception:
            recent_reply_texts = []
    persona_dict = None
    if persona_bundle is not None:
        try:
            persona_raw = persona_bundle.metadata.persona
            if isinstance(persona_raw, dict):
                persona_dict = persona_raw
        except Exception:
            persona_dict = None
    login_nick = await resolve_login_nickname(int(bot.self_id))
    self_aliases = extract_self_aliases(persona_dict, login_nickname=login_nick or None)
    llm_user_text = (
        normalize_llm_chat_user_text(
            msg,
            plain=plain,
            bot_self_id=int(bot.self_id),
            mention_names=self_aliases,
        )
        or focus_text.strip()
    )
    from pallas.product.llm.tools.command_invoke import serialize_event_source_segments

    command_source_segments = serialize_event_source_segments(event, bot_id=int(bot.self_id))
    await TaskManager.add_task(
        request_id,
        {
            "bot_id": bot.self_id,
            "group_id": getattr(event, "group_id", None),
            "user_id": user_id,
            "task_type": LLM_CHAT_TASK_TYPE,
            "user_text": llm_user_text,
            "fallback_text": corpus_fallback,
            "llm_route": llm_route,
            "agent_loop_enabled": bool(tool_meta.get("tools_enabled")),
            "agent_stage_plan": list(direct_decision.agent_stages),
            "tool_schema_count": len(tool_meta.get("tool_schemas") or []),
            "last_reply_text": last_reply_text,
            "recent_reply_texts": recent_reply_texts[:6],
            "variation_hint": variation_hint,
            "variation_applied": bool(variation_hint),
            "persona_affect_block": affect_system_block,
            "persona_shaping_active": bool(affect_system_block),
            "dynamic_expression_hint": dynamic_expression_hint,
            "behavior_scene": str(behavior_scene),
            "behavior_pattern_ids": [item.pattern_id for item in behavior_patterns],
            "behavior_actions": [str(item.action) for item in behavior_patterns],
            "behavior_hint": behavior_hint,
            "selected_expression_ids": selected_expression_ids,
            "selected_catchphrase_ids": selected_catchphrase_ids,
            "style_user_hints": style_user_hints[:8],
            "same_utterance_redup": bool(redup_hint),
            "alt_style_applied": bool(alt_style_hint),
            "reply_max_length": int(scene_constraints.max_length or 0),
            "start_time": time.time(),
            "self_aliases": self_aliases[:8],
            "speak_trigger": speak_trigger or "to_me",
            "command_source_segments": command_source_segments,
        },
    )

    result = await submit_chat_task(
        ChatSubmitRequest(
            request_id=request_id,
            session_id=session_id,
            user_text=llm_user_text,
            system_prompt=system_prompt,
            bot_id=int(bot.self_id),
            group_id=group_id,
            user_id=user_id,
            task="llm_chat",
            token_count=token_count,
            temperature=temperature,
            knowledge_retrieval_trace=knowledge_retrieval_trace,
            hybrid_retrieval_trace=hybrid_retrieval_trace,
            style_user_hints=style_user_hints,
            llm_rewrite_metadata={
                "task": "llm_chat",
                "bot_id": int(bot.self_id),
                "self_aliases": self_aliases[:8],
                "variation_hint": variation_hint,
                "persona_affect_block": affect_system_block,
                "persona_shaping_active": bool(affect_system_block or dynamic_expression_hint),
                "dynamic_expression_hint": dynamic_expression_hint,
                "preserve_colloquial_rewrite": bool(affect_system_block or dynamic_expression_hint),
                "command_source_segments": command_source_segments,
                "same_utterance_redup": bool(redup_hint),
                "alt_style_applied": bool(alt_style_hint),
            },
            tool_metadata=tool_meta,
        ),
        cfg=llm_cfg,
    )
    if not result.ok:
        await TaskManager.remove_task(request_id)
        record_bot_llm_task(LLM_CHAT_TASK_TYPE, "submit_skip")
        from pallas.product.llm.submit_gate import user_message_for_submit_status

        hint = user_message_for_submit_status(result.status)
        if hint:
            await llm_chat_msg.send(hint)
        logger.info(
            "llm chat submit skipped: status={} group={} user={}",
            result.status,
            group_id,
            user_id,
        )
        return

    await refresh_llm_chat_cooldown(event, default_cd_sec=llm_cfg.llm_chat_cooldown_sec)
    record_bot_llm_task(LLM_CHAT_TASK_TYPE, "submit_ok")

    if group_id is not None:
        try:
            await maybe_auto_save_episode(
                bot_id=int(bot.self_id),
                group_id=int(group_id),
                user_text=plain or msg,
                cfg=llm_cfg,
            )
        except Exception as exc:
            logger.debug("llm chat auto_episode skipped: {}", exc)

    if not result.task_id:
        await TaskManager.remove_task(request_id)
