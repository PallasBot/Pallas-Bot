import asyncio
import copy
import re
import shutil
import time
from collections.abc import Iterable
from typing import Any

from nonebot import get_loaded_plugins, logger
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.internal.adapter import Event
from nonebot.permission import SUPERUSER

from src.features.cmd_perm.help_menu import is_user_help_plugin
from src.foundation.db import make_bot_config_repository, make_group_config_repository
from src.foundation.db.modules import BotConfigModule, GroupConfigModule
from src.foundation.paths import plugin_data_dir

from .global_disable import resolve_global_disabled_plugin_names, sync_global_disable_remote_generation
from .group_fleet_whitelist import (
    add_group_fleet_whitelist_plugin,
    resolve_group_fleet_whitelist_plugins,
    sync_group_fleet_whitelist_remote_generation,
)
from .plugin_availability import is_plugin_help_available
from .plugin_match import find_matching_plugins
from .styles import load_config
from .visibility import resolve_help_hidden_plugins, resolve_help_ignored_plugins

bot_config_repo = make_bot_config_repository()
group_config_repo = make_group_config_repository()

plugin_config = load_config()
ignored_plugins = plugin_config.ignored_plugins if plugin_config else []
CORE_PLUGINS = ["help"]

_DISABLED_GATE_CACHE_TTL_SEC = 45.0
_DISABLED_GATE_CACHE_MAX = 50_000
_disabled_gate_cache: dict[tuple[int | None, int | None], tuple[float, frozenset[str]]] = {}
_disabled_gate_lock = asyncio.Lock()
_disabled_bot_scope_cache: dict[int, tuple[float, frozenset[str]]] = {}
_disabled_group_scope_cache: dict[int, tuple[float, frozenset[str]]] = {}
_disabled_bot_generation: dict[int, int] = {}
_disabled_group_generation: dict[int, int] = {}
_disabled_bot_fetch_tasks: dict[int, asyncio.Task[frozenset[str]]] = {}
_disabled_group_fetch_tasks: dict[int, asyncio.Task[frozenset[str]]] = {}
_disabled_fetch_tasks_lock = asyncio.Lock()


def _disabled_gate_key(bot_id: int | None, group_id: int | None) -> tuple[int | None, int | None]:
    return (bot_id, group_id)


def _pg_not_ready() -> bool:
    from src.foundation.db.repository_pg import is_pg_initialized
    from src.foundation.db.runtime import is_postgresql_backend

    return is_postgresql_backend() and not is_pg_initialized()


def plugin_display_name(plugin: Any) -> str:
    """用户可见的插件名：优先 PluginMetadata.name，否则回退包名。"""
    meta = getattr(plugin, "metadata", None)
    if meta is not None:
        n = getattr(meta, "name", None)
        if isinstance(n, str) and n.strip():
            return n.strip()
    return plugin.name or "未命名插件"


def get_help_menu_plugins(
    *,
    show_ignored: bool = False,
    ignored_plugins: list[str] | None = None,
) -> list[Any]:
    """与一级帮助总览相同的插件集合。"""
    plugins = [p for p in get_loaded_plugins() if p.name]
    hidden = set(resolve_help_hidden_plugins())
    plugins = [p for p in plugins if p.name not in hidden]

    if show_ignored:
        filtered = [p for p in plugins if is_plugin_help_available(p.name)]
    else:
        ignored = set(ignored_plugins if ignored_plugins is not None else resolve_help_ignored_plugins())
        filtered = [
            p for p in plugins if p.name not in ignored and is_user_help_plugin(p) and is_plugin_help_available(p.name)
        ]
    return sorted(filtered, key=plugin_display_name)


def clear_help_cache(group_id: int | None = None):
    """清理本地帮助缓存"""
    cache_base_dir = plugin_data_dir("help")
    if not cache_base_dir.exists():
        return

    # 如果在群，只清理该群组的缓存
    if group_id is not None:
        group_cache_dir = cache_base_dir / str(group_id)
        if group_cache_dir.exists():
            try:
                shutil.rmtree(group_cache_dir)
                logger.debug(f"help cache cleared for group [{group_id}] path={group_cache_dir}")
            except Exception as e:
                logger.warning(f"help cache rmtree failed group={group_id} path={group_cache_dir}: {e}")
    else:
        try:
            for item in cache_base_dir.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
            logger.debug("help cache cleared (all groups)")
        except Exception as e:
            logger.warning(f"help cache clear all failed: {e}")


