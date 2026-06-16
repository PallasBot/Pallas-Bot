# callback（任务回调）

> **4.0 起已收进内核**：HTTP 路由与执行分别在 [`platform/ai_callback/http.py`](../../../src/platform/ai_callback/http.py) 与 [`runner.py`](../../../src/platform/ai_callback/runner.py)。本目录插件已移除。

接收唱歌、智能对话等异步任务的 HTTP 回调，更新任务状态并向 QQ 推送结果。

## 用户命令

无。端点：`POST /callback/{task_id}`（维护者配置智能对话等服务回调地址）。

## 排障

| 现象 | 处理 |
| --- | --- |
| 404 | `task_id` 不存在或已过期 |
| 无群消息 | 查任务关联群号与 Bot 在线状态；若协议端发送失败，回调可能返回 `{"message": "failed"}` |

## 实现

- HTTP + hub 转发：`platform/ai_callback/http.py`、`platform/shard/coord/ai_callback_forward.py`
- 回调执行与 `task_type` 策略：`platform/ai_callback/`
