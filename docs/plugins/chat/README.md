# chat（酒后聊天）

牛牛**醉酒**时可用 ChatRWKV 对话；需部署 [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI)。

## 用户命令

| 口令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| @牛牛 | 群内 | 醉酒时 AI 回复 |
| 牛牛 + 文本 | 群内 | 同上 |

## 命令权限

无独立命令 ID（依赖醉酒状态，非 cmd_perm 口令）。

## 配置

酒后聊天与随时 @ 闲聊共用全局 **`LLM_CHAT_ENABLED`**（默认关）。遗留 WebUI 键 `chat_enable` 仍可读，但请改配 `LLM_CHAT_ENABLED`。

[`config.py`](../../../src/plugins/chat/config.py) 中 `chat_enable`、`ai_server_host` 等已弃用，推荐在 WebUI **环境变量** 或 `pallas.toml` `[env]` 配置 `LLM_CHAT_ENABLED` 与 `AI_SERVER_*`。

## 排障

| 现象 | 处理 |
| --- | --- |
| 无回复 | 确认已喝酒、AI 服务可达、`LLM_CHAT_ENABLED=true` |
| 冷却 | 群级冷却内可能静默 |

## 实现

[`src/plugins/chat/`](../../../src/plugins/chat/)
