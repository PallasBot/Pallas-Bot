from fastapi import File, Form, UploadFile
from nonebot import get_app
from nonebot.plugin import PluginMetadata

from src.common.bot_runtime.roles import is_hub_role
from src.common.cmd_perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from src.common.cmd_perm.metadata_text import join_usage, usage_line
from src.common.shard.coord.ai_callback_forward import forward_ai_callback_to_worker

from .handler import run_ai_callback

app = get_app()

__plugin_meta__ = PluginMetadata(
    name="任务回调",
    description="接收 AI/唱歌等异步任务 HTTP 回调并推送结果。",
    usage=join_usage(
        usage_line("POST /callback/{task_id}", "维护者配置 AI 服务回调地址"),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "menu_data": [
            {
                "func": "任务回调",
                "trigger_method": "http",
                "help_audience": "maintainer",
                "trigger_condition": "/callback/{task_id}",
                "brief_des": "接收任务状态回调",
                "detail_des": "根据回调结果更新任务状态并发送群消息或语音。",
            },
        ],
    },
)


@app.post("/callback/{task_id}")
async def callback(
    task_id: str,
    status: str = Form(...),
    text: str | None = Form(None),
    song_id: str | None = Form(None),
    chunk_index: int | None = Form(None),
    key: int | None = Form(None),
    file: UploadFile | None = File(None),  # noqa: B008
):
    if is_hub_role():
        return await forward_ai_callback_to_worker(
            task_id,
            status=status,
            text=text,
            song_id=song_id,
            chunk_index=chunk_index,
            key=key,
            file=file,
        )
    return await run_ai_callback(
        task_id,
        status=status,
        text=text,
        song_id=song_id,
        chunk_index=chunk_index,
        key=key,
        file=file,
    )
