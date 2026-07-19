"""超管私聊：切换 / 卸载本地推理模型（不出现在用户帮助图）。"""

from __future__ import annotations

from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent, PrivateMessageEvent
from nonebot.params import CommandArg

from pallas.core.perm import private_message_permission_for_command
from pallas.product.llm.model_admin import get_runtime_model, switch_runtime_model, unload_runtime_model

switch_model_cmd = on_command(
    "换模型",
    aliases={"牛牛换模型"},
    priority=5,
    block=True,
    permission=private_message_permission_for_command("llm_chat.switch_model"),
)

unload_model_cmd = on_command(
    "卸模型",
    aliases={"牛牛卸模型"},
    priority=5,
    block=True,
    permission=private_message_permission_for_command("llm_chat.unload_model"),
)


@switch_model_cmd.handle()
async def handle_switch_model(event: MessageEvent, args: str = CommandArg()) -> None:
    if not isinstance(event, PrivateMessageEvent):
        return
    model = str(args or "").strip()
    if not model:
        try:
            current = await get_runtime_model()
        except Exception as exc:
            await switch_model_cmd.finish(f"读取当前模型失败：{exc}")
            return
        await switch_model_cmd.finish(f"当前模型：{current}\n私聊发送：换模型 <Ollama 模型名>")
        return
    try:
        result = await switch_runtime_model(model, pull=True)
    except Exception as exc:
        await switch_model_cmd.finish(f"切换模型失败：{exc}")
        return
    resolved = str(result.get("model") or model).strip()
    await switch_model_cmd.finish(f"已切换模型：{resolved}（无需重启 Celery，旧权重已卸载）")


@unload_model_cmd.handle()
async def handle_unload_model(event: MessageEvent) -> None:
    if not isinstance(event, PrivateMessageEvent):
        return
    try:
        await unload_runtime_model()
    except Exception as exc:
        await unload_model_cmd.finish(f"卸载模型失败：{exc}")
        return
    await unload_model_cmd.finish("已请求卸载当前本地模型；下次对话将按新配置重新加载。")
