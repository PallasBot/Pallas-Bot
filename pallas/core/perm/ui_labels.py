"""WebUI 命令权限矩阵：插件/命令中文名。"""

from __future__ import annotations

# 命令 ID 前缀 → 插件包名
PLUGIN_NAME_ALIASES: dict[str, str] = {
    "relogin": "relogin_bot",
    "request": "request_handler",
}

# 插件包名 / 前缀 → 分组标题
PLUGIN_TITLE_FALLBACKS: dict[str, str] = {
    "blacklist": "牛牛黑名单",
    "bot_status": "牛牛状态",
    "connectivity": "牛牛连通",
    "draw": "牛牛画画",
    "dream": "牛牛做梦",
    "drink": "牛牛喝酒",
    "duel": "牛牛决斗",
    "greeting": "牛牛欢迎",
    "help": "牛牛帮助",
    "maa": "MAA 远控",
    "pb_core": "牛牛核心",
    "llm_chat": "随时闲聊",
    "ollama": "随时闲聊",
    "relogin": "牛牛重新上号",
    "relogin_bot": "牛牛重新上号",
    "repeater": "牛牛复读",
    "request": "申请管理",
    "request_handler": "申请管理",
    "roulette": "牛牛轮盘",
    "sing": "牛牛唱歌",
}

# 命令 ID → 矩阵行标题
COMMAND_LABEL_FALLBACKS: dict[str, str] = {
    "blacklist.add": "牛牛拉黑 / 牛牛屏蔽 / 牛牛拉黑群",
    "blacklist.remove": "牛牛解禁 / 牛牛解禁群",
    "blacklist.list": "牛牛黑名单 / 牛牛查看黑名单",
    "bot_status.status": "牛牛在吗",
    "bot_status.count": "牛牛报数 / 牛牛出列",
    "bot_status.test_mail": "测试邮件",
    "connectivity.probe": "牛牛连通",
    "draw.draw": "牛牛画画",
    "drink.drink": "牛牛喝酒 / 牛牛干杯 / 牛牛继续喝",
    "drink.sober_up": "牛牛醒一醒 / 牛牛别喝了",
    "dream.ban_cleanup": "梦库清理（不可以）",
    "duel.duel": "牛牛决斗",
    "duel.cage": "八角笼牛",
    "duel.reload_events": "决斗事件重载",
    "greeting.set_friend_welcome": "设置好友欢迎",
    "greeting.clear_friend_welcome": "清除好友欢迎",
    "greeting.set_group_welcome": "设置群欢迎",
    "greeting.clear_group_welcome": "清除群欢迎",
    "help.help": "牛牛帮助",
    "help.plugin_enable": "牛牛开启（单插件）",
    "help.plugin_disable": "牛牛关闭（单插件）",
    "help.plugin_enable_all": "牛牛开启全部功能",
    "help.plugin_disable_all": "牛牛关闭全部功能",
    "pb_core.status": "牛牛状态",
    "pb_core.console": "牛牛控制台",
    "pb_core.plugins": "牛牛插件",
    "pb_core.update_check": "牛牛更新",
    "pb_core.restart": "牛牛重启",
    "maa.bind": "牛牛绑定MAA",
    "maa.switch_device": "牛牛切换MAA设备",
    "maa.device_alias": "牛牛MAA设备名",
    "maa.control": "MAA 远控指令",
    "maa.raw_task": "牛牛MAA任务",
    "maa.clear_queue": "牛牛清空MAA队列",
    "maa.status": "牛牛MAA状态",
    "llm_chat.chat": "随时闲聊",
    "llm_chat.clear": "清空会话",
    "llm_chat.status": "LLM 状态",
    "llm_chat.switch_model": "换模型",
    "llm_chat.unload_model": "卸模型",
    "ollama.chat": "随时闲聊（已弃用）",
    "ollama.clear": "清空会话（已弃用）",
    "relogin.relogin": "牛牛重新上号",
    "relogin.create": "创建牛牛",
    "repeater.ban": "复读「不可以」",
    "repeater.ban_latest": "复读「不可以发这个」",
    "request.list_friends": "查看好友申请",
    "request.list_groups": "查看入群申请",
    "request.approve_latest": "同意（快捷）",
    "request.reject_latest": "拒绝（快捷）",
    "request.approve_friend": "同意好友",
    "request.reject_friend": "拒绝好友",
    "request.approve_all_friends": "同意所有好友",
    "request.reject_all_friends": "拒绝所有好友",
    "request.approve_group": "同意入群",
    "request.reject_group": "拒绝入群",
    "request.approve_all_groups": "同意所有入群申请",
    "request.reject_all_groups": "拒绝所有入群申请",
    "request.auto_accept_status": "查看自动同意",
    "request.enable_auto_friend": "开启自动同意好友",
    "request.disable_auto_friend": "关闭自动同意好友",
    "request.enable_auto_group": "开启自动同意入群",
    "request.disable_auto_group": "关闭自动同意入群",
    "request.approval_reply": "引用审批消息快捷同意/拒绝",
    "roulette.mode_switch": "牛牛轮盘切换模式",
    "sing.ncm_login": "网易云登录",
    "sing.ncm_logout": "网易云登出",
    "sing.sing": "牛牛唱歌 / 牛牛继续唱",
    "sing.play": "牛牛唱歌（随机）",
    "sing.request_song": "牛牛点歌",
    "sing.song_title": "牛牛什么歌",
}


def plugin_name_for_command_id(command_id: str) -> str:
    prefix = (command_id or "").split(".", 1)[0]
    return PLUGIN_NAME_ALIASES.get(prefix, prefix)


def plugin_title_for_name(plugin_name: str) -> str:
    key = (plugin_name or "").strip()
    return PLUGIN_TITLE_FALLBACKS.get(key, key)


def command_label_for_id(command_id: str) -> str:
    cid = (command_id or "").strip()
    return COMMAND_LABEL_FALLBACKS.get(cid, cid)
