import time
from collections.abc import Awaitable, Callable

from nonebot import logger, on_message
from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.rule import Rule
from ulid import ULID

from pallas.api.logging import format_plugin_event
from pallas.api.perm import group_message_permission_for_command
from pallas.core.foundation.config import TaskManager
from pallas.core.platform.ai_callback.task_types import LLM_CHAT_TASK_TYPE
from pallas.product.llm import ChatSubmitRequest, get_llm_config, is_llm_chat_service_enabled, submit_chat_task
from pallas.product.llm.assembler import (
    ChatPromptAssembler,
    ResolvedGroupExpression,
    ToolPromptContext,
    assemble_tool_bundle,
)
from pallas.product.llm.assembler.context import ChatContextBundle, assemble_direct_chat_context
from pallas.product.llm.behavior import (
    build_behavior_hint_text,
    classify_behavior_scene,
    select_behavior_patterns,
)
from pallas.product.llm.behavior_store import ensure_default_behavior_patterns
from pallas.product.llm.chat_queue import merge_queued_chat, stash_chat_during_cooldown
from pallas.product.llm.current_turn_decision import (
    CurrentTurnAction,
    CurrentTurnDecisionInput,
    decide_current_turn_with_model,
    should_include_recent_pair_for_turn,
    should_read_persistent_memory_for_turn,
)
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
from pallas.product.llm.reply_gate import evaluate_llm_reply_gate_result, reply_gate_skip_metric
from pallas.product.llm.reply_necessity import evaluate_reply_necessity_gate
from pallas.product.llm.reply_shape import resolve_reply_shape
from pallas.product.llm.reply_variation import should_wait_for_more
from pallas.product.llm.session_store import list_user_llm_messages
from pallas.product.llm.speak_perception import evaluate_speak_perception, speak_perception_metrics
from pallas.product.llm.task_metrics import record_bot_llm_task
from pallas.product.llm.turn_policy import resolve_turn_policy
from pallas.product.persona.peer_bots_prompt import save_peer_alias_from_teach
from pallas.product.persona.self_identity import (
    extract_self_aliases,
    maybe_persist_self_alias_from_utterance,
    resolve_cached_login_nickname,
    resolve_login_nickname,
    resolve_managed_display_name,
    save_self_alias_from_teach,
)

from . import startup as _startup  # noqa: F401
from .config import get_llm_chat_config
from .prompts import get_system_prompt
from .replies import (
    LLM_CHAT_ALIAS_SAVED_REPLY,
    LLM_CHAT_MEMORY_SAVED_REPLY,
    LLM_CHAT_PEER_ALIAS_SAVED_REPLY,
    LLM_CHAT_RELATIONSHIP_SAVED_REPLY,
    LLM_CHAT_VAGUE_REPLY,
)


async def load_recent_bot_plain_replies(bot_id: int, group_id: int, *, limit: int = 6) -> list[str]:
    from pallas.core.foundation.db import make_message_repository

    repo = make_message_repository()
    try:
        messages = await repo.find_recent_in_group(int(group_id), before_time=int(time.time()) + 1, limit=48)
    except Exception:
        return []

    out: list[str] = []
    for msg in messages:
        user_id = int(getattr(msg, "user_id", 0) or 0)
        message_bot_id = int(getattr(msg, "bot_id", 0) or 0)
        if user_id != int(bot_id) and message_bot_id != int(bot_id):
            continue
        plain = str(getattr(msg, "plain_text", "") or "").strip()
        if not plain or "[CQ:" in plain:
            continue
        out.append(plain)
        if len(out) >= max(1, int(limit)):
            break
    return out