async def superuser_bypasses_plugin_disable(bot: Bot | None, event: Event | None) -> bool:
    """超管豁免所有层级的插件运行时禁用。"""
    if bot is None or event is None or not isinstance(event, MessageEvent):
        return False
    return await SUPERUSER(bot, event)


async def is_plugin_disabled(
    plugin_name: str,
    group_id: int | None = None,
    bot_id: int | None = None,
    ignore_cache: bool = False,
    *,
    bot: Bot | None = None,
    event: Event | None = None,
) -> bool:
    """检查插件是否被禁用。"""
    try:
        if await superuser_bypasses_plugin_disable(bot, event):
            return False
        if bot_id or group_id:
            disabled_names = await collect_disabled_plugin_names(bot_id, group_id, ignore_cache=ignore_cache)
            return plugin_name in disabled_names
        return plugin_name in merge_global_disabled_plugin_names(frozenset())
    except Exception as e:
        logger.error(f"help is_plugin_disabled failed plugin={plugin_name}: {e}")
        return False


def merge_global_disabled_plugin_names(names: frozenset[str]) -> frozenset[str]:
    global_names = resolve_global_disabled_plugin_names()
    if not global_names:
        return names
    if not names:
        return global_names
    return frozenset((*names, *global_names))


def apply_group_fleet_whitelist(group_id: int | None, names: frozenset[str]) -> frozenset[str]:
    """白名单群从 fleet 禁用集合中剔除对应插件。"""
    if not group_id or not names:
        return names
    exempt = resolve_group_fleet_whitelist_plugins(group_id)
    if not exempt:
        return names
    filtered = names - exempt
    return filtered or frozenset()


async def load_scoped_disabled_plugin_names_from_db(
    bot_id: int | None,
    group_id: int | None,
    *,
    ignore_cache: bool = False,
) -> frozenset[str]:
    """合并单牛与单群禁用插件名。"""
    if _pg_not_ready():
        return frozenset()
    bot_names = await load_disabled_bot_names_from_db(bot_id, ignore_cache=ignore_cache)
    if not group_id:
        return bot_names
    group_names = await load_disabled_group_names_from_db(group_id, ignore_cache=ignore_cache)
    if not bot_names:
        return group_names
    if not group_names:
        return bot_names
    return frozenset((*bot_names, *group_names))


async def load_disabled_plugin_names_from_db(
    bot_id: int | None,
    group_id: int | None,
    *,
    ignore_cache: bool = False,
) -> frozenset[str]:
    """合并 Bot 全局、群级与全实例禁用插件名。"""
    scoped = await load_scoped_disabled_plugin_names_from_db(bot_id, group_id, ignore_cache=ignore_cache)
    if _pg_not_ready():
        return apply_group_fleet_whitelist(group_id, merge_global_disabled_plugin_names(frozenset()))
    return apply_group_fleet_whitelist(group_id, merge_global_disabled_plugin_names(scoped))


async def load_disabled_bot_names_from_db(bot_id: int | None, *, ignore_cache: bool = False) -> frozenset[str]:
    if not bot_id:
        return frozenset()
    bot_config = await bot_config_repo.get(bot_id, ignore_cache=ignore_cache)
    if bot_config is None or not bot_config.disabled_plugins:
        return frozenset()
    return frozenset(bot_config.disabled_plugins)


async def load_disabled_group_names_from_db(group_id: int | None, *, ignore_cache: bool = False) -> frozenset[str]:
    if not group_id:
        return frozenset()
    group_config = await group_config_repo.get(group_id, ignore_cache=ignore_cache)
    if group_config is None or not group_config.disabled_plugins:
        return frozenset()
    return frozenset(group_config.disabled_plugins)


