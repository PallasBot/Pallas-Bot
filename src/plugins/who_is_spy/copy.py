from __future__ import annotations

from nonebot.adapters.onebot.v11 import MessageSegment

from .commands import CMD_END, CMD_JOIN, CMD_OPEN, CMD_START, CMD_VOTE


def open_room_message(*, user_id: int, min_players: int) -> MessageSegment:
    return (
        MessageSegment.text("房已开，房主 ")
        + MessageSegment.at(user_id)
        + MessageSegment.text(f"。想玩发「{CMD_JOIN}」，至少 {min_players} 人时房主发「{CMD_START}」开局。")
    )


def join_ok(count: int) -> str:
    return f"已加入，共 {count} 人。"


def quit_ok(count: int) -> str:
    return f"已退出，还剩 {count} 人。"


def speak_phase_hint(*, round_no: int) -> str:
    return f"第 {round_no} 轮 · 自由描述，议完房主发「{CMD_VOTE}」开始投票。"


def start_game_hint(*, numbered: str, round_no: int = 1) -> str:
    return f"词已私聊发出。\n{speak_phase_hint(round_no=round_no)}\n{numbered}\n"


def role_word_private(*, role: str, word: str, show_role: bool) -> str:
    if show_role:
        return f"你的词：{word}（{role}）\n别在群里说。"
    return f"你的词：{word}\n别在群里说。"


def vote_invite_private(*, numbered: str) -> str:
    return f"{CMD_VOTE}\n私聊回复序号，0 弃权。\n\n{numbered}"


def vote_invite_email(*, numbered: str) -> str:
    return f"{CMD_VOTE}\n私聊回复序号，0 弃权。\n私聊没收到？看邮箱。\n\n{numbered}"


def role_word_email(*, role: str, word: str, show_role: bool) -> str:
    if show_role:
        body = f"你的词：{word}（{role}）\n"
    else:
        body = f"你的词：{word}\n"
    return "牛牛卧底 · 词牌\n" + body + "私聊没收到？看邮箱。别在群里说。"


def delivery_report(*, email_users: list[str], failed_users: list[str]) -> str:
    lines: list[str] = []
    if email_users:
        lines.append("以下改走邮箱：" + "、".join(email_users))
    if failed_users:
        lines.append("以下私聊未达：" + "、".join(failed_users) + "（请加好友）")
    return "\n".join(lines)


def speak_round_to_vote() -> str:
    return "进入投票，请看私聊。"


def vote_recorded(name: str) -> str:
    return f"已投给 {name}。"


def vote_abstained() -> str:
    return "已弃权。"


def game_over_tail() -> str:
    return f"本局结束。再来一局发「{CMD_OPEN}」。"


def vote_all_abstain() -> str:
    return f"全员弃权，重新讨论；房主发「{CMD_VOTE}」再投。"


def vote_tie() -> str:
    return f"最高票相同，重新讨论；房主发「{CMD_VOTE}」再投。"


def vote_eliminated_hidden(name: str) -> str:
    return f"{name} 出局。"


def vote_eliminated_reveal(*, name: str, role: str, summary: str) -> str:
    return f"{name} 出局，是{role}。\n{summary}"


def round_start(*, round_no: int, numbered: str) -> str:
    return f"{speak_phase_hint(round_no=round_no)}\n{numbered}"


def vote_stats_header() -> str:
    return "得票："


def vote_stats_abstain(count: int) -> str:
    return f"- 弃权 {count} 票"


def game_win_summary(
    *,
    headline: str,
    civilian_word: str,
    undercover_word: str,
    undercover_names: str,
) -> str:
    return f"{headline}\n平民词：{civilian_word}｜卧底词：{undercover_word}\n卧底：{undercover_names}"


def email_subject_words() -> str:
    return "[牛牛卧底] 你的词"


def email_subject_vote() -> str:
    return "[牛牛卧底] 请投票"


def status_panel(*, round_no: int, alive: int, numbered: str, voting: bool) -> str:
    lines = [f"第 {round_no} 轮 · {alive} 人在场", numbered]
    if voting:
        lines.append("投票：私聊回复序号，0 弃权。")
    else:
        lines.append(f"讨论中：房主发「{CMD_VOTE}」开始投票。")
    return "\n".join(lines)


def err_game_in_progress() -> str:
    return f"本群正在玩。要停发「{CMD_END}」。"


def err_room_busy() -> str:
    return f"本群已有房间。先「{CMD_END}」再开。"


def err_no_room() -> str:
    return f"还没开房，先发「{CMD_OPEN}」。"


def err_already_started_join() -> str:
    return "已经开局，不能再加入。"


def err_already_in_room() -> str:
    return "你已经在房间里了。"


def err_room_full(max_players: int) -> str:
    return f"房间满了（最多 {max_players} 人）。"


def err_no_room_quit() -> str:
    return "本群没有筹备中的房间。"


def err_cannot_quit_started() -> str:
    return "开局后不能退，只能等投票出局。"


def err_not_in_room() -> str:
    return "你不在房间里。"


def err_owner_cannot_quit() -> str:
    return f"房主不能退，要结束发「{CMD_END}」。"


def err_not_owner_start() -> str:
    return "只有房主能发词开局。"


def err_already_dealt() -> str:
    return "词已经发过了。"


def err_not_owner_vote() -> str:
    return f"只有房主能发「{CMD_VOTE}」。"


def err_already_voting() -> str:
    return "已经在投票了，请看私聊。"


def err_not_enough_players(min_players: int, count: int) -> str:
    return f"人数不够：至少 {min_players} 人，现在 {count} 人。"


def err_empty_word_bank() -> str:
    return "词库空了，稍后再试。"


def err_no_spy_room() -> str:
    return "本群没有卧底房间。"


def err_end_owner_only() -> str:
    return f"只有房主或群管能结束，请发「{CMD_END}」。"


def room_closed() -> str:
    return "房间已关。"


def pm_no_vote_pending() -> str:
    return "现在没有要你投票的局。"


def pm_already_voted() -> str:
    return "你这轮已经投过了。"


def pm_cannot_abstain_yet() -> str:
    return f"还没开始投票，等房主发「{CMD_VOTE}」。"


def pm_cannot_vote_yet() -> str:
    return f"还没开始投票，等房主发「{CMD_VOTE}」。"


def pm_invalid_index(numbered: str) -> str:
    return f"序号不对。回复下面名单里的数字，或 0 弃权。\n{numbered}"


def pm_target_gone() -> str:
    return "这个人已经出局了。"
