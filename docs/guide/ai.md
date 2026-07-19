# AI 扩展

::: tip
不启用 AI 时，复读、喝酒、轮盘等核心玩法照常可用。**Pallas-Bot** 管 QQ 消息；**Pallas-Bot-AI** 管唱歌、画画、部分对话。两边均需运行。
:::

本文按控制台点击顺序，带你把 **@ 闲聊** 跑通；唱歌 / TTS 见文末进阶。

## 能力对照

| 能力 | 群里口令（示例） |
| --- | --- |
| 随时闲聊 | @ 牛；见 [@牛牛与复读](llm-and-repeater.md) |
| 翻唱 / 点歌 | `牛牛唱歌 …`、`牛牛点歌 …`（需媒体能力包 + 插件） |
| 酒后对话 | 喝酒状态下的智能聊天 |
| 文生图 | `牛牛画画 …`（需 draw 扩展） |

精确口令以 **牛牛帮助** 为准。

## 硬件要求

| 方案 | 说明 |
| --- | --- |
| 仅闲聊（云端 API） | 可不跑本地大模型；仍须轻量 AI 服务，见 [remote-only](https://github.com/PallasBot/Pallas-Bot-AI/blob/main/docs/deploy/remote-only.md) |
| 仅闲聊（本机 Ollama） | CPU 可跑但较慢；内存建议 ≥8GB |
| 唱歌 / TTS | 建议 **NVIDIA ≥6GB** 显存；Docker 需 **`pallas-bot-ai:latest`**（非默认 slim） |

---

## 主路径：先让 @ 能聊

### 1. 打开控制台

浏览器进入 `http://<主机>:8088/pallas/`，登录后侧栏进入 **AI 配置**。不确定缺什么时点 **体检向导**。

### 2. 安装 / 连接 AI Runtime

在 **AI 配置 → AI 服务**：

| 方式 | 做法 |
| --- | --- |
| **源码（推荐本机开发）** | 「安装 AI Runtime（源码）」：克隆同级 `Pallas-Bot-AI` 并 bootstrap。仅闲聊可勾 **remote-only**；要唱歌再勾 **含唱歌/TTS**。 |
| **Docker 全栈** | 用主仓 `docker-compose.full.yml` 一次拉起 Bot + AI + Ollama。默认 AI 镜像为 **slim**（LLM-only）。见 [Docker 部署](/deploy/docker)。 |

控制台**不代跑** Docker。保存连接后，扩展基址会同步 Bot 侧 `AI_SERVER_*`。

### 3. 打开对话总闸

**AI 配置 → 对话**（或环境变量）：

| 键 | 说明 |
| --- | --- |
| **`LLM_CHAT_ENABLED`** | 总闸，默认关；打开后 @ / 接话 AI 才生效 |

### 4. 拉取对话模型

**AI 配置 → 能力包** 或 **接入**：

1. 确认 AI 服务可达  
2. 在本地模型区选择 `qwen2.5:7b`（或云端 Provider 的模型）  
3. 勾选 **切换时拉取** 并切换  

全栈默认**不**预拉 Ollama 模型。可选：compose 加 `--profile pull-models`。

### 5. 验收

群里发：

```text
牛牛连通
```

或 `@牛牛` 试一句。失败时回到体检向导看哪一步红灯。

---

## 进阶：唱歌 / TTS

对话模型就绪后，再开媒体：

1. **AI 配置 → 能力包 → 唱歌 · TTS · 媒体权重**  
2. **源码**：若任务包未开 →「重新安装（含媒体）」；权重缺失 →「下载默认媒体权重」  
3. **Docker slim**：按页内说明把 `PALLAS_AI_IMAGE` 改为 `pallasbot/pallas-bot-ai:latest`（可选叠 GPU compose），重启后看启动日志解压；**不要**指望 Ollama 拉取唱歌权重  
4. 插件商店安装 **`pallas-plugin-ai-media`**（画画另装 `pallas-plugin-draw`）

插件安装步骤 → [安装插件](install-plugins.md)

---

## 相关文档

- 维护者安装细节 → [AI Runtime](/maintainer/install/ai-runtime)  
- 运维排障 → [LLM 与 AI](/maintainer/operate/llm-and-ai)  
- 接话策略 → [@牛牛与复读](llm-and-repeater.md)
