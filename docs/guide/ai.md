# AI 扩展

::: tip
不启用 AI Runtime 时，复读、喝酒、轮盘等核心玩法照常可用。**LLM 聊天**（@ 对话）默认在 Bot 内核直连 OpenAI 兼容 Provider，不必再起 Pallas-Bot-AI。唱歌等媒体能力仍可选部署 **AI Runtime**。
:::

本文按控制台点击顺序，带你把 **LLM 聊天** 跑通；唱歌 / TTS 见文末进阶。

## 能力对照

| 能力 | 群里口令（示例） |
| --- | --- |
| LLM 聊天 | @ 牛；见 [@牛牛与复读](llm-and-repeater.md) |
| 翻唱 / 点歌 | `牛牛唱歌 …`、`牛牛点歌 …`（需媒体能力包 + 插件） |
| 酒后对话 | 喝酒状态下的智能聊天 |
| 文生图 | `牛牛画画 …`（插件直连网关，见画画插件） |

精确口令以 **牛牛帮助** 为准。

## 硬件要求

| 方案 | 说明 |
| --- | --- |
| 仅 LLM 聊天（云端 API） | 在 Bot 配置 Provider（`LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`）即可；无需 9099 / Redis / Celery |
| 仅 LLM 聊天（本机 Ollama） | 将 `LLM_BASE_URL` 指到 `http://127.0.0.1:11434/v1`；CPU 可跑但较慢；内存建议 ≥8GB |
| 唱歌 / TTS | 建议 **NVIDIA ≥6GB** 显存；需可选 AI Runtime，Docker 用 **`pallas-bot-ai:latest`**（非默认 slim） |

---

## 主路径：先让 LLM 聊天可用

### 1. 打开控制台

浏览器进入 `http://<主机>:8088/pallas/`，登录后侧栏进入 **AI 配置** 或通用配置中的智能对话段。不确定缺什么时点 **体检向导**。

### 2. 配置 Provider（内核默认）

默认 **`LLM_RUNTIME=bot_kernel`**。在通用配置 / 环境变量填写：

| 键 | 说明 |
| --- | --- |
| **`LLM_BASE_URL`** | OpenAI 兼容基址（兼容别名 `LLM_REMOTE_BASE_URL`） |
| **`LLM_API_KEY`** | 云端 Key；本地 Ollama 可留空（别名 `LLM_REMOTE_API_KEY`） |
| **`LLM_MODEL`** | 模型名，如 `gpt-4o-mini` / `qwen2.5:7b`（别名 `LLM_REMOTE_MODEL`） |

显式设 `LLM_RUNTIME=ai_service` 时，才走旧的 Pallas-Bot-AI HTTP + Celery 路径，并需配置 `AI_SERVER_*`。

### 3. 打开对话总闸

**AI 配置 → 对话**（或环境变量）：

| 键 | 说明 |
| --- | --- |
| **`LLM_CHAT_ENABLED`** | 总闸，默认关；打开后 @ / 接话 LLM 才生效 |

### 4. （可选）AI Runtime 仅媒体

唱歌等仍走 **AI 配置 → AI 服务** 安装或连接 Runtime。LLM 聊天不依赖此项；连接页保存后扩展基址会同步 `AI_SERVER_*`（供媒体与兼容路径）。

**Docker 全栈**：`docker-compose.full.yml` 已注入 `AI_SERVER_HOST=pallasbot-ai`；控制台探测该地址，**不会在 Bot 容器内 clone** AI 仓。

### 5. 验收

群里发：

```text
牛牛连通
```

或 `@牛牛` 试一句。失败时检查 Provider 与 `LLM_CHAT_ENABLED`，或回到体检向导。

---

## 进阶：唱歌 / TTS

对话模型就绪后，再开媒体：

1. **AI 配置 → 能力包 → 唱歌 · TTS · 媒体权重**  
2. **源码**：若任务包未开 →「重新安装（含媒体）」；权重缺失 →「下载默认媒体权重」  
3. **Docker slim**：按页内说明把 `PALLAS_AI_IMAGE` 改为 `pallasbot/pallas-bot-ai:latest`（可选叠 GPU compose），重启后看启动日志解压；**不要**指望 Ollama 拉取唱歌权重  
4. 插件商店安装 **`pallas-plugin-ai-media`**（画画用 `pallas-plugin-draw` 直连网关）

插件安装步骤 → [安装插件](install-plugins.md)

---

## 相关文档

- 维护者安装细节 → [AI Runtime](/maintainer/install/ai-runtime)  
- 运维排障 → [LLM 与 AI](/maintainer/operate/llm-and-ai)  
- 接话策略 → [@牛牛与复读](llm-and-repeater.md)
