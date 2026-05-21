from __future__ import annotations

from nonebot import get_bot, logger
from nonebot.adapters.onebot.v11 import MessageSegment
from pydantic import BaseModel, Field

from .config import get_maa_config
from .store import maa_store


class GetTaskRequest(BaseModel):
    user: str = ""
    device: str = ""


class GetTaskResponse(BaseModel):
    tasks: list[dict] = Field(default_factory=list)


class ReportStatusRequest(BaseModel):
    user: str = ""
    device: str = ""
    task: str = ""
    status: str = ""
    payload: str = ""


async def maa_get_task(body: GetTaskRequest) -> GetTaskResponse:
    from src.common.shard.coord.maa_route_registry import register_maa_user_route

    register_maa_user_route(body.user)
    cfg = get_maa_config()
    await maa_store.touch_seen(body.user, body.device, cfg.maa_seen_ttl_seconds)
    if not await maa_store.is_device_verified(body.user, body.device):
        return GetTaskResponse(tasks=[])
    tasks = await maa_store.pending_tasks_for(body.user, body.device)
    return GetTaskResponse(tasks=tasks)


async def maa_report_status(body: ReportStatusRequest) -> dict[str, str]:
    task = await maa_store.mark_reported(body.task)
    if not task:
        if body.task:
            logger.debug(
                "maa reportStatus: 未知或已汇报任务 id={}（多为牛牛重启后 MAA 重试汇报，可忽略）",
                body.task,
            )
        return {"message": "ok"}

    notify = task.notify
    try:
        bot = get_bot(str(notify.bot_id))
    except Exception:
        logger.warning("maa reportStatus: bot {} offline, task={}", notify.bot_id, body.task)
        return {"message": "ok"}

    lines = [f"MAA 任务 {body.task} 已结束：{body.status}"]
    if task.task_type == "HeartBeat":
        running = body.payload or "（当前无顺序任务）"
        lines.append(f"正在执行的任务：{running or '无'}")
    elif task.task_type in {"CaptureImage", "CaptureImageNow"} and body.payload:
        lines.append("截图如下：")
        msg_text = "\n".join(lines)
        segments = [MessageSegment.text(msg_text), MessageSegment.image(f"base64://{body.payload}")]
    else:
        if body.payload:
            lines.append(body.payload[:500])
        segments = [MessageSegment.text("\n".join(lines))]

    try:
        if notify.group_id:
            await bot.send_group_msg(group_id=notify.group_id, message=segments)
        else:
            await bot.send_private_msg(user_id=notify.user_id, message=segments)
    except Exception as exc:
        logger.warning("maa reportStatus notify failed task={}: {}", body.task, exc)
    return {"message": "ok"}


def current_maa_http_paths() -> tuple[str, str]:
    from .endpoints import normalize_http_path

    cfg = get_maa_config()
    return (
        normalize_http_path(cfg.maa_get_task_path),
        normalize_http_path(cfg.maa_report_status_path),
    )
