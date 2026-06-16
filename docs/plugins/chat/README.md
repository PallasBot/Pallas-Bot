# chat（酒后聊天）

牛牛**醉酒**时可用 ChatRWKV 或 LLM 对话；需部署 [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI)。

## 用户命令

| 口令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| @牛牛 | 群内 | 醉酒时 AI 回复 |
| 牛牛 + 文本 | 群内 | 同上 |

## 命令权限

无独立命令 ID（依赖醉酒状态，非 cmd_perm 口令）。

## 配置

新用户只需配置全局 **`LLM_CHAT_ENABLED`**（默认关）：开启后酒后聊天与随时 @ 闲聊共用同一 LLM 服务。

遗留 **`CHAT_ENABLE`** / 插件 `chat_enable` 仍可读：仅在**未显式配置** `LLM_CHAT_ENABLED` 时启用酒后 **RWKV**（`POST /api/chat`），用于零迁移升级。

[`config.py`](../../../src/plugins/chat/config.py) 中 `ai_server_host` 等已弃用，请在 WebUI **环境变量** 或 `pallas.toml` `[env]` 配置 `AI_SERVER_*` 与 `LLM_CHAT_ENABLED`。

## 排障

| 现象 | 处理 |
| --- | --- |
| 无回复 | 确认已喝酒、AI 服务可达；LLM 路径需 `LLM_CHAT_ENABLED=true`，遗留路径需 `CHAT_ENABLE=true` |
| 冷却 | 群级冷却内可能静默 |

## 实现

[`src/plugins/chat/`](../../../src/plugins/chat/)
