# AI 扩展

::: tip
不启用 AI 时，复读、喝酒、轮盘等核心玩法照常可用。**Pallas-Bot** 管 QQ 消息；**Pallas-Bot-AI** 管唱歌、画画、部分对话。两边均需运行。
:::

## 能力对照

| 能力 | 群里口令（示例） |
| --- | --- |
| 翻唱 / 点歌 | `牛牛唱歌 …`、`牛牛点歌 …` |
| 酒后对话 | 喝酒状态下的智能聊天 |
| 文生图 | `牛牛画画 …`（需 draw 扩展） |
| 随时闲聊 | @ 牛；见 [@牛牛与复读](llm-and-repeater.md) |

LLM 辅助接话（`LLM_REPEATER_MODE`：补位 / 润色等）见 [@牛牛与复读](llm-and-repeater.md)。

精确口令以 **牛牛帮助** 为准。

## 硬件要求

| 方案 | 说明 |
| --- | --- |
| NVIDIA 显卡 | 建议 **≥6GB** 显存 |
| 纯 CPU | 可运行但较慢，内存可能 **10GB+** |
| 云端 API | 可不跑本地大模型；仍须轻量 AI 服务，见 [remote-only](https://github.com/PallasBot/Pallas-Bot-AI/blob/main/docs/deploy/remote-only.md) |

## 1. 安装插件

| 能力 | 包 |
| --- | --- |
| 唱歌、酒后聊天 | `pallas-plugin-ai-media` |
| 画画 | `pallas-plugin-draw` |
| 随时闲聊 | core 自带 `llm_chat`（仍须 AI 服务在线） |

安装步骤 → [安装插件](install-plugins.md)

## 2. 启动 Pallas-Bot-AI

与主仓 **同级目录** 克隆 [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI)（版本尽量与 Bot 匹配）：

```bash
cd ../Pallas-Bot-AI
cp .env.example .env
```

至少配置以下项（以 AI 仓 README 为准）：

```env
LLM_CHAT_ENABLED=true
REDIS_URL=redis://127.0.0.1:6379/0
LLM_BACKEND_URL=http://127.0.0.1:11434
LLM_MODEL=qwen2.5:7b
```

按该仓文档启动 API（常见端口 `9099`）与 worker。

::: details 用 Docker 一次拉起
见 [Docker 部署 · 全栈](/deploy/docker)。
:::

## 3. 主仓打开总闸

在控制台 **AI 配置**（或环境变量）中设置：

| 键 | 默认 | 说明 |
| --- | --- | --- |
| **`LLM_CHAT_ENABLED`** | `false` | **总闸**。打开后酒后 LLM、随时 @、接话 AI 才生效 |
| `AI_SERVER_HOST` / `PORT` | `127.0.0.1` / `9099` | Pallas-Bot-AI 地址 |
| `LLM_REPEATER_MODE` | `both` | 接话是否用 AI → [@牛牛与复读](llm-and-repeater.md) |

::: tip
先启动 AI 服务，再在控制台填写地址。不确定缺什么时先跑 **AI 体检**。
:::

## 4. 验证

群里发：

```text
牛牛连通
```

或试一条唱歌 / 画画 / @ 闲聊口令。联调细节 → [LLM 与 AI](/maintainer/operate/llm-and-ai)
