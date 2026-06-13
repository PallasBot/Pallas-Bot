"""WebUI 命令权限矩阵：插件/命令中文名（metadata 未加载时的回退）。"""

from __future__ import annotations

# 命令 ID 前缀 → 插件包名（与 NoneBot plugin.name 不一致时）
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
    "duel": "牛牛决斗",
    "greeting": "牛牛欢迎",
    "help": "牛牛帮助",
    "maa": "MAA 远控",
    "ollama": "随时闲聊",
    "relogin": "牛牛重新上号",
    "relogin_bot": "牛牛重新上号",
    "repeater": "牛牛复读",
    "request": "申请管理",
    "request_handler": "申请管理",
    "roulette": "牛牛轮盘",
    "sing": "牛牛唱歌",
}

# 命令 ID → 矩阵行标题（与各插件 command_permissions.label 对齐）
COMMAND_LABEL_FALLBACKS: dict[str, str] = {
    "blacklist.add": "牛牛拉黑 / 牛牛屏蔽 / 牛牛拉黑群",
    "blacklist.remove": "牛牛解禁 / 牛牛解禁群",
    "blacklist.list": "牛牛黑名单 / 牛牛查看黑名单",
    "bot_status.status": "牛牛在吗",
    "bot_status.count": "牛牛报数 / 牛牛出列",
    "bot_status.test_mail": "测试邮件",
    "connectivity.probe": "牛牛连通",
    "draw.draw": "牛牛画画",
    "draw.gateway": "牛牛网关",
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
    "maa.bind": "牛牛绑定MAA",
    "maa.control": "MAA 远控指令",
    "maa.status": "牛牛MAA状态",
    "ollama.chat": "随时闲聊",
    "ollama.clear": "清空会话",
    "ollama.unload": "卸载模型",
    "ollama.set_model": "更换模型",
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
