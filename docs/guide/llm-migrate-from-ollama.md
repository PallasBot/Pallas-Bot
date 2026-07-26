# 从旧版 ollama 迁到 llm_chat

3.x 用过 `plugins/ollama` 或 pip 包 `pallas-plugin-llm-chat`？  
升级后请改用 Bot 内置的 **`llm_chat`** 与 `pallas/product/llm`。普通聊天不再经 Pallas-Bot-AI。

## 变了什么

| 3.x | 现行 |
| --- | --- |
| `src/plugins/ollama/` 或 pip `pallas-plugin-llm-chat` | **core 内置** `llm_chat`（仓库里已无 `ollama` 插件目录） |
| 主仓直连 Ollama `/api/chat` | Bot 内核经已配置的 Provider 调用模型 |
| `CHAT_ENABLE` / `OLLAMA_ENABLE` 等分散开关 | **`LLM_CHAT_ENABLED`**（LLM）与遗留 **`CHAT_ENABLE`**（RWKV）可并存 |
| 无 repeater fallback/polish | `LLM_REPEATER_MODE`：`off` / `select` / `select_polish_lite` / `select_fallback` / `fallback` |
| 无方舟 tool | `pallas/product/llm/tools` + `ARKNIGHTS_KB_ENABLED` |

酒后 `chat`、随时 @、接话 LLM 共用 **`LLM_CHAT_ENABLED`**（Bot 内核 Provider）。  
遗留酒后 **RWKV** 仍由 **`CHAT_ENABLE` / `chat_enable`** 控制（打 AI 仓 `/api/chat`），与 LLM 总闸独立；两者都开时醉酒优先走 LLM。

## 配置键对照

| 遗留键（`.env` / `webui.json`） | 现行键 | 说明 |
| --- | --- | --- |
| `CHAT_ENABLE` | （保留）`CHAT_ENABLE` / 插件 `chat_enable` | 遗留酒后 RWKV，与 LLM 总闸独立 |
| `OLLAMA_ENABLE` | `LLM_CHAT_ENABLED` | 合并进 LLM 总闸 |
| `OLLAMA_HOST` / `OLLAMA_PORT` | Provider 接入配置 | 在 Bot WebUI「AI 配置 → 接入」填写 Base URL |
| `OLLAMA_MODEL` | Provider 接入配置 | 在 Bot WebUI 为 Provider 选择模型 |
| `OLLAMA_SYSTEM_PROMPT` 等 | `llm_chat` 插件页 | 可选自定义人设文件；默认走 `compile_persona_prompt` |
| — | `LLM_REPEATER_MODE` | 接话策略，使用上表的五种模式 |
| — | `LLM_TOOLS_ENABLED` | 方舟等 tool，默认 `true`（总闸开时生效） |
| — | `LLM_SESSION_ENABLED` | 多轮会话，默认 `true` |
| — | `LLM_GOVERNANCE_ENABLED` | 冷却/并发/字数，默认 `true` |

WebUI：在 **AI 配置 → 接入** 配置并测试 Provider，再在智能对话配置中打开 `LLM_CHAT_ENABLED`；群风格开关在 **Bot 配置** 的 `group_style_enabled`。

## Pallas-Bot-AI 的保留用途

Pallas-Bot-AI 是可选的媒体 sidecar，提供唱歌、TTS、绘图等媒体任务，以及遗留 RWKV 酒后 `/api/chat`。这些任务才需要 `AI_SERVER_HOST` / `AI_SERVER_PORT`、`:9099` 与 callback；普通 `@` 聊天、接话和会话管理均在 Bot 内完成。

## 迁移步骤

1. 备份 `config/pallas.toml`、`data/pallas_config/webui.json`、`.env`。
2. 升级主仓，`uv sync`（按需 `--extra` 装玩法扩展）。
3. 在 Bot WebUI **AI 配置 → 接入** 配置 Provider、模型与密钥，并完成连通性测试。
4. 在智能对话配置中打开 **`LLM_CHAT_ENABLED`**。需要遗留 RWKV 酒后时，再部署 [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI)、配置 `AI_SERVER_HOST` / `AI_SERVER_PORT`，并打开 **`CHAT_ENABLE`**。
5. 删除或注释遗留 `OLLAMA_*`；**`CHAT_ENABLE` 可保留**（只要还要用 AI 仓 RWKV 酒后路径）。
6. 验收：Provider 测试成功，群内 `@牛牛` 与（可选）接话正常；媒体或 RWKV 任务另验收 AI Runtime 与 callback。

一键探测：

```bash
uv run python tools/integration_llm_chat.py
uv run python tools/integration_repeater_llm.py --scenario both
```

## 口令与帮助

| 3.x | 现行 |
| --- | --- |
| 插件名 `ollama` | 帮助项 **`智能对话`**（`llm_chat`；旧名「随时闲聊」仍可匹配） |
| @牛牛 闲聊 | 不变；实现改走 `pallas/product/llm` |
| 无 | `牛牛连通`（`pallas/product/service_gateways`）测媒体服务延迟 |

## 延伸阅读

- [AI 扩展](ai.md)
- [Bot ↔ AI 仓契约](../maintainer/operate/llm-and-ai.md)
- [llm_chat 插件说明](../plugins/llm_chat/README.md)
