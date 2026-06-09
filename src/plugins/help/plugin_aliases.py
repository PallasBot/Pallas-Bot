"""帮助口令解析用别名（包名 → 用户可能输入的简称）。"""

from __future__ import annotations

# 键为插件包名（Plugin.name），值为额外可匹配字符串（不含包名与 metadata.name，由匹配逻辑自动纳入）
PLUGIN_HELP_ALIASES: dict[str, tuple[str, ...]] = {
    "help": ("帮助", "菜单", "功能列表"),
    "maa": ("远控", "MAA", "明日方舟", "长草", "作战"),
    "repeater": ("复读", "复读机"),
    "chat": ("聊天", "酒后", "醉酒", "AI聊天"),
    "ollama": ("随时闲聊", "随时", "Ollama", "多轮", "牛牛聊天"),
    "sing": ("唱歌", "点歌", "翻唱", "续唱"),
    "drink": ("喝酒", "干杯"),
    "dream": ("做梦", "抽签"),
    "duel": ("决斗", "比拼"),
    "roulette": ("轮盘", "转盘"),
    "greeting": ("欢迎", "入群欢迎"),
    "blacklist": ("黑名单", "拉黑", "屏蔽"),
    "bot_status": ("状态", "报数", "出列", "在线"),
    "relogin_bot": ("上号", "重登", "重新登录"),
    "take_name": ("夺舍", "改名"),
    "draw": ("画画", "生图", "绘图"),
    "connectivity": ("连通", "网络", "探测"),
    "request_handler": ("申请", "申请管理", "好友申请", "加群", "入群申请"),
    "pallas_webui": ("控制台", "WebUI", "webui", "面板"),
    "pallas_protocol": ("协议", "协议端", "NapCat", "SnowLuma"),
}


def aliases_for_plugin(package_name: str) -> tuple[str, ...]:
    if not package_name:
        return ()
    return PLUGIN_HELP_ALIASES.get(package_name, ())
