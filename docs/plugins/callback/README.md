# callback（回调处理）

为 **唱歌**、**聊天** 等异步任务提供 HTTP 出口：`POST /callback/{task_id}`，由外部 AI 服务在任务完成后回调；根据 `status` 向对应群发送文本或 base64 语音，并维护 `SingProgress` 等状态。

## 契约摘要

- 路径：`POST /callback/{task_id}`（FastAPI 挂在 NoneBot 应用上，见源码）。
- 表单字段：`status`（必填）、`text`、`song_id`、`chunk_index`、`key`、`file`（上传文件）等。
- `status=failed`：移除任务并发送固定失败提示。
- `status=success`：可选发 `text`、发语音 `file`；成功后移除任务。

## 依赖

- 需与 **sing / chat** 等写入 `TaskManager` 的插件及 AI 服务 **约定同一 task_id** 与可访问的 Bot 网络路径。

## 排障

| 现象 | 说明 |
|------|------|
| 404 Task not found | `task_id` 与 Bot 内存任务不一致或已过期。 |
| 回调成功但群无消息 | `get_bot(bot_id)` 失败（Bot 离线）；检查返回 JSON。 |

实现见 [`src/plugins/callback/__init__.py`](../../../src/plugins/callback/__init__.py)。
