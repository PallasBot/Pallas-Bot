# AI 扩展

::: tip
不启用 AI Runtime 时，复读、喝酒、轮盘等核心玩法照常可用。**默认 LLM 聊天**由 Bot 内核直连 Provider，**不必**安装 Pallas-Bot-AI。唱歌 / TTS 等媒体能力才需要 AI Runtime。
:::

本文按控制台点击顺序，带你把 **@ LLM 聊天** 跑通；唱歌 / TTS 见文末进阶。

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

浏览器进入 `http://<主机>:8088/pallas/`，登录后侧栏进入 **AI 配置**。不确定缺什么时点 **体检向导**。

### 2. 配置 Provider（接入）

在 **AI 配置 → 接入**：

1. 选择云端服务商或本地 Ollama  
2. 填写密钥 / Base URL 与模型  
3. **测通 Provider 并保存**（不要求 AI Runtime / `:9099` 可达）

遗留路径：若显式设置 `LLM_RUNTIME=ai_service`，聊天仍走 AI 扩展，此时才需 **媒体服务** 页测通。

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

或 `@牛牛` 试一句。失败时回到体检向导看哪一步红灯；聊天问题优先查 **接入** 的 Provider，不要被媒体服务红灯误导。

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
