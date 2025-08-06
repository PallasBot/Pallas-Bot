import copy
import shutil
from pathlib import Path
from typing import Any

from nonebot import get_loaded_plugins, logger

from src.common.db.modules import BotConfigModule, GroupConfigModule
from src.common.utils.invalidate_cache import clear_model_cache

from .styles import load_config

plugin_config = load_config()
ignored_plugins = plugin_config.ignored_plugins if plugin_config else []
CORE_PLUGINS = ["help"]


def clear_help_cache(group_id: int = None):
    """清理本地帮助缓存"""
    cache_base_dir = Path("data/help")
    if not cache_base_dir.exists():
        return

    # 如果在群，只清理该群组的缓存
    if group_id is not None:
        group_cache_dir = cache_base_dir / str(group_id)
        if group_cache_dir.exists():
            try:
                shutil.rmtree(group_cache_dir)
                logger.debug(f"清理群组 {group_id} 的缓存: {group_cache_dir}")
            except Exception as e:
                logger.warning(f"删除群缓存失败 {group_cache_dir}: {e}")
    else:
        try:
            for item in cache_base_dir.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
            logger.debug("清理所有帮助缓存")
        except Exception as e:
            logger.warning(f"清理帮助缓存失败: {e}")


async def is_plugin_disabled(
    plugin_name: str, group_id: int = None, bot_id: int = None, ignore_cache: bool = False
) -> bool:
    """
    检查插件是否被禁用
    """
    try:
        # 检查全局禁用状态
        if bot_id:
            bot_config = await BotConfigModule.find_one(
                {"account": bot_id}, fetch_links=True, ignore_cache=ignore_cache
            )
            if bot_config:
                if plugin_name in bot_config.disabled_plugins:
                    logger.debug(f"插件 {plugin_name} 在全局级别被禁用")
                    return True
            elif not bot_config:
                bot_config = BotConfigModule(account=bot_id, disabled_plugins=[])
                await bot_config.save()

        # 检查群级禁用状态
        if group_id:
            group_config = await GroupConfigModule.find_one(
                {"group_id": group_id}, fetch_links=True, ignore_cache=ignore_cache
            )
            if group_config:
                if plugin_name in group_config.disabled_plugins:
                    logger.debug(f"插件 {plugin_name} 在群 {group_id} 级别被禁用")
                    return True

        return False
    except Exception as e:
        logger.error(f"检查插件 {plugin_name} 状态时出错: {str(e)}")
        # 出错时返回False，假设插件是启用的
        return False


async def is_plugin_globally_disabled(plugin_name: str, bot_id: int, ignore_cache: bool = False) -> bool:
    """
    检查插件是否在全局范围内被禁用

    """
    if not bot_id:
        return False

    bot_config = await BotConfigModule.find_one({"account": bot_id}, fetch_links=True, ignore_cache=ignore_cache)
    return bool(bot_config and plugin_name in bot_config.disabled_plugins)


async def get_bot_config(bot_id: int) -> tuple[BotConfigModule, bool]:
    """
    获取Bot配置，如果不存在则创建

    """
    bot_config = await BotConfigModule.find_one({"account": bot_id})
    created = False

    if not bot_config:
        logger.debug(f"为Bot {bot_id} 创建新的配置")
        bot_config = BotConfigModule(account=bot_id, disabled_plugins=[])
        await bot_config.insert()
        created = True

    return bot_config, created


async def get_group_config(group_id: int) -> tuple[GroupConfigModule, bool]:
    """
    获取群配置，如果不存在则创建
    """
    group_config = await GroupConfigModule.find_one({"group_id": group_id})
    created = False

    if not group_config:
        logger.debug(f"为群 {group_id} 创建新的配置")
        group_config = GroupConfigModule(group_id=group_id, disabled_plugins=[])
        await group_config.insert()
        created = True

    return group_config, created


async def update_bot_config(bot_id: int, disabled_plugins: list[str]) -> BotConfigModule:
    """
    更新Bot配置中的禁用插件列表
    """

    bot_config, _ = await get_bot_config(bot_id)

    bot_config.disabled_plugins = disabled_plugins.copy()

    await bot_config.save()

    clear_model_cache(BotConfigModule)

    # 清理所有缓存，因为全局设置影响所有群组
    clear_help_cache()

    return bot_config


async def update_group_config(group_id: int, disabled_plugins: list[str]) -> GroupConfigModule:
    """
    更新群配置中的禁用插件列表
    """

    group_config, _ = await get_group_config(group_id)

    group_config.disabled_plugins = disabled_plugins.copy()

    await group_config.save()

    clear_model_cache(GroupConfigModule)

    clear_help_cache(group_id)

    return group_config


def find_plugin(plugin_name: str) -> Any | None:
    """
    查找插件对象
    """
    plugins = get_loaded_plugins()

    for plugin in plugins:
        if plugin.name and plugin.name.lower() == plugin_name.lower():
            if plugin.name in ignored_plugins:
                return None
            return plugin

    for plugin in plugins:
        if plugin.name and plugin_name.lower() in plugin.name.lower():
            if plugin.name in ignored_plugins:
                return None
            return plugin

    return None


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
        action_name = "禁用" if should_disable else "启用"
        scope_info = "全局" if config_type == "bot" else f"群 {id_value}"
        logger.error(
            f"{action_name}失败：插件 {plugin_name} 未能正确更新到"
            f"{scope_info}{'禁用' if should_disable else '启用'}状态"
        )
        return False, config

    return True, config


