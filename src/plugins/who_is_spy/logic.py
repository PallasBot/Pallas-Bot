from __future__ import annotations

import asyncio
import random
from typing import TYPE_CHECKING

from src.platform.multi_bot.dedup import needs_group_host_bot_gate, release_group_owned_gate_sync

from .config import get_spy_config
from .coord_store import clear_game_snapshot, write_game_snapshot
from .copy import (
    email_subject_vote,
    email_subject_words,
    game_over_tail,
    game_win_summary,
    role_word_email,
    role_word_private,
    round_start,
    vote_all_abstain,
    vote_eliminated_hidden,
    vote_eliminated_reveal,
    vote_invite_email,
    vote_invite_private,
    vote_stats_abstain,
    vote_stats_header,
    vote_tie,
)
from .deliver import deliver_player_message
from .group_lock import clear_spy_room_session
from .store import WORD_BANK

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot

    from .models import Game

games: dict[int, Game] = {}


def sync_active_game(game: Game) -> None:
    if game.ready:
        write_game_snapshot(game)


async def get_nickname(bot: Bot, group_id: int, user_id: int) -> str:
    try:
        info = await bot.get_group_member_info(
            group_id=group_id,
            user_id=user_id,
            no_cache=True,
        )
        return info.get("card") or info.get("nickname") or str(user_id)
    except Exception:
        return str(user_id)


def current_alive_order(game: Game) -> list[int]:
    return [user_id for user_id in game.alive_order if game.players[user_id].is_alive]


def player_seat_no(game: Game, user_id: int) -> int:
    return game.alive_order.index(user_id) + 1


def build_index_map(game: Game) -> dict[int, int]:
    """本局固定座位号 → 玩家 uid（仅在场）。"""
    out: dict[int, int] = {}
    for user_id in game.alive_order:
        player = game.players.get(user_id)
        if player is None or not player.is_alive:
            continue
        out[player_seat_no(game, user_id)] = user_id
    return out


def render_alive_numbered(game: Game) -> str:
    index_map = build_index_map(game)
    lines = []
    for seat in sorted(index_map.keys()):
        user_id = index_map[seat]
        player = game.players[user_id]
        lines.append(f"{seat}. {player.nickname}")
    return "\n".join(lines)


def is_voting_phase(game: Game) -> bool:
    return bool(game.expecting_pm_vote) and game.vote_round_tag == game.round_no


def pick_words() -> tuple[str, str]:
    if not WORD_BANK:
        raise RuntimeError("词库为空，请检查 data/who_is_spy/undercover_words.json")
    return random.choice(WORD_BANK)


def assign_roles(game: Game, undercover_count: int) -> None:
    user_ids = list(game.players.keys())
    random.shuffle(user_ids)

    civilian_word, undercover_word = pick_words()
    if random.random() < 0.5:
        civilian_word, undercover_word = undercover_word, civilian_word

    game.word_civilian = civilian_word
    game.word_undercover = undercover_word

    for user_id in user_ids[:undercover_count]:
        game.players[user_id].is_undercover = True

    game.alive_order = user_ids.copy()
    random.shuffle(game.alive_order)


def player_role_word(game: Game, player) -> tuple[str, str]:
    if player.is_undercover:
        return "卧底", game.word_undercover
    return "平民", game.word_civilian


async def deliver_role_words(bot: Bot, game: Game, *, show_role: bool) -> tuple[list[str], list[str]]:
    email_names: list[str] = []
    failed_names: list[str] = []
    for player in game.players.values():
        role, word = player_role_word(game, player)
        private_text = role_word_private(role=role, word=word, show_role=show_role)
        email_body = role_word_email(role=role, word=word, show_role=show_role)
        outcome = await deliver_player_message(
            bot,
            group_id=game.group_id,
            user_id=player.uid,
            private_text=private_text,
            email_subject=email_subject_words(),
            email_body=email_body,
        )
        if outcome.channel == "email":
            email_names.append(player.nickname)
        elif not outcome.ok:
            failed_names.append(player.nickname)
    return email_names, failed_names


