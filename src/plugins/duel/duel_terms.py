"""决斗对外显示用语（与机制键名解耦）。"""

# —— 幕型标题（拼在「第 n/m 幕 · 」后）——
ROUND_KIND_PUBLIC = "泰拉节庆"
ROUND_KIND_CLASH = "紧急作战"

# —— 状态条与层数变动 ——
STAT_HP = "生命"
STAT_DP = "护盾"
STACK_BUFF = "战意"
STACK_DEBUFF = "蚀势"

# —— 空幕 / 无词 ——
PUBLIC_ROUND_EMPTY = "节庆寂然，唯源石风掠过栏外。"
CLASH_SILENT_ATTACKER = "攻方斗士敛锋，本段无言。"
CLASH_SILENT_DEFENDER = "守方斗士敛锋，本段无言。"

# —— 日志与 QTE 子标签（内部 narr / round_tag）——
TAG_PUBLIC = "节庆"
TAG_PUBLIC_INTRUSION = "节庆·干员乱入"
TAG_CLASH_ATTACK = "刃锋·攻"
TAG_CLASH_DEFEND = "刃锋·守"
TAG_CLASH_INTRUSION_ATTACK = "刃锋·攻方乱入"
TAG_CLASH_INTRUSION_DEFEND = "刃锋·守方乱入"
TAG_EXCHANGE = "刃锋对撼"

# —— QTE 提示 ——
QTE_INTRUSION_TITLE = " 辨认闯入者 "
QTE_KEYWORD_TITLE = " [QTE] "
QTE_INTRUSION_FAIL_STUB = "（闯入者身份无法载入，这场乱入只能作罢。）"
QTE_SUCCESS_TAIL = " QTE 成功 "
QTE_FAIL_TAIL = " QTE 失败"
EXCHANGE_QTE_DEFAULT_PROMPT = "刃势未绝！攻势仍在延续"


def round_finale_head(total_rounds: int) -> str:
    return f"第{total_rounds}幕落幕"