async def toggle_plugin(
    plugin_name: str, group_id: int = None, bot_id: int = None, action: str = "toggle"
) -> tuple[bool, str | None]:
    """
    切换插件启用/禁用状态
    """
    if not plugin_name:
        return False, "插件名称不能为空"

    # 查找插件
    target_plugin = find_plugin(plugin_name)
    if not target_plugin:
        return False, f"博士，你说的'{plugin_name}'是什么呀？"

    plugin_name = target_plugin.name
    logger.debug(f"操作插件: {plugin_name}, 操作类型: {action}, 群ID: {group_id}, BotID: {bot_id}")

    if plugin_name in ignored_plugins:
        return False, None

    if bot_id and not group_id:
        return await _handle_global_plugin_operation(plugin_name, bot_id, action)
    elif group_id:
        return await _handle_group_plugin_operation(plugin_name, group_id, bot_id, action)
    else:
        return False, None


async def _handle_global_plugin_operation(plugin_name: str, bot_id: int, action: str) -> tuple[bool, str]:
    """处理全局插件操作"""

    bot_config, _ = await get_bot_config(bot_id)
    current_disabled = bot_config.disabled_plugins

    # 确定目标状态
    should_disable = (
        plugin_name not in current_disabled if action == "toggle" else True if action == "disable" else False
    )

    # 检查是否已经处于目标状态
    is_disabled = plugin_name in current_disabled
    if should_disable == is_disabled:
        status = "禁用" if is_disabled else "启用"  # 超管私聊就不用搞什么七七八八的回复了吧(
        return True, f"{plugin_name} 已经 {status}"

    new_disabled = await modify_disabled_list(current_disabled, plugin_name, should_disable)

    success, _ = await update_config_and_cache("bot", bot_id, new_disabled, plugin_name, should_disable)
    if not success:
        action_name = "禁用" if should_disable else "启用"
        return False, f"{action_name} {plugin_name}失败"

    action_name = "禁止" if should_disable else "启用"
    return True, f"{plugin_name} 已经 {action_name}"


async def _handle_group_plugin_operation(plugin_name: str, group_id: int, bot_id: int, action: str) -> tuple[bool, str]:
    """处理群级插件操作"""

    group_config, _ = await get_group_config(group_id)
    current_disabled = group_config.disabled_plugins

    is_globally_disabled = await is_plugin_globally_disabled(plugin_name, bot_id)
    scope_info = f"在{group_id}这块地方"

    should_disable = (
        plugin_name not in current_disabled if action == "toggle" else True if action == "disable" else False
    )

    is_disabled = plugin_name in current_disabled
    if should_disable == is_disabled:
        status = "停止" if is_disabled else "启用"
        if not is_disabled and is_globally_disabled:
            return True, f"博士,我在{scope_info}已经{status}了 {plugin_name}，但我同时受到了米诺斯的制约..."
        return True, f"听你的，博士。{scope_info}我为你{status}了{plugin_name}"

    new_disabled = await modify_disabled_list(current_disabled, plugin_name, should_disable)

    success, _ = await update_config_and_cache("group", group_id, new_disabled, plugin_name, should_disable)
    if not success:
        action_name = "停止" if should_disable else "启用"
        return False, f"呜...看来是喝多了...无法感受到米诺斯的联系，{scope_info}{action_name} {plugin_name}失败了..."
    action_name = "停止" if should_disable else "启用"
    if not should_disable and is_globally_disabled:
        return True, f"博士,我在{scope_info}已经{action_name}了 {plugin_name}，但我同时受到了米诺斯的制约..."

    return True, f"听你的，博士。{scope_info}我为你{action_name}了{plugin_name}"


async def find_plugin_by_identifier(plugin_identifier: str, ignored_plugins: list = None):
    """
    根据插件名称或序号查找插件）
    """
    if not plugin_identifier:
        return None, "博士，即使身为大祭司，你不说想要什么，我也帮不了你呀"

    # 如果不是数字，直接返回插件名称
    if not plugin_identifier.isdigit():
        return plugin_identifier, None

    # 获取插件配置
    if ignored_plugins is None:
        from .styles import load_config

        plugin_config = load_config()
        ignored_plugins = plugin_config.ignored_plugins if plugin_config else []

    # 过滤和排序插件
    filtered_plugins = [p for p in get_loaded_plugins() if p.name and p.name not in ignored_plugins]
    sorted_plugins = sorted(filtered_plugins, key=lambda p: p.name or "")

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


async def fill_plugin_status(markdown_content: str, bot_id: int = None, group_id: int = None) -> str:
    from .styles import load_config

    plugin_config = load_config()

    ignored_plugins = plugin_config.ignored_plugins if plugin_config else []
    filtered_plugins = [p for p in get_loaded_plugins() if p.name and p.name not in ignored_plugins]

    sorted_plugins = sorted(filtered_plugins, key=lambda p: p.name or "")
    logger.debug(f"已排序的插件列表 (共{len(sorted_plugins)}个)")

    result_content = markdown_content
    placeholders_count = result_content.count("{status}")

    for index, plugin in enumerate(sorted_plugins, 1):
        if index > placeholders_count:
            break

        plugin_name = plugin.name or "未命名插件"

        is_disabled = await is_plugin_disabled(plugin_name, group_id, bot_id, ignore_cache=True)
        status = "⛔ 禁用" if is_disabled else "✅ 启用"

        result_content = result_content.replace("{status}", status, 1)

    result_content = result_content.replace("{status}", "❓ 未知")
    return result_content