async def invalidate_disabled_plugin_gate_cache(
    *,
    bot_id: int | None = None,
    group_id: int | None = None,
    clear_all: bool = False,
) -> None:
    """使禁用插件门禁缓存失效。"""
    if clear_all:
        async with _disabled_fetch_tasks_lock:
            for t in [*_disabled_bot_fetch_tasks.values(), *_disabled_group_fetch_tasks.values()]:
                if not t.done():
                    t.cancel()
            _disabled_bot_fetch_tasks.clear()
            _disabled_group_fetch_tasks.clear()
        async with _disabled_gate_lock:
            _disabled_gate_cache.clear()
            _disabled_bot_scope_cache.clear()
            _disabled_group_scope_cache.clear()
            _disabled_bot_generation.clear()
            _disabled_group_generation.clear()
        return

    async with _disabled_gate_lock:
        if bot_id is not None:
            _disabled_bot_generation[bot_id] = _disabled_bot_generation.get(bot_id, 0) + 1
            _disabled_bot_scope_cache.pop(bot_id, None)
            for k in [k for k in _disabled_gate_cache if k[0] == bot_id]:
                _disabled_gate_cache.pop(k, None)
        if group_id is not None:
            _disabled_group_generation[group_id] = _disabled_group_generation.get(group_id, 0) + 1
            _disabled_group_scope_cache.pop(group_id, None)
            for k in [k for k in _disabled_gate_cache if k[1] == group_id]:
                _disabled_gate_cache.pop(k, None)


async def reset_disabled_plugin_gate_cache() -> None:
    """清空禁用插件门禁内存缓存。"""
    await invalidate_disabled_plugin_gate_cache(clear_all=True)


async def _await_disabled_scope_deduped(
    scope_id: int,
    *,
    ignore_cache: bool,
    fetch_tasks: dict[int, asyncio.Task[frozenset[str]]],
    loader,
) -> frozenset[str]:
    async def _runner() -> frozenset[str]:
        try:
            return await loader(scope_id, ignore_cache=ignore_cache)
        finally:
            async with _disabled_fetch_tasks_lock:
                cur = asyncio.current_task()
                if fetch_tasks.get(scope_id) is cur:
                    fetch_tasks.pop(scope_id, None)

    async with _disabled_fetch_tasks_lock:
        t = fetch_tasks.get(scope_id)
        if t is not None and not t.done():
            task = t
        else:
            task = asyncio.create_task(_runner())
            fetch_tasks[scope_id] = task
    return await asyncio.shield(task)


async def _collect_disabled_scope_names(
    scope_id: int | None,
    *,
    cache: dict[int, tuple[float, frozenset[str]]],
    generation: dict[int, int],
    fetch_tasks: dict[int, asyncio.Task[frozenset[str]]],
    loader,
) -> frozenset[str]:
    if scope_id is None:
        return frozenset()

    while True:
        now = time.monotonic()
        async with _disabled_gate_lock:
            hit = cache.get(scope_id)
            if hit is not None:
                exp, val = hit
                if now < exp:
                    return val
                cache.pop(scope_id, None)
            if len(cache) > _DISABLED_GATE_CACHE_MAX:
                stale = [k for k, (e, _) in cache.items() if now >= e]
                for k in stale:
                    cache.pop(k, None)
                if len(cache) > _DISABLED_GATE_CACHE_MAX:
                    cache.clear()
            gen_snapshot = generation.get(scope_id, 0)

        names = await _await_disabled_scope_deduped(
            scope_id,
            ignore_cache=False,
            fetch_tasks=fetch_tasks,
            loader=loader,
        )

        expire_at = time.monotonic() + _DISABLED_GATE_CACHE_TTL_SEC
        async with _disabled_gate_lock:
            if generation.get(scope_id, 0) != gen_snapshot:
                continue
            cache[scope_id] = (expire_at, names)
        return names


