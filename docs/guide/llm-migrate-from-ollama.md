# 从旧版 ollama 迁到 llm_chat

3.x 用过 `plugins/ollama` 或 pip 包 `pallas-plugin-llm-chat`？  
升级后请改用内置 **`llm_chat`** + **`features/llm`** + **Pallas-Bot-AI（api ≥ 4.0.0）**。

## 变了什么

| 3.x | 现行 |
| --- | --- |
| `src/plugins/ollama/` 或 pip `pallas-plugin-llm-chat` | **core 内置** `llm_chat`（仓库里已无 `ollama` 插件目录） |
| 主仓直连 Ollama `/api/chat` | 主仓 → **Pallas-Bot-AI** → 统一 `/api/v1/chat/completions` |
| `CHAT_ENABLE` / `OLLAMA_ENABLE` 等分散开关 | **`LLM_CHAT_ENABLED` 总闸** + `LLM_*` 子项 |
| 无 repeater fallback/polish | `LLM_REPEATER_MODE`：`off` / `fallback` / `polish` / `both` |
| 无方舟 tool | `features/llm/tools` + `ARKNIGHTS_KB_ENABLED` |

酒后 `chat`、随时 @、接话 LLM **共用** `LLM_CHAT_ENABLED`；总闸关时子项不耗资源。

## 配置键对照

| 遗留键（`.env` / `webui.json`） | 现行键 | 说明 |
| --- | --- | --- |
| `CHAT_ENABLE` | `LLM_CHAT_ENABLED` | 智能对话总闸 |
| `OLLAMA_ENABLE` | `LLM_CHAT_ENABLED` | 同上，合并 |
| `OLLAMA_HOST` / `OLLAMA_PORT` | — | 删掉；改 **AI 仓** `AI_SERVER_HOST` / `AI_SERVER_PORT` |
| `OLLAMA_MODEL` | — | 改 AI 仓 `.env` 的 `LLM_MODEL` |
| `OLLAMA_SYSTEM_PROMPT` 等 | `llm_chat` 插件页 | 可选自定义人设文件；默认走 `compile_persona_prompt` |
| — | `LLM_REPEATER_MODE` | 接话 LLM，默认 `polish` |
| — | `LLM_TOOLS_ENABLED` | 方舟等 tool，默认 `true`（总闸开时生效） |
| — | `LLM_SESSION_ENABLED` | 多轮会话，默认 `true` |
| — | `LLM_GOVERNANCE_ENABLED` | 冷却/并发/字数，默认 `true` |

WebUI：**通用配置 → 智能对话与 AI 服务**；群风格开关在 **Bot 配置** 的 `group_style_enabled`。

## AI 仓路径（兼容旧客户端）

Pallas-Bot-AI 仍代理 deprecated 的 `/api/ollama/*`，方便旧客户端过渡；**新功能不要再加** ollama 专用路径。

主仓默认请求：

- 统一 Chat：`/api/v1/chat/completions`
- 删会话：`/api/v1/chat/completions/session`

启动时主仓探测 AI `/health`，要求 `api_version` **≥ 4.0.0**（见 `src/features/llm/startup_probe.py`）。

## 迁移步骤

1. 备份 `config/pallas.toml`、`data/pallas_config/webui.json`、`.env`。
2. 升级主仓，`uv sync`（按需 `--extra` 装玩法扩展）。
3. 部署 [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI)（与 Bot 匹配的版本），配置 `LLM_BACKEND_URL` / `LLM_MODEL`。
4. 在 WebUI 打开 **`LLM_CHAT_ENABLED`**，填写 `AI_SERVER_HOST` / `AI_SERVER_PORT`。
5. 删除或注释遗留 `CHAT_ENABLE`、`OLLAMA_*`；勿与 `LLM_*` 同名冲突。
6. 验收：日志出现 `LLM：可达 … v=4.x`；群内 @ 与（可选）接话 polish/fallback 正常。

一键探测：

```bash
uv run python tools/integration_llm_chat.py --ai-port 9099
uv run python tools/integration_repeater_llm.py --scenario both --ai-port 9099
```

## 口令与帮助

| 3.x | 现行 |
| --- | --- |
| 插件名 `ollama` | 帮助项 **`随时闲聊`**（`llm_chat`） |
| @牛牛 闲聊 | 不变；实现改走 `features/llm` |
| 无 | `牛牛连通`（`features/service_gateways`）测 AI 延迟 |

## 延伸阅读

- [AI 扩展](ai.md)
- [Bot ↔ AI 仓契约](../maintainer/operate/llm-and-ai.md)
- [llm_chat 插件说明](../plugins/llm_chat/README.md)
