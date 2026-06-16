# llm_chat（随时闲聊）

群内 @牛牛 多轮 LLM 对话；推理后端由 Pallas-Bot-AI 提供（当前默认 Ollama，可换 vLLM 等）。

## 命令权限

| 命令 ID | 默认等级 | 说明 |
| --- | --- | --- |
| `llm_chat.chat` | everyone | 群内 @牛牛 多轮对话 |
| `llm_chat.clear` | everyone | `@牛牛 clear` 清空本会话记忆 |
| `llm_chat.unload` | staff | `@牛牛 unload` 卸载模型（群管/号主） |
| `llm_chat.set_model` | superuser | `@牛牛 model [模型名]` 查询或热更换模型 |

遗留 ID `ollama.*` 仍可读权限覆盖。

## 配置

[`config.py`](../../../src/plugins/llm_chat/config.py) 字段以 WebUI **插件 → llm_chat** 为准（落盘 `data/pallas_config/webui.json`）。旧插件名 `ollama` 的配置键仍兼容读取。

| 键 | 环境变量 | 说明 |
| --- | --- | --- |
| `llm_chat_enable` | `LLM_CHAT_ENABLED` | 是否启用 @牛牛 LLM 闲聊，默认 `false` |
| `ollama_enable` | `OLLAMA_ENABLE` | **已弃用**，等同 `llm_chat_enable` |
| `llm_chat_system_prompt_path` | — | 可选自定义 prompt；留空用 `compile_persona_prompt` |

全局 AI 地址：`AI_SERVER_HOST` / `AI_SERVER_PORT`（见 [settings-storage](../../architecture/settings-storage.md)）。

模型、温度等推理参数仅在 **Pallas-Bot-AI** 侧配置。

## 排障

| 现象 | 处理 |
| --- | --- |
| 无回复 | WebUI `llm_chat_enable=true`；AI 侧 `LLM_CHAT_ENABLED=true` |
| 人设不对 | 检查 `llm_chat_system_prompt_path` 或牛格 prompt |
| 与酒后聊天混淆 | 本插件随时 @ 可用；`chat` 须先喝酒 |

## 源码

[`src/plugins/llm_chat/`](../../../src/plugins/llm_chat/)
