"""按用户话术推断需注入的 tool domain。"""

from __future__ import annotations

from pallas.product.llm.tools.identity import is_self_identity_question

_ARKNIGHTS_HINTS = (
    "干员",
    "技能",
    "天赋",
    "敌人",
    "关卡",
    "活动",
    "方舟",
    "明日方舟",
    "arknights",
    "查一下",
    "查询",
    "资料",
    "档案",
    "立绘",
)

_OPERATOR_LOOKUP_HINTS = (
    "是谁",
    "谁是",
    "你知道",
    "介绍一下",
    "介绍下",
    "什么角色",
    "哪个干员",
    "什么人",
    "干啥的",
    "什么职业",
)

_COMMAND_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("画", "绘制", "抽卡", "来张"), "draw"),
    (("忘掉", "清空", "clear", "忘了吧"), "llm_chat"),
    (("喝酒", "干杯", "继续喝", "醉酒", "醒一醒", "别喝了", "醒酒", "喝一杯", "再喝"), "drink"),
    (("帮助", "有哪些功能", "有什么功能", "功能列表", "牛牛帮助", "功能说明"), "help"),
    (("唱歌", "唱一首", "翻唱", "点歌", "继续唱", "接着唱", "什么歌", "哪首歌"), "sing"),
    (("轮盘", "开枪", "救一下", "补一枪"), "roulette"),
    (("做梦", "醒梦", "说梦话"), "dream"),
    (("决斗", "八角笼", "对战"), "duel"),
    (("卧底", "发身份", "牛牛局势"), "who_is_spy"),
    (("塔罗", "占卜", "抽牌"), "arcana"),
    (("赞我", "点赞"), "interact"),
    (("表情", "meme", "表情包", "做表情"), "memes"),
    (("报数", "出列"), "bot_status"),
    (("maa", "长草", "公招", "基建"), "maa"),
    (("额度", "爱发电", "画画次数"), "afdian"),
)


def infer_tool_domains(user_text: str) -> frozenset[str]:
    text = (user_text or "").strip().lower()
    if not text:
        return frozenset()
    domains: set[str] = set()
    if any(hint.lower() in text for hint in _ARKNIGHTS_HINTS):
        domains.add("arknights")
    if any(hint in text for hint in _OPERATOR_LOOKUP_HINTS):
        if not is_self_identity_question(user_text):
            domains.add("arknights")
    for hints, domain in _COMMAND_HINTS:
        if any(hint in text for hint in hints):
            domains.add(domain)
    return frozenset(domains)
