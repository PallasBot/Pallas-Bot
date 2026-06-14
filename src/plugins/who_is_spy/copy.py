from __future__ import annotations

from nonebot.adapters.onebot.v11 import MessageSegment

from .commands import CMD_END, CMD_JOIN, CMD_OPEN, CMD_START


def open_room_message(*, user_id: int) -> MessageSegment:
    return (
        MessageSegment.text("房间已开，房主 ")
        + MessageSegment.at(user_id)
        + MessageSegment.text(f"。发「{CMD_JOIN}」加入，人满后房主发「{CMD_START}」开局。")
    )


def join_ok(count: int) -> str:
    return f"已加入，当前 {count} 人。"


def quit_ok(count: int) -> str:
    return f"已退出，当前 {count} 人。"


def start_game_hint(*, player_names: str) -> str:
    return (
        "词牌已私聊发放。\n"
        "群内可自由聊天；按名册顺序 @牛牛 述词，全员述毕后私聊数字投票（0 弃权）。\n"
        f"在场：{player_names}"
    )


def speak_turn_prompt(*, user_id: int, round_no: int | None = None) -> MessageSegment:
    if round_no is None:
        head = "请 "
    else:
        head = f"第 {round_no} 轮 · 请 "
    return (
        MessageSegment.text(head)
        + MessageSegment.at(user_id)
        + MessageSegment.text(" @牛牛 述词。")
    )


def speak_wait_turn(*, user_id: int) -> MessageSegment:
    return (
        MessageSegment.text("还没轮到你。请等待 ")
        + MessageSegment.at(user_id)
        + MessageSegment.text(" @牛牛 述词。")
    )


def role_word_private(*, role: str, word: str, show_role: bool) -> str:
    if show_role:
        return f"【{role}】{word}\n请勿在群内泄露。"
    return f"词牌：{word}\n请勿在群内泄露。"


def vote_invite_private(*, numbered: str) -> str:
    return f"【牛牛卧底 · 投票】回复数字投票，0 弃权。\n\n{numbered}"


def vote_invite_email(*, numbered: str) -> str:
    return f"牛牛卧底 · 投票\n私聊未达，改由邮箱说明。请私聊回复数字投票，0 弃权。\n\n{numbered}"


def role_word_email(*, role: str, word: str, show_role: bool) -> str:
    head = "牛牛卧底 · 词牌\n"
    if show_role:
        body = f"【{role}】{word}\n"
    else:
        body = f"词牌：{word}\n"
    return head + body + "私聊未达，改由邮箱递词。请勿在群内泄露。"


def delivery_report(*, email_users: list[str], failed_users: list[str]) -> str:
    lines: list[str] = []
    if email_users:
        lines.append("以下改由邮箱收词/票：" + "、".join(email_users))
    if failed_users:
        lines.append("未能私聊：" + "、".join(failed_users) + "（请加好友或从群内发起会话）")
    return "\n".join(lines)


def speak_already() -> str:
    return "本轮你已述词过。"


def speak_round_to_vote() -> str:
    return "述词结束，请留意私聊投票。"


def vote_recorded(name: str) -> str:
    return f"已投「{name}」。"


def game_over_tail() -> str:
    return f"本局结束。再开一局发「{CMD_OPEN}」。"


def vote_all_abstain() -> str:
    return "全员弃权，请重新述词。"


def vote_tie() -> str:
    return "最高票并列，请重新述词。"


def vote_eliminated_hidden(name: str) -> str:
    return f"{name} 出局。"


def vote_eliminated_reveal(*, name: str, role: str, summary: str) -> str:
    return f"{name} 出局，身份为【{role}】。\n{summary}"


def round_start(round_no: int) -> str:
    return f"第 {round_no} 轮，按顺序 @牛牛 述词。"


def vote_stats_header() -> str:
    return "票型："


def vote_stats_abstain(count: int) -> str:
    return f"- 弃权：{count} 票"


def game_win_summary(
    *,
    headline: str,
    civilian_word: str,
    undercover_word: str,
    undercover_names: str,
) -> str:
    return (
        f"{headline}\n"
        f"平民词：{civilian_word}\n"
        f"卧底词：{undercover_word}\n"
        f"卧底：{undercover_names}"
    )


def email_subject_words() -> str:
    return "[牛牛卧底] 词牌"


def email_subject_vote() -> str:
    return "[牛牛卧底] 投票说明"


def status_panel(*, round_no: int, alive: int, numbered: str, voting: bool) -> str:
    lines = [f"第 {round_no} 轮 · 在场 {alive} 人", f"序次：\n{numbered}"]
    if voting:
        lines.append("投票请私聊回复数字，0 弃权。")
    else:
        lines.append("按顺序 @牛牛 述词，群内可自由聊天。")
    return "\n".join(lines)


def err_game_in_progress() -> str:
    return f"本群已有对局。中止请发「{CMD_END}」。"


def err_room_busy() -> str:
    return f"本群已有房间占位（或重启后遗留）。群管/房主可发「{CMD_END}」清理后再开。"


def err_no_room() -> str:
    return f"尚无房间，请先「{CMD_OPEN}」。"


def err_already_started_join() -> str:
    return "词牌已发，不能再加入。"


def err_already_in_room() -> str:
    return "你已在名册上。"


def err_room_full(max_players: int) -> str:
    return f"名册已满（上限 {max_players}）。"


def err_no_room_quit() -> str:
    return "本群没有筹备中的房间。"


def err_cannot_quit_started() -> str:
    return "已开始，不可退——唯有被投票出局。"


def err_not_in_room() -> str:
    return "你不在名册上。"


def err_owner_cannot_quit() -> str:
    return f"房主不可退出。结束请「{CMD_END}」。"


def err_not_owner_start() -> str:
    return "仅房主可发词牌。"


def err_already_dealt() -> str:
    return "词牌已分过。"


def err_not_enough_players(min_players: int, count: int) -> str:
    return f"人数不足（至少 {min_players} 人，现 {count} 人）。"


def err_empty_word_bank() -> str:
    return "暂无可用词牌。"


def err_no_spy_room() -> str:
    return "本群没有房间。"


def err_end_owner_only() -> str:
    return f"仅房主或群管可结束。请房主发「{CMD_END}」。"


def room_closed() -> str:
    return "房间已关闭。"


def pm_no_vote_pending() -> str:
    return "此刻没有待你投票的局。"


def pm_already_voted() -> str:
    return "你本轮已投过，不可改。"


def pm_cannot_abstain_yet() -> str:
    return "仍在述词阶段，尚不可弃权。"


def pm_cannot_vote_yet() -> str:
    return "仍在述词阶段，尚不可投票。"


def pm_invalid_index(numbered: str) -> str:
    return f"无效序次。回复名单中的数字，或 0 弃权。\n{numbered}"


def pm_target_gone() -> str:
    return "该目标已不在场。"