async def collect_disabled_plugin_names(
    bot_id: int | None,
    group_id: int | None,
    *,
    ignore_cache: bool = False,
) -> frozenset[str]:
    """合并 Bot 全局与群级的禁用插件名，供批量判断。"""
    if _pg_not_ready():
        return apply_group_fleet_whitelist(group_id, merge_global_disabled_plugin_names(frozenset()))
    if ignore_cache:
        return await load_disabled_plugin_names_from_db(bot_id, group_id, ignore_cache=True)

    remote_changed = sync_global_disable_remote_generation() or sync_group_fleet_whitelist_remote_generation()
    key = _disabled_gate_key(bot_id, group_id)
    while True:
        now = time.monotonic()
        async with _disabled_gate_lock:
            hit = _disabled_gate_cache.get(key)
            if hit is not None:
                exp, val = hit
                if now < exp and not remote_changed:
                    return val
                _disabled_gate_cache.pop(key, None)
            if len(_disabled_gate_cache) > _DISABLED_GATE_CACHE_MAX:
                stale = [k for k, (e, _) in _disabled_gate_cache.items() if now >= e]
                for k in stale:
                    _disabled_gate_cache.pop(k, None)
                if len(_disabled_gate_cache) > _DISABLED_GATE_CACHE_MAX:
                    _disabled_gate_cache.clear()
            bot_snap = _disabled_bot_generation.get(bot_id, 0) if bot_id is not None else 0
            group_snap = _disabled_group_generation.get(group_id, 0) if group_id is not None else 0

        bot_names = await _collect_disabled_scope_names(
            bot_id,
            cache=_disabled_bot_scope_cache,
            generation=_disabled_bot_generation,
            fetch_tasks=_disabled_bot_fetch_tasks,
            loader=load_disabled_bot_names_from_db,
        )
        group_names = await _collect_disabled_scope_names(
            group_id,
            cache=_disabled_group_scope_cache,
            generation=_disabled_group_generation,
            fetch_tasks=_disabled_group_fetch_tasks,
            loader=load_disabled_group_names_from_db,
        )
        if not bot_names:
            scoped = group_names
        elif not group_names:
            scoped = bot_names
        else:
            scoped = frozenset((*bot_names, *group_names))
        names = apply_group_fleet_whitelist(group_id, merge_global_disabled_plugin_names(scoped))

        expire_at = time.monotonic() + _DISABLED_GATE_CACHE_TTL_SEC
        async with _disabled_gate_lock:
            if bot_id is not None and _disabled_bot_generation.get(bot_id, 0) != bot_snap:
                continue
            if group_id is not None and _disabled_group_generation.get(group_id, 0) != group_snap:
                continue
            _disabled_gate_cache[key] = (expire_at, names)
        return names


async def is_plugin_globally_disabled(plugin_name: str, bot_id: int, ignore_cache: bool = False) -> bool:
    """
    检查插件是否在全局范围内被禁用
    """
    if not bot_id:
        return False

    bot_config = await bot_config_repo.get(bot_id, ignore_cache=ignore_cache)
    return bool(bot_config and plugin_name in bot_config.disabled_plugins)


def is_fleet_runtime_disabled(plugin_name: str, *, group_id: int | None = None) -> bool:
    """全实例运行时禁用，优先于单牛/单群配置；群白名单可豁免。"""
    if plugin_name not in resolve_global_disabled_plugin_names():
        return False
    if group_id is not None and plugin_name in resolve_group_fleet_whitelist_plugins(group_id):
        return False
    return True


def runtime_constraint_message(user_visible_name: str, *, group: bool = False) -> str:
    if group:
        return f"博士，{user_visible_name} 受到了米诺斯的制约..."
    return f"{user_visible_name} 受到了米诺斯的制约..."


async def get_bot_config(bot_id: int) -> tuple[BotConfigModule, bool]:
    """
    获取Bot配置，如果不存在则创建
    """
    bot_config, created = await bot_config_repo.get_or_create(bot_id, disabled_plugins=[])
    if created:
        logger.debug(f"help bot_config created bot_id={bot_id}")
    return bot_config, created


async def get_group_config(group_id: int) -> tuple[GroupConfigModule, bool]:
    """
    获取群配置，如果不存在则创建
    """
    group_config, created = await group_config_repo.get_or_create(group_id, disabled_plugins=[])
    if created:
        logger.debug(f"help group_config created group_id={group_id}")
    return group_config, created


async def update_bot_config(bot_id: int, disabled_plugins: list[str]) -> BotConfigModule:
    """
    更新Bot配置中的禁用插件列表
    """
    await bot_config_repo.upsert_field(bot_id, "disabled_plugins", disabled_plugins.copy())
    await bot_config_repo.invalidate_cache()
    await invalidate_disabled_plugin_gate_cache(bot_id=bot_id)

    bot_config = await bot_config_repo.get(bot_id, ignore_cache=True)
    # 不用 assert：python -O 下 assert 会被剥离。
    # upsert_field 语义上应保证文档存在，若仍拿不到说明仓储实现出问题，显式报错
    if bot_config is None:
        raise RuntimeError(f"BotConfig for bot_id={bot_id} not found after upsert_field")
    return bot_config


