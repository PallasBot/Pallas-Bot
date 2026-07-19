from nonebot.plugin import PluginMetadata

from pallas.core.commands import command_limit_list, command_limit_row, command_perm_list, command_perm_row
from pallas.core.perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from pallas.core.perm.metadata_text import SCENE_GROUP, join_usage, usage_line
from pallas.product.llm.knowledge.declare import knowledge_source_row

from . import handlers as _handlers  # noqa: F401
from . import startup as _startup  # noqa: F401

__plugin_meta__ = PluginMetadata(
    name="牛牛喝酒",
    description="让牛牛喝酒、醒酒，并影响它接下来的表现。",
    usage=join_usage(
        usage_line("牛牛喝酒 / 牛牛干杯 / 牛牛继续喝", "增加醉酒度，可能睡着"),
        usage_line("牛牛醒一醒 / 牛牛别喝了", "立即醒酒；本群在做梦时一并醒梦"),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "ingress_fanout": {
            "scope": "always",
            "plaintexts": [
                "牛牛醒一醒",
                "牛牛别喝了",
            ],
        },
        "command_permissions": command_perm_list(
            command_perm_row("drink.drink", "牛牛喝酒 / 牛牛干杯 / 牛牛继续喝"),
            command_perm_row("drink.sober_up", "牛牛醒一醒 / 牛牛别喝了"),
        ),
        "command_limits": command_limit_list(
            command_limit_row("drink.drink", 3),
        ),
        "menu_data": [
            {
                "func": "牛牛喝酒",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "牛牛喝酒 / 牛牛干杯 / 牛牛继续喝",
                "command_permission": "drink.drink",
                "brief_des": "饮酒并进入醉酒",
                "detail_des": "喝得越多越容易醉，醉酒后说话和行为都会变得不一样，太过头还会睡着。",
            },
            {
                "func": "牛牛醒一醒",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "牛牛醒一醒 / 牛牛别喝了",
                "command_permission": "drink.sober_up",
                "brief_des": "立即醒酒",
                "detail_des": "让牛牛立刻清醒；如果它正在做梦，也会一起停下来。",
            },
        ],
        "knowledge_sources": [
            knowledge_source_row(
                source_id="drink.faq",
                title="牛牛喝酒说明",
                description="饮酒、醒酒与醉酒状态",
                chunks=[
                    {
                        "title": "如何让牛牛喝酒",
                        "content": (
                            "在群内发送「牛牛喝酒」「牛牛干杯」或「牛牛继续喝」"
                            "可增加醉酒度；喝得越多越容易醉，严重时可能睡着。"
                        ),
                        "keywords": "喝酒,干杯,继续喝,醉酒,醉了,怎么喝",
                    },
                    {
                        "title": "如何让牛牛醒酒",
                        "content": ("发送「牛牛醒一醒」或「牛牛别喝了」可立即让牛牛清醒；若本群正在做梦也会一并停止。"),
                        "keywords": "醒酒,醒一醒,别喝了,清醒, sober",
                    },
                    {
                        "title": "醉酒会影响什么",
                        "content": (
                            "醉酒后牛牛说话与行为会变化，自动夺舍等玩法也会更夸张；"
                            "部分扩展（如酒后聊天）可能要求先处于醉酒状态。"
                        ),
                        "keywords": "醉酒,影响,聊天,夺舍,前置,状态",
                    },
                ],
            ),
        ],
    },
)
