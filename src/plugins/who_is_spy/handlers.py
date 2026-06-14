from nonebot import logger, on_command, on_message
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, PrivateMessageEvent
from nonebot.adapters.onebot.v11.permission import PRIVATE
from nonebot.params import CommandArg
from nonebot.rule import Rule

from src.features.cmd_perm import group_message_permission_for_command
from src.platform.multi_bot.group import (
    bind_group_owned_gate,
    claim_group_message_event,
    is_group_owned_gate_holder,
    needs_group_host_bot_gate,
    try_acquire_group_broadcast_slot,
)
from src.platform.shard.coord.spy_activity import SPY_OWNED_PLUGIN

from .args import parse_undercover_count
from .commands import CMD_END, CMD_JOIN, CMD_OPEN, CMD_QUIT, CMD_START, CMD_STATUS, CMD_VOTE
from .config import get_spy_config
from .copy import (
    delivery_report,
    err_already_dealt,
    err_already_in_room,
    err_already_started_join,
    err_already_voting,
    err_cannot_quit_started,
    err_empty_word_bank,
    err_end_owner_only,
    err_game_in_progress,
    err_no_room,
    err_no_room_quit,
    err_no_spy_room,
    err_not_enough_players,
    err_not_in_room,
    err_not_owner_start,
    err_not_owner_vote,
    err_owner_cannot_quit,
    err_room_busy,
    err_room_full,
    join_ok,
    open_room_message,
    pm_already_voted,
    pm_cannot_abstain_yet,
    pm_cannot_vote_yet,
    pm_invalid_index,
    pm_no_vote_pending,
    pm_target_gone,
    quit_ok,
    room_closed,
    speak_round_to_vote,
    start_game_hint,
    status_panel,
    vote_abstained,
    vote_recorded,
)
from .group_lock import SPY_GROUP_LOCK, mark_spy_prep_room
from .logic import (
    assign_roles,
    build_index_map,
    deliver_role_words,
    get_nickname,
    is_voting_phase,
    pm_invite_for_voting,
    render_alive_numbered,
    settle_and_announce,
)
from .models import Game, Player
from .session import (
    SPY_HOST_GATE_SEC,
    begin_spy_room,
    bind_local_game,
    close_spy_room,
    group_key,
    load_local_game,
    load_local_prep_game,
    mark_spy_room_active,
    persist_game,
    persist_prep,
    resolve_game_sync,
)
from .store import WORD_BANK

PLUGIN_KEY = SPY_OWNED_PLUGIN
OPEN_PERM = group_message_permission_for_command("who_is_spy.open")
JOIN_PERM = group_message_permission_for_command("who_is_spy.join")
START_PERM = group_message_permission_for_command("who_is_spy.start")
STATUS_PERM = group_message_permission_for_command("who_is_spy.status")
END_PERM = group_message_permission_for_command("who_is_spy.end")

cmd_open = on_command(
    CMD_OPEN,
    aliases={"牛牛谁是卧底"},
    block=True,
    priority=10,
    permission=OPEN_PERM,
)
cmd_join = on_command(CMD_JOIN, block=True, priority=10, permission=JOIN_PERM)
cmd_quit = on_command(CMD_QUIT, block=True, priority=10, permission=JOIN_PERM)
cmd_start = on_command(CMD_START, aliases={"牛牛开始"}, block=True, priority=10, permission=START_PERM)
cmd_vote = on_command(CMD_VOTE, block=True, priority=10, permission=START_PERM)
cmd_status = on_command(CMD_STATUS, block=True, priority=10, permission=STATUS_PERM)
cmd_end = on_command(CMD_END, block=True, priority=5, permission=END_PERM)


async def claim_group_event(event: GroupMessageEvent) -> bool:
    claimed = await claim_group_message_event(
        PLUGIN_KEY,
        event,
        int(event.self_id),
        include_message_time=True,
    )
    if not claimed:
        logger.warning(
            "who_is_spy: claim lost bot={} group={} user={} text={!r}",
            event.self_id,
            event.group_id,
            event.user_id,
            (event.get_plaintext() or "").strip()[:80],
        )
        return False
    return True


async def can_close_spy_room(bot: Bot, event: GroupMessageEvent, game: Game | None) -> bool:
    user_id = event.user_id
    if game is not None and user_id == game.owner_id:
        return True
    try:
        info = await bot.get_group_member_info(
            group_id=event.group_id,
            user_id=user_id,
            no_cache=True,
        )
        role = (info.get("role") or "").lower()
    except Exception:
        role = "member"
    return role in ("owner", "admin")