async def update_group_config(group_id: int, disabled_plugins: list[str]) -> GroupConfigModule:
    """
    更新群配置中的禁用插件列表
    """
    await group_config_repo.upsert_field(group_id, "disabled_plugins", disabled_plugins.copy())
    await group_config_repo.invalidate_cache()
    await invalidate_disabled_plugin_gate_cache(group_id=group_id)

    group_config = await group_config_repo.get(group_id, ignore_cache=True)
    if group_config is None:
        raise RuntimeError(f"GroupConfig for group_id={group_id} not found after upsert_field")
    return group_config


def find_plugin(plugin_name: str, *, plugins: Iterable[Any] | None = None) -> Any | None:
    """
    查找插件：包名、展示名、help_aliases 与 plugin_aliases 表；去空格后精确或子串匹配。
    仅当唯一命中时返回，否则 None。
    """
    key = (plugin_name or "").strip()
    if not key:
        return None
    pool = list(plugins) if plugins is not None else [p for p in get_loaded_plugins() if p.name]
    matches = find_matching_plugins(key, pool)
    if len(matches) == 1:
        return matches[0]
    return None


def resolve_plugin_disable_scope(plugin_name: str) -> str:
    """插件禁用作用域：group=本群；bot=单牛全局。"""
    plugin = find_plugin(plugin_name)
    if plugin is None:
        return "group"
    meta = getattr(plugin, "metadata", None)
    extra = getattr(meta, "extra", None) or {}
    scope = str(extra.get("disable_scope") or "group").strip().lower()
    return "bot" if scope == "bot" else "group"


async def is_plugin_disabled_for_help_display(
    plugin_name: str,
    group_id: int | None,
    bot_id: int | None,
    *,
    bot: Bot | None = None,
    event: Event | None = None,
) -> bool:
    eff_group_id = None if resolve_plugin_disable_scope(plugin_name) == "bot" else group_id
    return await is_plugin_disabled(plugin_name, eff_group_id, bot_id, bot=bot, event=event)


async def modify_disabled_list(disabled_list: list[str], plugin_name: str, should_disable: bool) -> list[str]:
    """
    修改禁用列表
    """
    result = copy.deepcopy(disabled_list)

    if should_disable and plugin_name not in result:
        result.append(plugin_name)
    elif not should_disable and plugin_name in result:
        result.remove(plugin_name)

    return result


async def update_config_and_cache(
    config_type: str, id_value: int, disabled_list: list[str], plugin_name: str, should_disable: bool
) -> tuple[bool, BotConfigModule | GroupConfigModule]:
    """
    更新配置并清除缓存
    """
    if config_type == "bot":
        config = await update_bot_config(id_value, disabled_list)
        expected_state = plugin_name in config.disabled_plugins
    else:  # group
        config = await update_group_config(id_value, disabled_list)
        expected_state = plugin_name in config.disabled_plugins

    # 验证操作结果
    if expected_state != should_disable:
        scope_info = f"bot[{id_value}]" if config_type == "bot" else f"group[{id_value}]"
        logger.error(
            f"help toggle verify failed: plugin={plugin_name} scope={scope_info} expected_disabled={should_disable}",
        )
        return False, config

    return True, config


async def toggle_plugin(
    plugin_name: str,
    group_id: int | None = None,
    bot_id: int | None = None,
    action: str = "toggle",
    *,
    is_superuser: bool = False,
) -> tuple[bool, str | None]:
    """
    切换插件启用/禁用状态
    """
    if not plugin_name:
        return False, "插件名称不能为空"

    # 查找插件
    target_plugin = find_plugin(plugin_name)
    if not target_plugin:
        # 检查插件是否在忽略列表中
        plugins = get_loaded_plugins()
        for plugin in plugins:
            if plugin.name and plugin.name.lower() == plugin_name.lower():
                if plugin.name in ignored_plugins:
                    # 如果是被忽略的插件，仍然允许超级用户操作
                    target_plugin = plugin
                    break
        if not target_plugin:
            return False, f"博士，你说的'{plugin_name}'是什么呀？"

    plugin_name = target_plugin.name
    user_visible_name = plugin_display_name(target_plugin)
    logger.debug(f"help toggle_plugin plugin={plugin_name} action={action} group_id={group_id} bot_id={bot_id}")

    if group_id and resolve_plugin_disable_scope(plugin_name) == "bot":
        return (
            True,
            f"{user_visible_name} 为单牛全局功能，请在私聊发送 牛牛开启 / 牛牛关闭 {user_visible_name}",
        )

    if bot_id and not group_id:
        return await _handle_global_plugin_operation(
            plugin_name, user_visible_name, bot_id, action, is_superuser=is_superuser
        )
    elif bot_id and group_id:
        return await _handle_group_plugin_operation(
            plugin_name, user_visible_name, group_id, bot_id, action, is_superuser=is_superuser
        )
    else:
        return False, None


