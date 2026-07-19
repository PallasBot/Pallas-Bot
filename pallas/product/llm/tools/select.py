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

_COMMAND_HINTS: tuple[tuple[str, ...], str] = (
    (("画", "绘制", "抽卡", "来张"), "draw"),
    (("忘掉", "清空", "clear", "忘了吧"), "llm_chat"),
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