def llm_chat_rule(event: Event) -> bool:
    if not is_llm_chat_service_enabled():
        return False
    is_to_me = bool(getattr(event, "to_me", False) or getattr(event, "_pallas_llm_alias_hard_trigger", False))
    plain_text = str(getattr(event, "get_plaintext", lambda: "")() or "").strip()
    raw_message = str(getattr(event, "raw_message", "") or "").strip()
    if not is_to_me and plain_text in {"牛牛", "帕拉斯"} and (not raw_message or raw_message == plain_text):
        return False
    if is_to_me:
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
    managed_display_name = resolve_managed_display_name(int(bot_id))
    persona_dict = None
    try:
        from pallas.core.foundation.db import make_bot_config_repository

        doc = await make_bot_config_repository().get(int(bot_id))
        raw = getattr(doc, "persona", None) if doc is not None else None
        if isinstance(raw, dict):
            persona_dict = raw
    except Exception:
        persona_dict = None
    return extract_self_aliases(
        persona_dict,
        login_nickname=login_nick or None,
        managed_display_name=managed_display_name or None,
    )


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
async def handle_llm_chat(
    bot: Bot,
    event: Event,
    *,
    send_message: Callable[[object], Awaitable[object]] | None = None,
):
    route_started = time.perf_counter()
    if send_message is None:
        send_message = llm_chat_msg.send
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
        await send_message(LLM_CHAT_VAGUE_REPLY)
        return

    llm_cfg = get_llm_config()
    raw_group_id = getattr(event, "group_id", None)
    group_id = int(raw_group_id) if raw_group_id is not None else None
    user_id = int(getattr(event, "user_id", 0) or 0)
    is_alias_hard_trigger = bool(getattr(event, "_pallas_llm_alias_hard_trigger", False))
    is_to_me = bool(getattr(event, "to_me", False) or is_alias_hard_trigger)
    speak_trigger = "alias" if is_alias_hard_trigger else ("to_me" if is_to_me else "")
    followup_window_sec = int(llm_cfg.llm_speak_followup_window_sec)
    followup_max_total = int(llm_cfg.llm_speak_followup_max_total_sec)

    bot_id = int(bot.self_id)
    if is_to_me and llm_cfg.llm_speak_followup_enabled:
        note_hard_speak_trigger(
            bot_id,
            group_id,
            user_id,
            window_seconds=followup_window_sec,
            max_total_seconds=followup_max_total,
        )

    if llm_cfg.llm_speak_perception_enabled and not is_to_me:
        followup_active = bool(
            llm_cfg.llm_speak_followup_enabled
            and in_followup_window(
                bot_id,
                group_id,
                user_id,
                window_seconds=followup_window_sec,
                max_total_seconds=followup_max_total,
            )
        )
        from pallas.product.llm.ambient_turn_window import note_ambient_turn_and_should_flush
        from pallas.product.llm.speak_perception import text_mentions_aliases

        speak_aliases = await _resolve_speak_aliases(bot_id)
        mention_force = bool(
            llm_cfg.llm_speak_mention_enabled
            and text_mentions_aliases(
                plain or msg,
                speak_aliases,
                min_alias_len=llm_cfg.llm_speak_min_alias_len,
            )
        )
        should_eval, _merged = note_ambient_turn_and_should_flush(
            bot_id=bot_id,
            group_id=group_id,
            user_id=user_id,
            text=plain or msg,
            force=followup_active or mention_force,
        )
        if not should_eval:
            record_bot_llm_task(LLM_CHAT_TASK_TYPE, "ambient_turn_coalesce")
            return
        persona_speak_bias = 1.0
        try:
            from pallas.product.persona.loader import resolve_persona

            persona_speak_bias = float((await resolve_persona(bot_id, group_id)).speak_bias)
        except Exception:
            logger.debug("resolve persona speak bias skipped bot={} group={}", bot_id, group_id)
        decision = evaluate_speak_perception(
            plain_text=plain or msg,
            aliases=speak_aliases,
            is_to_me=False,
            bot_id=bot_id,
            mention_enabled=llm_cfg.llm_speak_mention_enabled,
            ambient_enabled=llm_cfg.llm_speak_ambient_enabled,
            ambient_rate=llm_cfg.llm_speak_ambient_rate,
            ambient_min_score=llm_cfg.llm_speak_ambient_min_score,
            ambient_cooldown_sec=llm_cfg.llm_speak_ambient_cooldown_sec,
            ambient_budget_limit=llm_cfg.llm_speak_ambient_budget_limit,
            ambient_budget_window_sec=llm_cfg.llm_speak_ambient_budget_window_sec,
            persona_speak_bias=persona_speak_bias,
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
                bot_id,
                group_id,
                user_id,
                window_seconds=followup_window_sec,
                max_total_seconds=followup_max_total,
            )

    teach_body = parse_memory_teach(plain or msg)
    if teach_body is not None and llm_cfg.llm_memory_rag_enabled:
        saved = await save_memory_entry(int(bot.self_id), group_id, teach_body, cfg=llm_cfg)
        if saved:
            await send_message(LLM_CHAT_MEMORY_SAVED_REPLY)
            return

    if await save_self_alias_from_teach(int(bot.self_id), plain or msg):
        await send_message(LLM_CHAT_ALIAS_SAVED_REPLY)
        return

    if await save_peer_alias_from_teach(int(bot.self_id), plain or msg):
        await send_message(LLM_CHAT_PEER_ALIAS_SAVED_REPLY)
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
            await send_message(LLM_CHAT_RELATIONSHIP_SAVED_REPLY)
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
        await send_message(LLM_CHAT_VAGUE_REPLY)
        return

    persona_for_gate = None
    if persona_bundle is not None:
        try:
            persona_raw = persona_bundle.metadata.persona
            if isinstance(persona_raw, dict):
                from pallas.product.persona.model import ResolvedPersona

                persona_for_gate = ResolvedPersona(**persona_raw)
        except Exception:
            persona_for_gate = None

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
            "llm chat route skipped: reason=reply_gate:{} message_id={} group={} user={}",
            gate_result.reason,
            getattr(event, "message_id", None),
            group_id,
            user_id,
        )
        return
    if should_wait_for_more(plain or msg, is_to_me=is_to_me):
        record_bot_llm_task(LLM_CHAT_TASK_TYPE, "reply_gate_defer")
        logger.debug(
            "llm chat route skipped: reason=wait_for_more message_id={} group={} user={}",
            getattr(event, "message_id", None),
            group_id,
            user_id,
        )
        return
    record_bot_llm_task(LLM_CHAT_TASK_TYPE, "reply_gate_proceed")

    corpus_fallback = ""
    llm_route = "plain_llm_chat"

    gate = await check_llm_chat_gate(event, group_id, cfg=llm_cfg)
    if gate is not None:
        if gate == "cooldown" and llm_cfg.llm_chat_queue_merge:
            stash_chat_during_cooldown(int(bot.self_id), group_id, user_id, msg, cfg=llm_cfg)
            record_bot_llm_task(LLM_CHAT_TASK_TYPE, "reply_gate_defer")
            logger.debug(
                "llm chat route deferred: reason=cooldown message_id={} group={} user={}",
                getattr(event, "message_id", None),
                group_id,
                user_id,
            )
            return
        if gate == "cooldown":
            record_bot_llm_task(LLM_CHAT_TASK_TYPE, "reply_gate_skip")
        logger.debug(
            "llm chat route skipped: reason={} message_id={} group={} user={}",
            gate,
            getattr(event, "message_id", None),
            group_id,
            user_id,
        )
        return

    merge_result = merge_queued_chat(int(bot.self_id), group_id, user_id, msg, cfg=llm_cfg)
    msg = merge_result.text
    if merge_result.merged:
        logger.debug("llm chat merged queued message group={} user={}", group_id, user_id)

    pre_submit_stage_durations_ms = {
        "routing_and_persona": int((time.perf_counter() - route_started) * 1000),
    }
    request_id = str(ULID())
    history_started = time.perf_counter()
    recent_turns = await list_user_llm_messages(int(bot.self_id), group_id, user_id, limit=6)
    recent_reply_texts: list[str] = []
    if group_id is not None:
        try:
            recent_reply_texts = await load_recent_bot_plain_replies(
                int(bot.self_id),
                int(group_id),
                limit=6,
            )
        except Exception:
            recent_reply_texts = []
    pre_submit_stage_durations_ms["history"] = int((time.perf_counter() - history_started) * 1000)
    context_started = time.perf_counter()
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
    conversation_scene = behavior_scene_to_conversation_scene(behavior_scene)
    recent_bot_reply_count = len(recent_reply_texts)
    if not recent_bot_reply_count:
        recent_bot_reply_count = sum(1 for turn in recent_turns if str(getattr(turn, "role", "")) == "assistant")
    tool_meta = assemble_tool_bundle(task="llm_chat", user_text=focus_text)
    required_tool_intent = (
        bool(tool_meta.get("tools_enabled"))
        and bool(tool_meta.get("tool_schemas"))
        and str(tool_meta.get("tool_choice_prefer") or "").strip().lower() == "required"
    )
    necessity = evaluate_reply_necessity_gate(
        text=focus_text,
        is_to_me=is_to_me,
        bot_id=int(bot.self_id),
        has_recent_back_and_forth=bool(recent_turns),
        is_mentioned=speak_trigger == "mention",
        is_followup=speak_trigger == "followup",
        recent_bot_reply_count=recent_bot_reply_count,
    )
    if group_id is not None:
        from packages.repeater.opportunity_trace import append_conversation_decision_trace

        append_conversation_decision_trace({
            "group_id": int(group_id),
            "bot_id": int(bot.self_id),
            "kind": "reply_necessity_trace",
            "decision": necessity.decision,
            "score": necessity.score,
            "detail": necessity.detail,
            "speak_trigger": speak_trigger or "to_me",
        })
    if necessity.decision == "skip" and not required_tool_intent and not is_to_me:
        record_bot_llm_task(LLM_CHAT_TASK_TYPE, "reply_necessity_skip")
        logger.debug(
            "llm chat route skipped: reason=reply_necessity message_id={} group={} user={} score={} detail={}",
            getattr(event, "message_id", None),
            group_id,
            user_id,
            necessity.score,
            necessity.detail,
        )
        return
    direct_ctx = ConversationContext.for_direct_chat(
        plain_text=focus_text,
        group_id=group_id,
        bot_id=int(bot.self_id),
        user_id=user_id,
        scene=conversation_scene,
        recent_texts=recent_plain,
        has_multi_party_overlap=has_multi_party,
    )
    pre_submit_context_durations_ms = {
        "before_turn_decision": int((time.perf_counter() - context_started) * 1000),
    }
    turn_decision_started = time.perf_counter()
    current_turn_decision = await decide_current_turn_with_model(
        CurrentTurnDecisionInput(
            text=focus_text,
            is_to_me=is_to_me,
            is_explicitly_addressed=speak_trigger in {"alias", "mention", "followup"},
            tools_permitted=bool(tool_meta.get("tools_enabled")),
            required_tool_intent=required_tool_intent,
            recent_bot_reply_count=min(6, recent_bot_reply_count),
            has_multi_party_overlap=has_multi_party,
        ),
        enabled=bool(getattr(llm_cfg, "llm_current_turn_decision_enabled", False)),
    )
    pre_submit_context_durations_ms["turn_decision"] = int((time.perf_counter() - turn_decision_started) * 1000)
    if group_id is not None:
        from packages.repeater.opportunity_trace import append_conversation_decision_trace

        append_conversation_decision_trace({
            "group_id": int(group_id),
            "bot_id": int(bot.self_id),
            "kind": "current_turn_decision_trace",
            **current_turn_decision.trace.model_dump(mode="json"),
        })
    if current_turn_decision.action is CurrentTurnAction.PASS:
        logger.debug(
            "llm chat route skipped: reason=current_turn_pass message_id={} group={} user={}",
            getattr(event, "message_id", None),
            group_id,
            user_id,
        )
        return
    if bool(getattr(llm_cfg, "llm_current_turn_decision_enabled", False)) and (
        current_turn_decision.action is not CurrentTurnAction.TOOL
    ):
        tool_meta = {**tool_meta, "tools_enabled": False, "tool_schemas": []}
    turn_policy = resolve_turn_policy(
        current_turn_decision,
        conversation_scene,
        tools_enabled=bool(tool_meta.get("tools_enabled")),
    )
    reply_target = turn_policy.reply_target
    include_persistent_history = should_read_persistent_memory_for_turn(
        focus_text,
        current_turn_decision.social_action,
    )
    include_recent_pair = should_include_recent_pair_for_turn(
        focus_text,
        current_turn_decision.social_action,
        explicitly_addressed=is_to_me or speak_trigger in {"alias", "mention", "followup"},
        has_recent_assistant_turn=any(str(getattr(turn, "role", "")).strip() == "assistant" for turn in recent_turns),
    )
    from pallas.product.llm.repeater_semantic_style import resolve_cached_semantic_style

    semantic_style = resolve_cached_semantic_style(
        int(bot.self_id),
        group_id,
        "group_chat",
        request_id=request_id,
        query_text=focus_text,
        recent_assistant_replies=recent_reply_texts[:6],
    )
    direct_context_started = time.perf_counter()
    assembled_context = await assemble_direct_chat_context(
        bot_id=int(bot.self_id),
        group_id=group_id,
        user_id=user_id,
        query_text=focus_text,
        cfg=llm_cfg,
        allow_persistent_memory=include_persistent_history,
    )
    pre_submit_context_durations_ms["direct_context"] = int((time.perf_counter() - direct_context_started) * 1000)
    for stage, duration in getattr(assembled_context, "stage_durations_ms", {}).items():
        if isinstance(duration, (int, float)):
            pre_submit_context_durations_ms[str(stage)] = max(0, int(duration))
    if isinstance(assembled_context, ChatContextBundle):
        chat_context = assembled_context
    else:
        chat_context = ChatContextBundle(
            memory=str(getattr(assembled_context, "system_prompt", "") or ""),
            knowledge_retrieval_trace=dict(getattr(assembled_context, "knowledge_retrieval_trace", {}) or {}),
            hybrid_retrieval_trace=dict(getattr(assembled_context, "hybrid_retrieval_trace", {}) or {}),
            relationship_trace=dict(getattr(assembled_context, "relationship_trace", {}) or {}),
            stage_durations_ms=dict(getattr(assembled_context, "stage_durations_ms", {}) or {}),
        )
    knowledge_retrieval_trace = chat_context.knowledge_retrieval_trace
    hybrid_retrieval_trace = chat_context.hybrid_retrieval_trace
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
    from pallas.product.llm.scene_style import resolve_scene_style_constraints

    scene_constraints = resolve_scene_style_constraints(
        behavior_scene,
        ConversationMode.NORMAL,
        direct_chat=True,
    )
    behavior_hint = ""
    if can_read_behavioral_learning(llm_cfg):
        behavior_hint = build_behavior_hint_text(scene=behavior_scene, actions=behavior_actions)
    last_assistant_reply_started = time.perf_counter()
    last_reply_text = await latest_llm_assistant_reply(int(bot.self_id), group_id, user_id)
    pre_submit_context_durations_ms["last_assistant_reply"] = int(
        (time.perf_counter() - last_assistant_reply_started) * 1000
    )
    persona_dict = None
    if persona_bundle is not None:
        try:
            persona_raw = persona_bundle.metadata.persona
            if isinstance(persona_raw, dict):
                persona_dict = persona_raw
        except Exception:
            persona_dict = None
    group_expression_profile = None
    if persona_bundle is not None:
        try:
            from pallas.product.persona.model import ResolvedPersona

            persona_raw = persona_bundle.metadata.persona
            if isinstance(persona_raw, dict):
                group_expression_profile = ResolvedPersona(**persona_raw).group_expression_profile
        except Exception:
            group_expression_profile = None
    reply_shape = resolve_reply_shape(turn_policy, group_expression_profile)
    semantic_examples = list(getattr(semantic_style, "matched_examples", []) or [])[:2]
    group_expression = ResolvedGroupExpression(
        style_anchor=str(getattr(semantic_style, "style_anchor", "") or ""),
        matched_examples=[
            (str(item[0] or ""), str(item[1] or ""))
            for item in semantic_examples
            if isinstance(item, (list, tuple)) and len(item) == 2
        ],
    )
    core_persona = system_prompt
    if persona_bundle is not None:
        core_persona = str(getattr(getattr(persona_bundle, "sections", None), "base", "") or core_persona).strip()
    self_identity = ""
    if persona_bundle is not None:
        self_identity = str(getattr(getattr(persona_bundle, "sections", None), "self_identity", "") or "")
    if not self_identity:
        from pallas.product.persona.self_identity import compile_self_identity_prompt

        self_identity = compile_self_identity_prompt()

    system_prompt = ChatPromptAssembler().assemble(
        core_persona=core_persona,
        self_identity=self_identity,
        turn_policy=turn_policy,
        context=chat_context,
        group_expression=group_expression,
        reply_shape=reply_shape,
        tool_context=ToolPromptContext(
            action_tools_enabled=bool(tool_meta.get("tool_schemas")),
            ask_before_call=bool(tool_meta.get("ask_before_call")),
            missing_required_params=dict(tool_meta.get("missing_required_params") or {}),
        ),
    )
    login_nickname_started = time.perf_counter()
    login_nick = await resolve_login_nickname(int(bot.self_id))
    pre_submit_context_durations_ms["login_nickname"] = int((time.perf_counter() - login_nickname_started) * 1000)
    self_aliases = extract_self_aliases(
        persona_dict,
        login_nickname=login_nick or None,
        managed_display_name=resolve_managed_display_name(int(bot.self_id)) or None,
    )
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
    pre_submit_stage_durations_ms["context"] = int((time.perf_counter() - context_started) * 1000)
    task_registration_started = time.perf_counter()
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
            "current_turn_action": current_turn_decision.action,
            "current_turn_trace": current_turn_decision.trace.model_dump(mode="json"),
            "reply_delivery_style": getattr(current_turn_decision, "delivery_style", "PLAIN"),
            "message_id": getattr(event, "message_id", None),
            "has_multi_party_overlap": has_multi_party,
            "reply_target": reply_target,
            "agent_stage_plan": list(direct_decision.agent_stages),
            "tool_schema_count": len(tool_meta.get("tool_schemas") or []),
            "last_reply_text": last_reply_text,
            "recent_reply_texts": recent_reply_texts[:6],
            "behavior_scene": str(behavior_scene),
            "behavior_pattern_ids": [item.pattern_id for item in behavior_patterns],
            "behavior_actions": [str(item.action) for item in behavior_patterns],
            "behavior_hint": behavior_hint,
            "semantic_style_source_example_id": getattr(semantic_style, "source_example_id", "") or None,
            "semantic_style_direct_candidate": semantic_style.direct_candidate or None,
            "reply_max_length": int(scene_constraints.max_length or 0),
            "start_time": time.time(),
            "self_aliases": self_aliases[:8],
            "speak_trigger": speak_trigger or "to_me",
            "command_source_segments": command_source_segments,
        },
    )
    pre_submit_stage_durations_ms["task_registration"] = int((time.perf_counter() - task_registration_started) * 1000)

    submit_started = time.perf_counter()
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
            priority=("explicit" if is_to_me or speak_trigger in {"mention", "followup"} else "ambient"),
            token_count=token_count,
            temperature=temperature,
            knowledge_retrieval_trace=knowledge_retrieval_trace,
            hybrid_retrieval_trace=hybrid_retrieval_trace,
            include_session_history=include_persistent_history or include_recent_pair,
            session_history_limit=2 if include_recent_pair else None,
            include_group_ambient_history=not include_recent_pair,
            llm_rewrite_metadata={
                "task": "llm_chat",
                "current_turn_action": current_turn_decision.action,
                "bot_id": int(bot.self_id),
                "self_aliases": self_aliases[:8],
                "conversation_fallback_text": corpus_fallback,
                "command_source_segments": command_source_segments,
                "social_action": current_turn_decision.social_action,
                "reply_target": reply_target,
                "pre_submit_duration_ms": int((time.perf_counter() - route_started) * 1000),
                "pre_submit_stage_durations_ms": pre_submit_stage_durations_ms,
                "pre_submit_context_durations_ms": pre_submit_context_durations_ms,
                "semantic_style_direct_candidate": semantic_style.direct_candidate or None,
                "semantic_style_source_example_id": getattr(semantic_style, "source_example_id", "") or None,
            },
            tool_metadata=tool_meta,
        ),
        cfg=llm_cfg,
    )
    pre_submit_stage_durations_ms["submit"] = int((time.perf_counter() - submit_started) * 1000)
    if not result.ok:
        await TaskManager.remove_task(request_id)
        record_bot_llm_task(LLM_CHAT_TASK_TYPE, "submit_skip")
        from pallas.product.llm.submit_gate import user_message_for_submit_status

        hint = "" if result.status == "shared_budget_busy" else user_message_for_submit_status(result.status)
        if hint:
            await send_message(hint)
        logger.debug(
            format_plugin_event(
                "skip_generate",
                f"Bot [{bot.self_id}] skipped generating a reply for user [{user_id}] "
                f"in group [{group_id or '-'}]: {result.status}",
            )
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