async def _handle_global_plugin_operation(
    plugin_name: str,
    user_visible_name: str,
    bot_id: int,
    action: str,
    *,
    is_superuser: bool = False,
) -> tuple[bool, str]:
    """处理全局插件操作"""

    bot_config, _ = await get_bot_config(bot_id)
    current_disabled = bot_config.disabled_plugins

    # 确定目标状态
    should_disable = (
        plugin_name not in current_disabled if action == "toggle" else True if action == "disable" else False
    )

    fleet_disabled = is_fleet_runtime_disabled(plugin_name)

    if not should_disable and fleet_disabled and not is_superuser:
        return True, runtime_constraint_message(user_visible_name)

    # 检查是否已经处于目标状态
    is_disabled = plugin_name in current_disabled
    if should_disable == is_disabled:
        status = "禁用" if is_disabled else "启用"  # 超管私聊就不用搞什么七七八八的回复了吧(
        return True, f"{user_visible_name} 已经 {status}"

    new_disabled = await modify_disabled_list(current_disabled, plugin_name, should_disable)

    success, _ = await update_config_and_cache("bot", bot_id, new_disabled, plugin_name, should_disable)
    if not success:
        action_name = "禁用" if should_disable else "启用"
        return False, f"{action_name} {user_visible_name}失败"

    action_name = "禁止" if should_disable else "启用"
    return True, f"{user_visible_name} 已经 {action_name}"


async def ensure_superuser_group_fleet_whitelist(
    plugin_name: str,
    group_id: int,
    *,
    is_superuser: bool,
    enabling: bool,
) -> None:
    """超管为指定群开启插件时，若该插件处于全实例禁用，自动写入群白名单。"""
    if not is_superuser or not enabling:
        return
    if plugin_name not in resolve_global_disabled_plugin_names():
        return
    if plugin_name in resolve_group_fleet_whitelist_plugins(group_id):
        return
    if not add_group_fleet_whitelist_plugin(group_id, plugin_name):
        return
    await invalidate_disabled_plugin_gate_cache(clear_all=True)


async def _handle_group_plugin_operation(
    plugin_name: str,
    user_visible_name: str,
    group_id: int,
    bot_id: int,
    action: str,
    *,
    is_superuser: bool = False,
) -> tuple[bool, str]:
    """处理群级插件操作"""

    group_config, _ = await get_group_config(group_id)
    current_disabled = group_config.disabled_plugins

    is_globally_disabled = await is_plugin_globally_disabled(plugin_name, bot_id)
    fleet_disabled = is_fleet_runtime_disabled(plugin_name, group_id=group_id)
    runtime_constrained = not is_superuser and (is_globally_disabled or fleet_disabled)
    scope_info = f"在{group_id}这块地方"

    should_disable = (
        plugin_name not in current_disabled if action == "toggle" else True if action == "disable" else False
    )
    enabling = not should_disable

    if not should_disable and runtime_constrained:
        return True, runtime_constraint_message(user_visible_name, group=True)

    is_disabled = plugin_name in current_disabled
    if should_disable == is_disabled:
        await ensure_superuser_group_fleet_whitelist(
            plugin_name, group_id, is_superuser=is_superuser, enabling=enabling
        )
        status = "停止" if is_disabled else "启用"
        return True, f"听你的，博士。{scope_info}我为你{status}了{user_visible_name}"

    new_disabled = await modify_disabled_list(current_disabled, plugin_name, should_disable)

    success, _ = await update_config_and_cache("group", group_id, new_disabled, plugin_name, should_disable)
    if not success:
        action_name = "停止" if should_disable else "启用"
        return (
            False,
            f"呜...看来是喝多了...无法感受到米诺斯的联系，{scope_info}{action_name} {user_visible_name}失败了...",
        )
    await ensure_superuser_group_fleet_whitelist(plugin_name, group_id, is_superuser=is_superuser, enabling=enabling)
    action_name = "停止" if should_disable else "启用"
    return True, f"听你的，博士。{scope_info}我为你{action_name}了{user_visible_name}"


