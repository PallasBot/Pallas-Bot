# pallas-plugin-ollama

Pallas-Bot 4.0 官方扩展：**随时闲聊**（本地 Ollama 多轮对话）。

## 安装

需已安装 [Pallas-Bot](https://github.com/PallasBot/Pallas-Bot) **≥ 4.0**，并部署 [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI)（Ollama 在 AI 仓侧配置）。

```bash
uv sync --extra plugins-ollama
```

默认 **`ollama_enable=false`**，须在 WebUI 或 `pallas.toml` 开启。

## 功能说明

群内 **@牛牛** 多轮对话；与「酒后聊天」（RWKV，`plugins-ai-media`）独立。

### 用户命令

| 口令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| @牛牛 + 消息 | 群内 | 多轮对话 |
| @牛牛 clear | 群内 | 清空本会话记忆 |
| @牛牛 unload | 群内 | 卸载 Ollama 模型 |
| @牛牛 model [模型名] | 群内或私聊 | 查询或热更换模型（超管） |

### 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `ollama.chat` | everyone |
| `ollama.clear` | everyone |
| `ollama.unload` | staff |
| `ollama.set_model` | superuser |

### 配置

WebUI **插件 → ollama** 或 `config/pallas.toml` `[env]`：

| 键 | 说明 |
| --- | --- |
| `ollama_enable` | 是否启用 |
| `ai_server_host` / `ai_server_port` | Pallas-Bot-AI 地址 |
| `ollama_system_prompt_path` | 可选自定义 prompt 文件 |

完整键：[`src/pallas_plugin_ollama/config.py`](src/pallas_plugin_ollama/config.py)

内置人设：[`system_prompt.txt`](src/pallas_plugin_ollama/system_prompt.txt)

### 排障

| 现象 | 处理 |
| --- | --- |
| 无回复 | 确认 `OLLAMA_ENABLE=true`、AI 与 Ollama 可达 |
| 与酒后聊天混淆 | 本插件随时 @ 可用；`chat` 须先喝酒 |

模型热更换见 [Pallas-Bot-AI 部署文档](https://github.com/PallasBot/Pallas-Bot-AI/blob/main/docs/Deployment.md#ollama-配置参考)。

## 文档

| 说明 | 链接 |
| --- | --- |
| 随时闲聊 · 用户文档 | [文档站 · ollama](https://PallasBot.github.io/Pallas-Bot-Docs/plugins/ollama) |
| 插件开发入门 | [develop/plugin/getting-started](https://PallasBot.github.io/Pallas-Bot-Docs/develop/plugin/getting-started) |

## 源码

[`src/pallas_plugin_ollama/`](src/pallas_plugin_ollama/)