@cmd_open.handle()
async def handle_open(bot: Bot, event: GroupMessageEvent) -> None:
    if not await claim_group_event(event):
        return

    cfg = get_spy_config()
    gid = group_key(event.group_id)
    user_id = event.user_id
    cached = await load_local_game(bot, gid)
    if cached is not None and cached.ready:
        await cmd_open.finish(err_game_in_progress())

    if cached is None:
        gate = await begin_spy_room(gid)
        if gate == "busy":
            await cmd_open.finish(err_room_busy())

    game = bind_local_game(Game(group_id=gid, owner_id=user_id))
    nick = await get_nickname(bot, gid, user_id)
    game.players[user_id] = Player(uid=user_id, nickname=nick)
    persist_prep(game)

    if needs_group_host_bot_gate():
        await bind_group_owned_gate(PLUGIN_KEY, gid, int(bot.self_id), gate_sec=SPY_HOST_GATE_SEC)
    mark_spy_prep_room(gid, owner_id=user_id, host_bot_id=int(bot.self_id))
    bot_id = int(bot.self_id)
    if await try_acquire_group_broadcast_slot(PLUGIN_KEY, gid, ttl_sec=3.0):
        await cmd_open.finish(open_room_message(user_id=user_id, min_players=cfg.spy_min_players))
        return
    if await is_group_owned_gate_holder(PLUGIN_KEY, gid, bot_id):
        await cmd_open.finish(open_room_message(user_id=user_id, min_players=cfg.spy_min_players))


@cmd_join.handle()
async def handle_join(bot: Bot, event: GroupMessageEvent) -> None:
    if not await claim_group_event(event):
        return

    cfg = get_spy_config()
    gid = group_key(event.group_id)
    user_id = event.user_id
    game = await load_local_prep_game(bot, gid)
    if game is None:
        await cmd_join.finish(err_no_room())
    if game.ready:
        await cmd_join.finish(err_already_started_join())
    if user_id in game.players:
        await cmd_join.finish(err_already_in_room())
    if len(game.players) >= cfg.spy_max_players:
        await cmd_join.finish(err_room_full(cfg.spy_max_players))

    nick = await get_nickname(bot, gid, user_id)
    game.players[user_id] = Player(uid=user_id, nickname=nick)
    persist_prep(game)
    await cmd_join.finish(join_ok(len(game.players)))


@cmd_quit.handle()
async def handle_quit(event: GroupMessageEvent) -> None:
    if not await claim_group_event(event):
        return

    gid = group_key(event.group_id)
    user_id = event.user_id
    game = resolve_game_sync(gid)
    if game is None:
        await cmd_quit.finish(err_no_room_quit())
    if game.ready:
        await cmd_quit.finish(err_cannot_quit_started())
    if user_id not in game.players:
        await cmd_quit.finish(err_not_in_room())
    if user_id == game.owner_id:
        await cmd_quit.finish(err_owner_cannot_quit())
    del game.players[user_id]
    persist_prep(game)
    await cmd_quit.finish(quit_ok(len(game.players)))