async def find_plugin_by_identifier(plugin_identifier: str, ignored_plugins: list | None = None):
    """
    根据插件名称或序号查找插件）
    """
    if not plugin_identifier:
        return None, "博士，即使身为大祭司，你不说想要什么，我也帮不了你呀"

    # 如果不是数字，直接返回插件名称
    if not plugin_identifier.isdigit():
        if ignored_plugins is None:
            candidates = [p for p in get_loaded_plugins() if p.name]
        else:
            candidates = get_help_menu_plugins(show_ignored=False, ignored_plugins=ignored_plugins)

        plugin = find_plugin(plugin_identifier, plugins=candidates)
        if plugin:
            return plugin.name or "", None

        matched_plugins = find_matching_plugins(plugin_identifier, candidates)
        if len(matched_plugins) == 1:
            return matched_plugins[0].name or "", None
        if len(matched_plugins) > 1:
            plugin_names = [plugin_display_name(p) for p in matched_plugins]
            return (
                None,
                f"博士，你说的'{plugin_identifier}'有多个可能：{'、'.join(plugin_names)}，请说得更具体一些哦",
            )
        return None, f"博士，你说的'{plugin_identifier}'是什么呀？"

    if ignored_plugins is None:
        sorted_plugins = get_help_menu_plugins(show_ignored=True)
    else:
        sorted_plugins = get_help_menu_plugins(show_ignored=False, ignored_plugins=ignored_plugins)

    # 检查序号是否有效
    index = int(plugin_identifier) - 1
    if 0 <= index < len(sorted_plugins):
        plugin = sorted_plugins[index]
        return plugin.name or "未命名插件", None
    else:
        return (
            None,
            (
                f"博士，'{plugin_identifier}' 这个数字太大了，"
                f"在米诺斯女神允许的情况下，我们可以使用 1 到 {len(sorted_plugins)} 之间的序号。"
            ),
        )


def apply_status_marks_to_plugin_table(markdown_content: str, marks: list[str]) -> str:
    """按「插件列表」表数据行顺序填入状态，每行仅替换一个占位符。"""
    from .help_constants import HELP_STATUS_PLACEHOLDER

    lines = markdown_content.splitlines()
    out: list[str] = []
    row_i = 0
    in_plugin_table = False
    for line in lines:
        if "## 插件列表" in line:
            in_plugin_table = True
            out.append(line)
            continue
        if (
            in_plugin_table
            and HELP_STATUS_PLACEHOLDER in line
            and line.strip().startswith("|")
            and not re.match(r"^\|\s*[-:]+\s*\|", line.strip())
        ):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cells and cells[0].isdigit():
                mark = marks[row_i] if row_i < len(marks) else "？"
                line = line.replace(HELP_STATUS_PLACEHOLDER, mark, 1)
                row_i += 1
        out.append(line)
    return "\n".join(out)


async def fill_plugin_status(
    markdown_content: str, bot_id: int | None = None, group_id: int | None = None, show_ignored: bool = False
) -> str:
    from .markdown_generator import help_list_status_mark
    from .styles import load_config

    plugin_config = load_config()

    if show_ignored:
        sorted_plugins = get_help_menu_plugins(show_ignored=True)
    else:
        sorted_plugins = get_help_menu_plugins(
            show_ignored=False,
            ignored_plugins=plugin_config.ignored_plugins if plugin_config else [],
        )
    logger.debug(f"help fill_plugin_status sorted_plugins count={len(sorted_plugins)}")

    disabled_names = await collect_disabled_plugin_names(bot_id, group_id, ignore_cache=False)
    bot_disabled_names = (
        await collect_disabled_plugin_names(bot_id, None, ignore_cache=False) if group_id else disabled_names
    )

    marks: list[str] = []
    for plugin in sorted_plugins:
        plugin_name = plugin.name or "未命名插件"
        names = bot_disabled_names if resolve_plugin_disable_scope(plugin_name) == "bot" else disabled_names
        is_disabled = plugin_name in names
        marks.append(help_list_status_mark(not is_disabled))

    result_content = apply_status_marks_to_plugin_table(markdown_content, marks)
    from .help_constants import HELP_STATUS_PLACEHOLDER

    return result_content.replace(HELP_STATUS_PLACEHOLDER, "？")