async def pm_invite_for_voting(bot: Bot, game: Game) -> tuple[list[str], list[str]]:
    numbered = render_alive_numbered(game)
    private_text = vote_invite_private(numbered=numbered)
    email_body = vote_invite_email(numbered=numbered)

    game.expecting_pm_vote = set(game.alive_ids())
    game.vote_round_tag = game.round_no

    email_names: list[str] = []
    failed_names: list[str] = []
    for user_id in game.expecting_pm_vote:
        outcome = await deliver_player_message(
            bot,
            group_id=game.group_id,
            user_id=user_id,
            private_text=private_text,
            email_subject=email_subject_vote(),
            email_body=email_body,
        )
        player = game.players[user_id]
        if outcome.channel == "email":
            email_names.append(player.nickname)
        elif not outcome.ok:
            failed_names.append(player.nickname)
    return email_names, failed_names


async def schedule_cleanup(group_id: int, delay: int | None = None) -> None:
    cleanup_sec = delay if delay is not None else get_spy_config().spy_room_cleanup_sec
    gid = int(group_id)
    try:
        await asyncio.sleep(cleanup_sec)
        game = games.get(gid)
        if game and not game.ready:
            games.pop(gid, None)
            clear_game_snapshot(gid)
            if needs_group_host_bot_gate():
                release_group_owned_gate_sync("who_is_spy", gid)
    except Exception:
        pass


async def settle_and_announce(bot: Bot, game: Game) -> None:
    group_id = game.group_id

    game.vote_box.clear()
    for target in game.votes.values():
        if target is None:
            continue
        game.vote_box[target] = game.vote_box.get(target, 0) + 1

    if not game.vote_box:
        await bot.send_group_msg(group_id=group_id, message=vote_all_abstain())
        game.reset_round_flags()
        sync_active_game(game)
        await bot.send_group_msg(
            group_id=group_id,
            message=round_start(round_no=game.round_no, numbered=render_alive_numbered(game)),
        )
        return

    index_map = build_index_map(game)
    inverse_index = {user_id: index for index, user_id in index_map.items()}

    abstain_count = sum(1 for vote in game.votes.values() if vote is None)

    lines = [vote_stats_header()]
    for user_id, count in sorted(
        game.vote_box.items(),
        key=lambda item: (-item[1], game.players[item[0]].nickname),
    ):
        index = inverse_index.get(user_id, "?")
        lines.append(f"- [{index}] {game.players[user_id].nickname}：{count} 票")
    if abstain_count:
        lines.append(vote_stats_abstain(abstain_count))
    await bot.send_group_msg(group_id=group_id, message="\n".join(lines))

    max_count = max(game.vote_box.values())
    top = [user_id for user_id, count in game.vote_box.items() if count == max_count]

    if len(top) >= 2:
        await bot.send_group_msg(group_id=group_id, message=vote_tie())
        game.reset_round_flags()
        sync_active_game(game)
        await bot.send_group_msg(
            group_id=group_id,
            message=round_start(round_no=game.round_no, numbered=render_alive_numbered(game)),
        )
        return

    eliminated = top[0]
    game.players[eliminated].is_alive = False
    eliminated_player = game.players[eliminated]
    role = "卧底" if eliminated_player.is_undercover else "平民"
    game_over = game.is_game_over()
    if game_over:
        undercover_names = [player.nickname for player in game.players.values() if player.is_undercover]
        summary = game_win_summary(
            headline=game_over,
            civilian_word=game.word_civilian,
            undercover_word=game.word_undercover,
            undercover_names=", ".join(undercover_names) if undercover_names else "无",
        )
        await bot.send_group_msg(
            group_id=group_id,
            message=vote_eliminated_reveal(
                name=eliminated_player.nickname,
                role=role,
                summary=summary,
            ),
        )

        game.ready = False
        game.expecting_pm_vote.clear()
        game.votes.clear()
        game.vote_box.clear()
        clear_spy_room_session(group_id)
        clear_game_snapshot(int(group_id))

        await bot.send_group_msg(group_id=group_id, message=game_over_tail())
        asyncio.create_task(schedule_cleanup(group_id))
        return

    await bot.send_group_msg(
        group_id=group_id,
        message=vote_eliminated_hidden(eliminated_player.nickname),
    )
    game.reset_round_flags()
    sync_active_game(game)
    await bot.send_group_msg(
        group_id=group_id,
        message=round_start(round_no=game.round_no, numbered=render_alive_numbered(game)),
    )