@cmd_start.handle()
async def handle_start(bot: Bot, event: GroupMessageEvent, arg: Message = CommandArg()) -> None:  # noqa: B008
    if not await claim_group_event(event):
        return

    cfg = get_spy_config()
    gid = group_key(event.group_id)
    user_id = event.user_id
    game = await load_local_prep_game(bot, gid)
    if game is None:
        await cmd_start.finish(err_no_room())
    if user_id != game.owner_id:
        await cmd_start.finish(err_not_owner_start())
    if game.ready:
        await cmd_start.finish(err_already_dealt())
    player_count = len(game.players)
    if player_count < cfg.spy_min_players:
        await cmd_start.finish(err_not_enough_players(cfg.spy_min_players, player_count))
    if not WORD_BANK:
        await cmd_start.finish(err_empty_word_bank())

    text = arg.extract_plain_text().strip()
    undercover_count = parse_undercover_count(text, default=cfg.spy_default_undercovers)
    if undercover_count >= player_count:
        undercover_count = max(1, player_count // 3)

    assign_roles(game, undercover_count)
    game.ready = True
    game.reset_round_flags()
    mark_spy_room_active(gid)
    persist_game(game)

    show_role = cfg.spy_show_role_default
    email_names, failed_names = await deliver_role_words(bot, game, show_role=show_role)

    msg = start_game_hint(numbered=render_alive_numbered(game), round_no=game.round_no)
    extra = delivery_report(email_users=email_names, failed_users=failed_names)
    if extra:
        msg = f"{msg}\n{extra}"
    await cmd_start.finish(msg)


@cmd_vote.handle()
async def handle_vote(bot: Bot, event: GroupMessageEvent) -> None:
    if not await claim_group_event(event):
        return

    gid = group_key(event.group_id)
    user_id = event.user_id
    game = await load_local_game(bot, gid)
    if game is None or not game.ready:
        await cmd_vote.finish(err_no_spy_room())
    if user_id != game.owner_id:
        await cmd_vote.finish(err_not_owner_vote())
    if is_voting_phase(game):
        await cmd_vote.finish(err_already_voting())

    async with game.lock:
        email_names, failed_names = await pm_invite_for_voting(bot, game)
        persist_game(game)

    msg = speak_round_to_vote()
    extra = delivery_report(email_users=email_names, failed_users=failed_names)
    if extra:
        msg = f"{msg}\n{extra}"
    await cmd_vote.finish(msg)


@cmd_status.handle()
async def handle_status(bot: Bot, event: GroupMessageEvent) -> None:
    if not await claim_group_event(event):
        return

    gid = group_key(event.group_id)
    game = await load_local_game(bot, gid)
    if game is None:
        await cmd_status.finish(err_no_spy_room())
    text = status_panel(
        round_no=game.round_no,
        alive=len(game.alive_ids()),
        numbered=render_alive_numbered(game),
        voting=is_voting_phase(game),
    )
    await cmd_status.finish(text)


@cmd_end.handle()
async def handle_end(bot: Bot, event: GroupMessageEvent) -> None:
    if not await claim_group_event(event):
        return

    gid = group_key(event.group_id)
    game = await load_local_game(bot, gid)
    if game is not None:
        if not await can_close_spy_room(bot, event, game):
            await cmd_end.finish(err_end_owner_only())
        close_spy_room(gid)
        await cmd_end.finish(room_closed())
        return

    lock = SPY_GROUP_LOCK.read(gid)
    if lock and lock.get("busy") and await can_close_spy_room(bot, event, None):
        close_spy_room(gid)
        await cmd_end.finish(room_closed())
        return

    await cmd_end.finish(err_no_spy_room())


def is_waiting_pm_vote(event: PrivateMessageEvent) -> bool:
    user_id = event.user_id
    text = str(event.get_plaintext() or "").strip()
    if not text.isdigit():
        return False
    for game in resolve_all_active_games():
        if (
            game.ready
            and user_id in game.players
            and game.players[user_id].is_alive
            and user_id in game.expecting_pm_vote
            and game.vote_round_tag == game.round_no
        ):
            return True
    return False


def resolve_all_active_games() -> list[Game]:
    from .logic import games as memory_games

    seen: dict[int, Game] = {gid: g for gid, g in memory_games.items() if g.ready}
    return list(seen.values())


pm_numeric_vote = on_message(
    rule=Rule(is_waiting_pm_vote),
    priority=8,
    block=True,
    permission=PRIVATE,
)


@pm_numeric_vote.handle()
async def handle_pm_vote(bot: Bot, event: PrivateMessageEvent) -> None:
    user_id = event.user_id
    number = int(event.get_plaintext().strip())

    game: Game | None = None
    for candidate in resolve_all_active_games():
        if (
            candidate.ready
            and user_id in candidate.players
            and candidate.players[user_id].is_alive
            and user_id in candidate.expecting_pm_vote
            and candidate.vote_round_tag == candidate.round_no
        ):
            game = candidate
            break
    if not game:
        await pm_numeric_vote.finish(pm_no_vote_pending())

    index_map = build_index_map(game)
    inverse = dict(index_map.items())

    if number == 0:
        async with game.lock:
            if user_id in game.votes:
                await pm_numeric_vote.finish(pm_already_voted())
            if not is_voting_phase(game):
                await pm_numeric_vote.finish(pm_cannot_abstain_yet())
            game.votes[user_id] = None
            persist_game(game)
            all_done = set(game.votes.keys()) >= set(game.alive_ids())
        await pm_numeric_vote.send(vote_abstained())
        if all_done:
            await settle_and_announce(bot, game)
        return

    if number not in inverse:
        tips = pm_invalid_index(render_alive_numbered(game))
        await pm_numeric_vote.finish(tips)

    target_user_id = inverse[number]

    async with game.lock:
        if user_id in game.votes:
            await pm_numeric_vote.finish(pm_already_voted())
        if not is_voting_phase(game):
            await pm_numeric_vote.finish(pm_cannot_vote_yet())
        if target_user_id not in game.players or not game.players[target_user_id].is_alive:
            await pm_numeric_vote.finish(pm_target_gone())
        game.votes[user_id] = target_user_id
        persist_game(game)
        voted_name = game.players[target_user_id].nickname
        all_done = set(game.votes.keys()) >= set(game.alive_ids())

    await pm_numeric_vote.send(vote_recorded(voted_name))
    if all_done:
        await settle_and_announce(bot, game)
