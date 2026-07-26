# AI 扩展

::: tip
不启用 AI Runtime 时，复读、喝酒、轮盘等核心玩法照常可用。**默认 LLM 聊天**由 Bot 内核直连 Provider，**不必**安装 Pallas-Bot-AI。唱歌 / TTS 等媒体能力才需要 AI Runtime。
:::

本文按控制台点击顺序配置 **@ LLM 对话**；唱歌 / TTS 的部署见文末进阶。先了解组件边界可阅读 [LLM 对话、媒体与 AI Runtime](ai-runtime-choice.md)。

## 能力对照

| 能力 | 群里口令（示例） | 依赖 |
| --- | --- | --- |
| LLM 聊天 | @ 牛；见 [@牛牛与复读](llm-and-repeater.md) | Bot 内核 + Provider（默认） |
| 翻唱 / 点歌 | `牛牛唱歌 …`、`牛牛点歌 …` | 媒体能力包 + AI Runtime + 插件 |
| 酒后对话 | 喝酒状态下的智能聊天 | 同 LLM 聊天 |
| 文生图 | `牛牛画画 …` | 画画插件网关（默认不经 AI Runtime） |

精确口令以 **牛牛帮助** 为准。

## 硬件要求

| 方案 | 说明 |
| --- | --- |
| 仅聊天（云端 API） | 配好 Provider 即可；**无需** AI Runtime |
| 仅聊天（本机 Ollama） | CPU 可跑但较慢；内存建议 ≥8GB；Bot 直连 Ollama |
| 唱歌 / TTS | 建议 **NVIDIA ≥6GB** 显存；需 AI Runtime（`pallas-bot-ai:latest`） |

---

## 主路径：先让 @ 能聊

### 1. 打开控制台

浏览器进入 `http://<主机>:8088/pallas/`，登录后在 **AI 配置** 中打开 Provider 接入区域。先确认 Provider 测通结果。

### 2. 配置 Provider（接入）

在 **AI 配置 → 接入**：

1. 选择云端服务商或本地 Ollama  
2. 填写密钥 / Base URL 与模型  
3. **测通 Provider 并保存**（不要求 AI Runtime / `:9099` 可达）

`LLM_RUNTIME` 已兼容为 Bot 内核运行时；聊天无需 **媒体服务** 页测通。

### 3. 打开对话总闸

**AI 配置 → 对话**（或环境变量）：

| 键 | 说明 |
| --- | --- |
| **`LLM_CHAT_ENABLED`** | 智能对话总闸，默认关；打开后 @ / 接话走 Bot Provider |
| **`CHAT_ENABLE`** | 遗留酒后 RWKV，默认关；与上项独立，走 AI 仓 `/api/chat`（需 chat 资源包） |

WebUI 在同一页「功能开关」里：启用智能对话 / 启用遗留酒后 RWKV。二者都开时醉酒优先 LLM。

### 4. 验收

群里发：

```text
牛牛连通
```

或 `@牛牛` 试一句。失败时优先查 **接入** 的 Provider；聊天问题不要被媒体服务红灯误导。

---

## 聊得起来之后：AI 观测与对话策略

侧栏 **AI** 分两块：**AI 配置**（接入 / 对话 / 媒体）与 **AI 观测**（运行态查看与维护）。多数观测页需顶栏选定 Bot QQ，部分还需群号。

### AI 观测分段

| 分段 | 做什么 |
| --- | --- |
| 统计 | Token、画画、RAG 与任务成功情况 |
| 会话 | 查看对话、标注回复、试聊或清空上下文 |
| 记忆 | 群内长期记忆：图谱、条目与偏好 |
| 人物 | 人物事实、观察队列、账号口癖审批 |
| 工具 | 当前可调用的内置 / 插件 / MCP 工具（只读浏览） |
| 任务 | 提醒、周期与异步调研；可取消未完成任务 |
| 牛格 | 牛格状态、群风格画像，以及发给模型的人设 |
| 日志 | 媒体服务等扩展运行日志 |

人物事实默认只在本群生效；跨群复用需用户同意。口癖候选来自该 Bot 成功回复，在人物页「待审」里通过或驳回。任务结果只投递到对应群。

### 联网搜索

群里「搜一下…」「帮我搜…」会走工具 `web.search`。在 **AI 配置 → 对话 → 策略 → 联网搜索** 配置；两项都填才联网，留空时 Bot 会如实说搜不了。

推荐 [Tavily](https://app.tavily.com)（免费额度）：

| 字段 | 示例 |
| --- | --- |
| 搜索接口完整地址 | `https://api.tavily.com/search` |
| 搜索接口密钥 | `tvly-…` |

并确认同页 **允许调用工具** 已开。环境变量键为 `WEB_SEARCH_API_URL`、`TAVILY_API_KEY`。也可用其它兼容接口（`POST` + JSON `{"query":"…"}` + `Authorization: Bearer …`）。字段旁「？」有简短说明。

### 工具：何时交给模型

浏览清单用 **AI 观测 → 工具**；改触发说法与策略用 **AI 配置 → 对话 → 工具 / 策略**。

| 界面文案 | 含义 |
| --- | --- |
| 话题相关就带上（相关即带） | 话题与工具领域沾边时交给模型 |
| 说到触发词才带上（触发才带） | 平时不带；说到触发说法或经 `tools.find` 后才出现 |

后者更省上下文。开发向见 [Bot 内置 Agent 生命周期](/developer/architecture/agent-lifecycle)；HTTP 契约见 [Agent Platform API](/common/webui/api/09-agent-platform)；排障见 [LLM 与 AI](/maintainer/operate/llm-and-ai)。

---

## 进阶：唱歌 / TTS（媒体服务）

需要媒体时再装 AI Runtime：

### 连接 AI Runtime

在 **AI 配置 → 媒体服务**：

| 方式 | 做法 |
| --- | --- |
| **源码（推荐本机开发）** | 「安装 AI Runtime」：克隆同级 `Pallas-Bot-AI` 并 bootstrap；勾 **含唱歌/TTS**。 |
| **Docker 全栈** | 用主仓 compose 起 `pallasbot-ai`。见 [Docker 部署](/deploy/docker)。 |

控制台**不代跑** Docker。保存连接后，扩展基址会同步 Bot 侧 `AI_SERVER_*`。

然后：

1. **AI 配置 → 能力包 → 唱歌 · TTS · 媒体模型**
2. **源码**：
   - 任务包未开 →「重新安装（含媒体）」
   - 资源包可**分项下载 / 删除**（`sing_pallas` / `sing_pretrain` / `tts` 等）
   - 在同页选择**默认说话人**、**优先 SVC backend**（失败仍按 registry 回退）与 **TTS 参考音色**
3. **Docker**：页内只读就绪状态；下载请换 `pallas-bot-ai:latest` 并由启动脚本拉取；若 `data/` 卷可写，仍可切换默认说话人 / backend / 音色
4. 插件商店安装 **`pallas-plugin-ai-media`**（画画另装 `pallas-plugin-draw`）

插件安装步骤 → [安装插件](install-plugins.md)

---

## 相关文档

- 维护者安装细节 → [AI Runtime](/maintainer/install/ai-runtime)  
- 运维排障 → [LLM 与 AI](/maintainer/operate/llm-and-ai)  
- 接话策略 → [@牛牛与复读](llm-and-repeater.md)  
- 组件边界 → [LLM 对话、媒体与 AI Runtime](ai-runtime-choice.md)
