#!/usr/bin/env python3
"""扫描并清洗 LLM 反哺样本 / behavior run / 晋升候选中的低质量条目。

用法:
  uv run python tools/clean_llm_feedback.py --dry-run
  uv run python tools/clean_llm_feedback.py --apply
  uv run python tools/clean_llm_feedback.py --apply --restore-length-only-runs
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pallas.core.platform.ai_callback.task_types import (  # noqa: E402
    LLM_CHAT_TASK_TYPE,
    REPEATER_SELECT_TASK_TYPE,
)
from pallas.product.llm.behavior import BehaviorOutcome  # noqa: E402
from pallas.product.llm.behavior_store import _runs_path, list_behavior_runs  # noqa: E402
from pallas.product.llm.corpus_contamination import FEEDBACK_META_BLOCK_PHRASES  # noqa: E402
from pallas.product.llm.feedback_learning import is_reply_safe_for_shaped_writeback  # noqa: E402
from pallas.product.llm.promotion_candidates import (  # noqa: E402
    _load_candidates_index,
    _write_candidates_index,
)
from pallas.product.llm.repeater_feedback import (  # noqa: E402
    _BLOCKED_SOURCE_TAGS,
    _MAX_REPLY_LEN,
    LlmRepeaterFeedbackEntry,
    _load_all_feedback_entries,
    _write_feedback_entries,
    feedback_reply_max_len,
    is_reply_safe_for_auto_promote,
    is_systemish_promote_text,
    should_collect_llm_repeater_feedback,
)

# 原 _BLOCKED_REPLY_HINTS，已迁至 corpus_contamination.FEEDBACK_META_BLOCK_PHRASES
_BLOCKED_REPLY_HINTS = FEEDBACK_META_BLOCK_PHRASES
from pallas.product.persona.dynamic_expression import (  # noqa: E402
    clean_expression_reference_text,
    is_usable_expression_reference,
)

_CQ_RE = re.compile(r"\[CQ:[^\]]+\]", re.IGNORECASE)
_EMOJI_ONLY_RE = re.compile(r"^[\U0001F300-\U0001FAFF\s\u2600-\u27BF]+$")
_ASCII_ONLY_RE = re.compile(r"^[A-Za-z0-9_\-\.~!?]+$")
_PUNCT_STRIP = re.compile(r"[\s\u3000，,。！!？?：:;；~～…\.·]+")
_KAOMOJI_SUFFIX_RE = re.compile(r"\(\*[^)]{1,16}\*\)\s*$")
_BRACKET_FACE_RE = re.compile(r"\[(嘻嘻|害羞|doge|png|捂脸|呲牙|微笑|期待)\]", re.IGNORECASE)
_EMOJI_SPAM_RE = re.compile(r"(🌟|🌈|✨|🎉|🚀|📈|💖){2,}")
_GARBAGE_FRAGMENTS = re.compile(r"(规哦|油哦|来嘛来嘛|来，喝杯酒|喝杯酒庆祝)")
_CQ_FACE_RE = re.compile(r"\[CQ:face", re.IGNORECASE)

_CORPUS_ROUTES = frozenset({"corpus_select", "corpus_fallback"})
_POLISH_ROUTES = frozenset({"corpus_polish", "corpus_polish_lite"})

_RELATIONSHIP_PHRASES = (
    "关系我记下",
    "这层关系",
    "好的博士",
    "我记下了",
    "已记录这层",
    "我会记住",
    "注意到您了",
    "谢谢您的陪伴",
    "有什么可以帮到您",
)
_DRAW_FRAGMENTS = {"画一", "帮我", "帮你画", "画点", "来画", "我画"}
_MEME_OK = frozenset({
    "666",
    "6",
    "草",
    "行",
    "好",
    "嗯",
    "哦",
    "啊",
    "哈",
    "呵",
    "嘻",
    "赞",
    "牛",
    "可以",
    "确实",
    "对的",
    "是吧",
    "233",
    "ok",
    "OK",
    "xd",
    "马萨卡",
    "爱了",
    "不看",
    "没钱",
    "tql",
    "nb",
    "yyds",
    "蚌",
    "典",
    "乐",
    "笑",
    "举个手",
    "你好呀",
    "你好呀。",
    "摸摸",
    "摸摸。",
    "喵喵喵",
    "本人吗",
    "你有点小帅",
    "看不懂捏",
    "我也是萌新",
    "网还没起来呢",
    "注意一下群规哈",
})
_QUESTION_MARKERS = (
    "?",
    "？",
    "吗",
    "么",
    "怎么",
    "为何",
    "为什么",
    "为啥",
    "哪",
    "谁",
    "啥",
    "几",
    "能不能",
    "可不可以",
)
_SERVICEY_TOKENS = (
    "博士您",
    "博士觉得",
    "博士，",
    "有什么可以帮",
    "帮到您",
    "谢谢您的陪伴",
    "希望每个庆典",
    "随时准备好",
    "有啥好玩",
    "想和我聊聊",
    "想和我聊",
    "想聊聊吗",
    "分享一下",
    "趣事想分享",
    "庆典感满满",
    "活动或者干员",
    "到您的吗",
    "七深甜品",
    "nnm的商店",
    "吃甜点",
    "发“吃甜点”",
    "帕拉斯随时",
    "准备好了就",
    "一起喊起来吧",
    "有什么想说的吗",
    "有什么想聊的",
    "来聊聊",
    "聊聊吗",
    "随时准备好了",
    "祝您",
    "陪伴",
    "为您服务",
    "很荣幸",
    "如有其他问题",
    "姚雨墨",
    "准备好了就一起",
    "有什么可以帮到你的",
)
_SOFT_TEMPLATE = (
    "聊聊",
    "散心",
    "说说看",
    "说说",
    "发生了什么事",
    "需要聊聊",
    "好好说",
    "咱们好好说",
    "干员的故事",
    "哪个干员",
    "了解哪个",
    "构造体",
    "前线情况",
    "收到指令",
    "正在考虑",
    "挺聊得开心",
    "换个话题",
    "别生气嘛",
    "心情不太好",
    "发生了什么",
    "一起想想办法",
    "精神点",
    "乐子事儿",
    "开心点",
    "想先了解",
    "了解一下",
    "说说您的",
    "新鲜事吗",
    "有什么新鲜",
    "跟我聊聊",
    "咱们可以",
    "别太较真",
    "最近怎么样",
    "怎么样？",
    "怎么样",
    "期待下次",
    "一起玩哦",
)
_GAME_TOKENS = ("干员", "构造体", "庆典", "前线", "终端", "指挥官", "博士", "罗德岛", "明日方舟")
_INSULT_MARKERS = ("屎", "滚", "爬", "死", "贱", "操", "妈", "傻逼", "人机", "犯法")
_TASK_FOR_ROUTE = {
    "corpus_select": REPEATER_SELECT_TASK_TYPE,
    "corpus_fallback": "repeater_fallback",
    "corpus_polish": "repeater_polish",
    "corpus_polish_lite": "repeater_polish_lite",
    "plain_llm_chat": LLM_CHAT_TASK_TYPE,
}
_QUALITY_BAD_RUN_LABELS = {
    "含CQ码",
    "@自复读",
    "空回复",
    "完全复读",
    "复读用户句",
    "关系/客服腔",
    "说教腔",
    "LLM灌水复读",
    "过短碎片",
    "长问短答",
    "语境脱节",
    "语料半句误命中",
    "标点复读",
    "非接话来源",
    "客服/模板腔",
    "强行续聊",
    "接话不贴题",
    "润色跑题",
    "垃圾碎片",
    "emoji堆砌",
    "颜文字尾",
    "括号表情",
    "软续聊模板",
    "游戏客服腔",
    "骂战乱接",
    "塑形写回不安全",
    "LLM模板续聊",
    "短触发长灌水",
    "CQ残留",
    "答非所问",
    "auto_clean",
    "auto_clean_full_scan",
    "auto_clean_pass2",
    "auto_clean_pass3",
}


def strip_cq(text: str) -> str:
    return re.sub(r"\s+", " ", _CQ_RE.sub("", text or "")).strip()


def cjk(text: str) -> str:
    return re.sub(r"[^\u4e00-\u9fff]", "", text or "")


def norm_echo(text: str) -> str:
    return _PUNCT_STRIP.sub("", strip_cq(text)).lower()


def bigrams(text: str) -> set[str]:
    s = cjk(text)
    if len(s) < 2:
        return {s} if s else set()
    return {s[i : i + 2] for i in range(len(s) - 1)}


def bigram_overlap(left: str, right: str) -> float:
    left_bg, right_bg = bigrams(left), bigrams(right)
    if not left_bg or not right_bg:
        return 1.0 if cjk(left) == cjk(right) and cjk(left) else 0.0
    return len(left_bg & right_bg) / max(1, min(len(left_bg), len(right_bg)))


def shared_cjk(left: str, right: str) -> bool:
    left_set = {char for char in left if "\u4e00" <= char <= "\u9fff"}
    right_set = {char for char in right if "\u4e00" <= char <= "\u9fff"}
    return bool(left_set & right_set)


def is_llm_long_reply(route: str, plain: str) -> bool:
    route_key = str(route or "").strip()
    if route_key in _CORPUS_ROUTES:
        return False
    if route_key in _POLISH_ROUTES and len(plain) <= 20:
        return False
    return len(plain) > 20 or route_key.startswith("plain_")


def is_meme_ok(plain: str) -> bool:
    trimmed = plain.rstrip("。！!？?~～")
    return plain in _MEME_OK or trimmed in _MEME_OK


def is_natural_short_corpus_reply(*, user: str, plain: str) -> bool:
    """短接话产品形态：2～8 字、有汉字、可贴题或在 meme 白名单，不算「过短碎片」。"""
    if is_meme_ok(plain):
        return True
    cleaned = clean_expression_reference_text(plain)
    if not cleaned or len(cleaned) > 8:
        return False
    if len(cleaned) < 2:
        return False
    cjk = sum(1 for char in cleaned if "\u4e00" <= char <= "\u9fff")
    if cjk < 1:
        return False
    if is_usable_expression_reference(cleaned, min_len=2, min_cjk=1):
        return True
    # 「懂了」「然后呢」等：有用户侧字重叠或极短自然应答
    if shared_cjk(user, cleaned) and cjk >= 1:
        return True
    if 2 <= len(cleaned) <= 4 and cjk >= 2:
        return True
    return False


def classify_bad_entry(entry: LlmRepeaterFeedbackEntry) -> list[str]:
    """Return human-readable reasons; empty list means keep eligible."""
    reasons: list[str] = []
    user = str(entry.user_text or "").strip()
    reply = str(entry.reply_text or "").strip()
    plain = strip_cq(reply)
    route = str(entry.llm_route or "").strip()
    tags = {str(tag).strip().lower() for tag in entry.source_tags if str(tag).strip()}

    if not reply:
        return ["空回复"]
    if len(reply) > _MAX_REPLY_LEN and route in _CORPUS_ROUTES | _POLISH_ROUTES:
        reasons.append("超长回复")
    if tags & _BLOCKED_SOURCE_TAGS:
        reasons.append("非接话来源")
    if any(hint in reply for hint in _BLOCKED_REPLY_HINTS):
        reasons.append("说教腔")
    if "[CQ:" in reply.upper():
        reasons.append("含CQ码")
    if _CQ_FACE_RE.search(reply):
        reasons.append("CQ残留")
    if any(phrase in reply for phrase in _RELATIONSHIP_PHRASES):
        reasons.append("关系/客服腔")
    if _EMOJI_ONLY_RE.match(plain) and plain:
        reasons.append("纯表情")
    if _ASCII_ONLY_RE.match(plain) and len(plain) <= 8 and plain.lower() not in {x.lower() for x in _MEME_OK}:
        reasons.append("纯ASCII碎片")
    if plain.isdigit() or re.fullmatch(r"[\d\s]+", plain):
        reasons.append("纯数字")

    user_norm, reply_norm = norm_echo(user), norm_echo(plain)
    if user and user_norm and reply_norm == user_norm:
        reasons.append("完全复读")
    elif not is_llm_long_reply(route, plain):
        if user and len(user) >= 4 and user in plain:
            reasons.append("复读用户句")
        elif user and len(user_norm) >= 3 and len(reply_norm) <= len(user_norm) + 2 and reply_norm == user_norm:
            reasons.append("标点复读")
    elif user and len(user) >= 6 and plain.startswith(user[: min(8, len(user))]) and len(plain) > len(user) + 12:
        if any(token in plain for token in ("分享", "趣事", "好玩", "庆祝", "加油", "希望每个")):
            reasons.append("LLM灌水复读")

    if plain in _DRAW_FRAGMENTS or ("画" in user and plain in _DRAW_FRAGMENTS):
        reasons.append("画画半句")

    if route in _CORPUS_ROUTES or (route in _POLISH_ROUTES and len(plain) <= 16):
        if not is_natural_short_corpus_reply(user=user, plain=plain):
            if len(plain) <= 8:
                reasons.append("过短碎片")

    if not is_llm_long_reply(route, plain):
        user_cjk = sum(1 for char in user if "\u4e00" <= char <= "\u9fff")
        if user_cjk >= 4 and len(plain) <= 3 and not is_natural_short_corpus_reply(user=user, plain=plain):
            reasons.append("长问短答")
        if len(user) >= 18 and len(plain) <= 5 and not is_meme_ok(plain) and not shared_cjk(user, plain):
            if any(marker in user for marker in _QUESTION_MARKERS) or user_cjk >= 6:
                reasons.append("语境脱节")
        if route in _CORPUS_ROUTES and user and plain and len(user) >= 8:
            if plain in user and len(plain) <= max(4, len(user) // 4):
                reasons.append("语料半句误命中")

    if "为什么要@自己" in user or ("CQ:AT" in reply.upper() and user and norm_echo(user) in norm_echo(plain)):
        reasons.append("@自复读")

    if not reasons:
        if not is_reply_safe_for_shaped_writeback(plain) and not route.startswith("plain"):
            reasons.append("塑形写回不安全")
        if _KAOMOJI_SUFFIX_RE.search(reply):
            reasons.append("颜文字尾")
        if _BRACKET_FACE_RE.search(reply):
            reasons.append("括号表情")
        if _EMOJI_SPAM_RE.search(reply):
            reasons.append("emoji堆砌")
        if _GARBAGE_FRAGMENTS.search(plain):
            reasons.append("垃圾碎片")
        if any(token in reply for token in _SERVICEY_TOKENS):
            reasons.append("客服/模板腔")

    if not reasons:
        if is_llm_long_reply(route, plain):
            if plain.count("？") + plain.count("?") >= 2:
                reasons.append("强行续聊")
            if len(plain) > 45 and any(token in plain for token in ("聊聊", "分享", "好玩", "干员", "庆典")):
                reasons.append("LLM模板续聊")
            if user and len(user) <= 4 and len(plain) > 35:
                reasons.append("短触发长灌水")

        if route in _POLISH_ROUTES and user and len(user) <= 8 and len(plain) > 22:
            if not shared_cjk(user, plain) or plain.count("？") >= 1:
                reasons.append("润色跑题")

        if route in _CORPUS_ROUTES and len(user) >= 10 and 4 <= len(plain) <= 10:
            if not shared_cjk(user, plain) and plain not in _MEME_OK:
                reasons.append("接话不贴题")

        task = _TASK_FOR_ROUTE.get(route, LLM_CHAT_TASK_TYPE if route.startswith("plain") else "")
        if task:
            max_allowed = feedback_reply_max_len(task_type=task, llm_route=route)
            clipped = plain if len(plain) <= max_allowed else plain[:max_allowed]
            if not should_collect_llm_repeater_feedback(
                task_type=task,
                group_id=entry.group_id,
                user_text=user,
                reply_text=clipped,
                source_tags=entry.source_tags,
                llm_route=route,
            ):
                if len(plain) <= max_allowed or not route.startswith("plain"):
                    reasons.append("反哺不应收录")

    if not reasons:
        if any(token in reply for token in _SOFT_TEMPLATE):
            if "？" in plain or "?" in plain or plain.endswith(("吗", "吗？")):
                reasons.append("软续聊模板")
            elif is_llm_long_reply(route, plain):
                reasons.append("软续聊模板")

        if is_llm_long_reply(route, plain):
            game_hits = [token for token in _GAME_TOKENS if token in plain]
            if game_hits and not any(token in user for token in game_hits):
                reasons.append("游戏客服腔")

        if route in _CORPUS_ROUTES | _POLISH_ROUTES:
            trimmed = plain.rstrip("。！!？?~～")
            if len(user) >= 8 and 3 <= len(trimmed) <= 14 and trimmed not in _MEME_OK:
                if bigram_overlap(user, plain) < 0.15:
                    reasons.append("接话不贴题")
            if any(marker in user for marker in _INSULT_MARKERS) and len(plain) >= 4 and trimmed not in _MEME_OK:
                if bigram_overlap(user, plain) < 0.2:
                    reasons.append("骂战乱接")

        if route in _POLISH_ROUTES and len(user) <= 6 and len(plain) > 18:
            if bigram_overlap(user, plain) < 0.1:
                reasons.append("润色跑题")

        if len(re.findall(r"[\U0001F300-\U0001FAFF]", reply)) >= 2 and (
            is_llm_long_reply(route, plain) or route in _POLISH_ROUTES
        ):
            reasons.append("emoji堆砌")

        if user and any(q in user for q in ("什么", "哪种", "哪个", "是不是")) and is_llm_long_reply(route, plain):
            game_in_reply = any(token in plain for token in _GAME_TOKENS)
            game_in_user = any(token in user for token in _GAME_TOKENS)
            if bigram_overlap(user, plain) < 0.08 and not (game_in_reply and game_in_user):
                reasons.append("答非所问")

    deduped: list[str] = []
    for reason in reasons:
        if reason not in deduped:
            deduped.append(reason)
    return deduped


def infer_run_route(reply_text: str) -> str:
    if len(str(reply_text or "")) > 32:
        return "plain_llm_chat"
    return "corpus_select"


def entry_from_run(run) -> LlmRepeaterFeedbackEntry:
    return LlmRepeaterFeedbackEntry(
        entry_id=run.request_id,
        created_at=int(run.created_at or 0),
        bot_id=int(run.bot_id or 0),
        group_id=int(run.group_id or 0),
        user_id=int(run.user_id or 0),
        request_id=run.request_id,
        user_text=str(run.user_text or ""),
        reply_text=str(run.reply_text or ""),
        llm_route=infer_run_route(run.reply_text or ""),
    )


def restore_length_only_runs(runs) -> int:
    restored = 0
    for idx, run in enumerate(runs):
        if not run.disabled:
            continue
        labels = set(run.manual_labels or [])
        if labels & _QUALITY_BAD_RUN_LABELS:
            continue
        if not (labels <= {"超长回复", "auto_clean_full_scan"}):
            continue
        user = str(run.user_text or "").strip()
        reply = str(run.reply_text or "").strip()
        if not user or not reply or "[CQ:" in reply.upper():
            continue
        run.disabled = False
        skip_labels = {"auto_clean_full_scan", "超长回复"}
        run.manual_labels = [label for label in (run.manual_labels or []) if label not in skip_labels]
        if run.final_outcome == BehaviorOutcome.AWKWARD or run.final_outcome == "awkward":
            run.final_outcome = None
        runs[idx] = run
        restored += 1
    return restored


def run_cleanup(*, apply: bool, restore_length_only: bool, preview_limit: int) -> int:
    entries = _load_all_feedback_entries()
    runs = list_behavior_runs(limit=10_000)
    candidates = _load_candidates_index()

    if restore_length_only and apply:
        restored = restore_length_only_runs(runs)
        print(f"恢复仅因超长误伤的 behavior run: {restored}")

    fb_hits: list[tuple[LlmRepeaterFeedbackEntry, list[str]]] = []
    reason_counter: Counter[str] = Counter()
    for entry in entries:
        if not entry.eligible_for_bias:
            continue
        reasons = classify_bad_entry(entry)
        if not reasons:
            continue
        fb_hits.append((entry, reasons))
        for reason in reasons:
            reason_counter[reason] += 1

    fix_ids = {entry.request_id for entry, _ in fb_hits}
    run_hits = 0
    for run in runs:
        if run.disabled:
            continue
        reasons = classify_bad_entry(entry_from_run(run))
        if not reasons and run.request_id not in fix_ids:
            continue
        if reasons == ["反哺不应收录"] and len(str(run.reply_text or "")) > 32:
            continue
        run_hits += 1

    cand_hits = 0
    for candidate in candidates.values():
        if candidate.promoted or candidate.rejected_reason:
            continue
        fake = LlmRepeaterFeedbackEntry(
            entry_id=candidate.candidate_id,
            created_at=0,
            bot_id=0,
            group_id=int(candidate.group_id or 0),
            user_id=0,
            request_id=candidate.candidate_id,
            user_text=str(candidate.trigger_text or ""),
            reply_text=str(candidate.reply_text or ""),
            llm_route="corpus_select",
        )
        if (
            classify_bad_entry(fake)
            or is_systemish_promote_text(str(candidate.trigger_text or ""), str(candidate.reply_text or ""))
            or not is_reply_safe_for_auto_promote(
                candidate.reply_text,
                trigger_text=str(candidate.trigger_text or ""),
            )
        ):
            cand_hits += 1

    inv_before = sum(1 for entry in entries if not entry.eligible_for_bias)
    print("=== clean_llm_feedback ===")
    print(f"反哺 eligible 待禁: {len(fb_hits)}")
    print(f"behavior run 待禁: {run_hits}")
    print(f"晋升候选待 reject: {cand_hits}")
    print(f"原因分布: {dict(reason_counter.most_common(20))}")
    print()
    for entry, reasons in fb_hits[:preview_limit]:
        print(f"[{','.join(reasons)}] Q:{entry.user_text[:32]!r} A:{entry.reply_text[:40]!r} route={entry.llm_route}")
    if len(fb_hits) > preview_limit:
        print(f"... 另有 {len(fb_hits) - preview_limit} 条")

    if not apply:
        print("\n(dry-run，未写入；加 --apply 执行)")
        return 0

    for idx, entry in enumerate(entries):
        if entry.request_id not in fix_ids:
            continue
        entry.eligible_for_bias = False
        entries[idx] = entry

    run_changed = 0
    for idx, run in enumerate(runs):
        if run.disabled:
            continue
        reasons = classify_bad_entry(entry_from_run(run))
        if run.request_id in fix_ids and not reasons:
            reasons = ["auto_clean_tool"]
        if not reasons:
            continue
        if reasons == ["反哺不应收录"] and len(str(run.reply_text or "")) > 32:
            continue
        run.disabled = True
        run.manual_labels = list(dict.fromkeys([*(run.manual_labels or []), *reasons, "auto_clean_tool"]))
        if run.final_outcome is None:
            run.final_outcome = BehaviorOutcome.AWKWARD
        runs[idx] = run
        run_changed += 1

    cand_changed = 0
    for cid, candidate in list(candidates.items()):
        if candidate.promoted or candidate.rejected_reason:
            continue
        fake = LlmRepeaterFeedbackEntry(
            entry_id=cid,
            created_at=0,
            bot_id=0,
            group_id=int(candidate.group_id or 0),
            user_id=0,
            request_id=cid,
            user_text=str(candidate.trigger_text or ""),
            reply_text=str(candidate.reply_text or ""),
            llm_route="corpus_select",
        )
        if (
            classify_bad_entry(fake)
            or is_systemish_promote_text(str(candidate.trigger_text or ""), str(candidate.reply_text or ""))
            or not is_reply_safe_for_auto_promote(
                candidate.reply_text,
                trigger_text=str(candidate.trigger_text or ""),
            )
        ):
            candidate.rejected_reason = "auto_clean_tool"
            candidates[cid] = candidate
            cand_changed += 1

    _write_feedback_entries(entries)
    from pallas.core.foundation.fs_lock import atomic_write_text, interprocess_file_lock

    runs_path = _runs_path()
    runs_body = "".join(json.dumps(item.model_dump(mode="json"), ensure_ascii=False) + "\n" for item in runs)
    with interprocess_file_lock(runs_path.with_suffix(runs_path.suffix + ".lock")):
        atomic_write_text(runs_path, runs_body)
    if cand_changed:
        _write_candidates_index(candidates)

    inv_after = sum(1 for entry in entries if not entry.eligible_for_bias)
    dis_after = sum(1 for run in runs if run.disabled)
    print()
    print(f"已写入: 反哺 invalidate +{inv_after - inv_before} (累计 {inv_after}/{len(entries)})")
    print(f"behavior run 禁用 +{run_changed} (累计 disabled {dis_after}/{len(runs)})")
    print(f"候选 reject +{cand_changed}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="只统计与预览，不写盘")
    mode.add_argument("--apply", action="store_true", help="执行清洗并写盘")
    parser.add_argument(
        "--restore-length-only-runs",
        action="store_true",
        help="与 --apply 同用：恢复仅因超长误伤的 behavior run",
    )
    parser.add_argument("--preview", type=int, default=20, help="预览条数")
    args = parser.parse_args()
    return run_cleanup(
        apply=args.apply,
        restore_length_only=args.restore_length_only_runs,
        preview_limit=max(0, int(args.preview)),
    )


if __name__ == "__main__":
    raise SystemExit(main())
