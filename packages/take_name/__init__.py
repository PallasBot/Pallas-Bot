from nonebot.plugin import PluginMetadata

from pallas.core.perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from pallas.core.perm.metadata_text import SCENE_AUTO, join_usage, usage_line
from pallas.product.llm.knowledge.declare import knowledge_source_row

from . import handlers as _handlers  # noqa: F401
from . import startup as _startup  # noqa: F401

__plugin_meta__ = PluginMetadata(
    name="自动夺舍",
    description="自动模仿群友名片，醉酒时还会闹出更夸张的改名效果。",
    usage=join_usage(
        usage_line("（自动）", "随机改牛牛名片；醉酒时可能夺舍群友"),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "menu_data": [
            {
                "func": "牛牛夺舍",
                "trigger_method": "scheduler",
                "trigger_scene": SCENE_AUTO,
                "trigger_condition": "随机模仿群友名片",
                "brief_des": "牛牛自动更换群名片",
                "detail_des": "牛牛会偶尔把自己的群名片换成群友的名字，有时还会顺手戳一下对方。",
            },
            {
                "func": "醉酒夺舍",
                "trigger_method": "scheduler",
                "trigger_scene": SCENE_AUTO,
                "trigger_condition": "牛牛醉酒时",
                "brief_des": "醉酒时随机更换群友名片",
                "detail_des": "喝醉后会闹得更大，除了改自己的名字，还有机会把别人也一起改名。",
            },
            {
                "func": "名片同步",
                "trigger_method": "on_notice",
                "trigger_scene": SCENE_AUTO,
                "trigger_condition": "被模仿者改名",
                "brief_des": "同步被取名用户的群名片",
                "detail_des": "如果被模仿的人后来改了名字，牛牛也会跟着一起改过来。",
            },
        ],
        "knowledge_sources": [
            knowledge_source_row(
                source_id="take_name.faq",
                title="自动夺舍说明",
                description="牛牛自动模仿群友名片",
                chunks=[
                    {
                        "title": "夺舍是什么",
                        "content": (
                            "牛牛会定时随机把自己的群名片改成群友的名字，有时还会戳一下对方；"
                            "这是自动行为，没有单独口令触发。"
                        ),
                        "keywords": "夺舍,改名,名片,模仿,自动",
                    },
                    {
                        "title": "醉酒夺舍",
                        "content": (
                            "牛牛喝醉后夺舍更夸张，除了改自己的名片，还可能随机修改群友名片；"
                            "可先让牛牛喝酒进入醉酒状态。"
                        ),
                        "keywords": "醉酒,喝醉,夺舍,改别人,名片",
                    },
                    {
                        "title": "名片同步",
                        "content": "若被模仿的群友后来改了名片，牛牛会同步更新自己的模仿名片。",
                        "keywords": "同步,跟随,改名,名片",
                    },
                ],
            ),
        ],
    },
)
