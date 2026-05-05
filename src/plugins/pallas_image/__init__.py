from nonebot.plugin import PluginMetadata

__plugin_meta__ = PluginMetadata(
    name="牛牛画画",
    description="在群里发送「牛牛画画」，让牛牛按你的话画图；也可以带上参考图一起改",
    usage="""
在群内直接发：
· 「牛牛画画」后面跟上你想画的内容，例如：牛牛画画 一只戴斗篷的羊
· 若要参考某张图：发「牛牛画画」同时附图，或者回复某一张图片，支持多图
限制了画画次数，用完会提示
    """.strip(),
    type="application",
    homepage="https://github.com/PallasBot",
    supported_adapters={"~onebot.v11"},
    extra={
        "version": "3.0.0",
        "menu_data": [
            {
                "func": "牛牛画画",
                "trigger_method": "on_command",
                "trigger_condition": "发送「牛牛画画 …」",
                "brief_des": "按你的话生成图，或按参考图改图",
                "detail_des": "支持纯文字描述，也可附带一张或多张参考图；失败时牛牛会用大白话或简短提示说明原因。",
            },
        ],
        "menu_template": "default",
    },
)

from . import draw as _pallas_draw  # noqa: E402, F401
