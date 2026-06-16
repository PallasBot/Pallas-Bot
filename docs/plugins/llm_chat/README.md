# llm_chat（随时闲聊）

群内 @牛牛 多轮 LLM 对话；推理后端由 Pallas-Bot-AI 提供。

## 命令权限

| 命令 ID | 默认等级 | 说明 |
| --- | --- | --- |
| `llm_chat.chat` | everyone | 群内 @牛牛 多轮对话 |
| `llm_chat.clear` | everyone | `@牛牛 clear` 清空本会话记忆 |
| `llm_chat.unload` | staff | `@牛牛 unload` 卸载模型（群管/号主） |
| `llm_chat.set_model` | superuser | `@牛牛 model [模型名]` 查询或热更换模型 |

遗留 ID `ollama.*` 仍可读权限覆盖。

## 配置

[`config.py`](../../../src/plugins/llm_chat/config.py) 字段以 WebUI **插件 → llm_chat** 为准（落盘 `data/pallas_config/webui.json`，保存后热重载）。也可在 **`config/pallas.toml` 的 `[env]`** 写同名键，合并顺序见 [settings-storage](../../architecture/settings-storage.md)。

| 键 | 环境变量 | 说明 |
| --- | --- | --- |
| `llm_chat_enable` | `LLM_CHAT_ENABLE` | 是否启用，默认 `false` |
| `ollama_enable` | `OLLAMA_ENABLE` | **已弃用**，等同 `llm_chat_enable` |
| `llm_chat_system_prompt_path` | `LLM_CHAT_SYSTEM_PROMPT_PATH` | 可选自定义 prompt；留空用内置 `system_prompt.txt` |

`chat` / `sing` / `llm_chat` 在对应开关关闭时不会出现在帮助总览中。

## 排障

| 现象 | 处理 |
| --- | --- |
| 无回复 | `llm_chat_enable=true`（Bot 与 AI 侧均需就绪） |
| 人设不对 | 检查 `system_prompt.txt` 或 `llm_chat_system_prompt_path` |
| 与酒后聊天混淆 | 本插件随时 @ 可用；`chat` 须先喝酒 |

## 源码

[`src/plugins/llm_chat/`](../../../src/plugins/llm_chat/)
