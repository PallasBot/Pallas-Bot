# chat（酒后聊天）

仅在牛牛 **醉酒**（群内发送`牛牛喝酒`）时生效：群内 **@牛牛** 或消息以 **「牛牛」开头** 时，将短文本发往本机 **AI 聊天服务**，通过任务系统异步回复（可与 TTS 联动）。

## 前置条件

1. `chat_enable=true`（默认关闭）。
2. AI 服务地址与 [`callback`](../callback/README.md) 可互通，逻辑与 `sing` 类似依赖 HTTP 与任务 ID。

## 配置

见 [`src/plugins/chat/config.py`](../../../src/plugins/chat/config.py)：`ai_server_host`、`ai_server_port`、`chat_endpoint`、`del_session_endpoint`、`tts_enable`。

## 排障

| 现象 | 说明 |
|------|------|
| 不回复 | 未醉酒、未 `@` / 未以「牛牛」开头、`chat_enable` 为 false、或群冷却中。 |
| 醒酒后不回复 | 设计如此；醒酒时会请求 AI 服务删除 session（见 `on_sober_up`）。 |

实现见 [`src/plugins/chat/__init__.py`](../../../src/plugins/chat/__init__.py)。
