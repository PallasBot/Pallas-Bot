# pallas-plugin-llm-chat

Pallas-Bot 官方扩展：**随时闲聊**（群内 @牛牛 多轮对话）。

## 安装

```bash
uv sync --extra plugins-llm-chat
```

默认 **`llm_chat_enable=false`**，须在 WebUI 或 `pallas.toml` 开启。

## 命令权限（默认）

| 命令 ID | 默认等级 |
| --- | --- |
| `llm_chat.chat` | everyone |
| `llm_chat.clear` | everyone |
| `llm_chat.unload` | staff |
| `llm_chat.set_model` | superuser |

遗留 `ollama.*` 命令 ID 仍可读 WebUI 覆盖。

## 配置

WebUI **插件 → llm_chat** 或 `config/pallas.toml` `[env]`：

| 键 | 说明 |
| --- | --- |
| `llm_chat_enable` | 是否启用 |
| `llm_chat_system_prompt_path` | 可选自定义 prompt 文件 |

完整键：[`src/pallas_plugin_llm_chat/config.py`](src/pallas_plugin_llm_chat/config.py)

内置人设：[`system_prompt.txt`](src/pallas_plugin_llm_chat/system_prompt.txt)

## 依赖

- [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI) 推理服务
- Bot 侧 `AI_SERVER_HOST` / `AI_SERVER_PORT`（或插件内 `ai_server_*`）

模型热更换见 [Pallas-Bot-AI 部署文档](https://github.com/PallasBot/Pallas-Bot-AI/blob/main/docs/Deployment.md#ollama-配置参考)。

## 文档

| 文档 | 链接 |
| --- | --- |
| 随时闲聊 · 用户文档 | [文档站 · llm_chat](https://PallasBot.github.io/Pallas-Bot-Docs/plugins/llm_chat) |

## 源码

[`src/pallas_plugin_llm_chat/`](src/pallas_plugin_llm_chat/)
