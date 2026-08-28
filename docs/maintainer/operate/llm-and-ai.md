# LLM 与 AI 运维

本页按现象排查 LLM 对话、记忆与媒体任务。普通 LLM 聊天走 Bot Provider；Pallas-Bot-AI 仅用于媒体 / 遗留 RWKV。

::: warning 排障：无回复与记忆失效
`@` 无回复或记不住旧事时，优先查：`LLM_CHAT_ENABLED`、**接入** Provider 是否测通。媒体任务才查 AI Runtime / callback。
:::

## 优先确认

1. **`LLM_CHAT_ENABLED`** 是否为开（总闸关闭时不会聊天）
2. **Provider**（AI 配置 → 接入）是否可达；默认聊天不依赖 `:9099`
3. 媒体任务：**AI Runtime**（`AI_SERVER_*`）与 **callback** 是否回到 Bot

再查任务与会话状态是否可观察。

## LLM 对话 / 记忆不生效

```mermaid
flowchart TD
  Start[LLM 对话或记忆不生效] --> Gate{LLM_CHAT_ENABLED 已开?}
  Gate -->|否| OpenGate[打开总闸并保存配置]
  Gate -->|是| Prov{Provider 测通?}
  Prov -->|否| FixProv[检查接入页密钥模型与 Base URL]
  Prov -->|是| Emb{需要向量检索?}
  Emb -->|hybrid或embedding| EmbOk{embeddings 可用?}
  EmbOk -->|否| Fallback[会回落关键词或修 embeddings]
  EmbOk -->|是| Store{PG 记忆或 knowledge 有数据?}
  Emb -->|只要关键词| Store
  Store -->|否| Teach[教一句记住或检查 data/pallas_knowledge]
  Store -->|是| Deeper[再查 runtime-overview]
```

## Bot 与 AI Runtime

| 组件 | 职责 |
| --- | --- |
| `Pallas-Bot` | LLM Agent、Provider 调用、会话、工具循环与消息投递 |
| `Pallas-Bot-AI` | 唱歌、TTS 等媒体任务，以及遗留 RWKV 酒后 `/api/chat` |

功能不可用时，先分清是聊天（Provider）还是媒体（Runtime）。

## 相关配置

- `LLM_CHAT_ENABLED`
- Provider（WebUI「AI 配置 → 接入」）
- `AI_SERVER_HOST` / `AI_SERVER_PORT`（仅媒体 / RWKV）

::: warning
`LLM_CHAT_ENABLED` 未开时，即使 AI 后端在线也不会触发多数LLM 对话能力。
:::

## 群洞察与语义风格

群表达画像和普通 LLM 对话是两条不同的后台链路。消息先写入 `message` 表，主进程约每 6 小时扫描活跃群并向 `work aux` 投递 `group.insight` 任务；work aux 再批量标注新发现的真人接话，成功后更新语义样本和画像。因此，配置刚打开或群里刚产生新对话后，页面不会立即出现结果。

| 项目 | 默认 / 位置 | 说明 |
| --- | --- | --- |
| 语义标注每日预算 | `LLM_SEMANTIC_STYLE_REALTIME_DAILY_LIMIT`，5000 次/天 | 按实际 LLM 请求计数；批量请求算 1 次，retry 另计 |
| 语义样本 | `data/pb_webui/repeater_semantic_style/examples.jsonl` | 通过质量判断的前句→接话样本 |
| 语义画像 | `data/pb_webui/repeater_semantic_style/profiles.json` | 按 Bot × 群 × 场景重建的注入数据 |
| 增量游标 | `data/pb_webui/repeater_semantic_style/semantic_style_group_cursors.json` | 记录各 Bot/群已处理到的消息时间 |
| 预算计数 | `data/pb_webui/repeater_semantic_style/semantic_style_label_budget.json` | 按天记录已占用的标注请求数 |

### 群表达页面没有数据

按下面顺序判断：

1. 页面选择的 `bot` 和 `group` 是否是目标范围。语义画像按 Bot × 群隔离，同一群的另一只 Bot 可能还没有样本。
2. 是否只等待了几分钟。语义扫描约 6 小时一轮，样本标注还要经过 work aux 消费；短时间没有新增属于正常情况。
3. 用 `uv run pallas logs -f --all` 或查看 `data/pallas_work/logs/work.log`，确认主进程是否记录「群洞察扫描已入队」，以及 work aux 是否记录产出、预算跳过或失败；产出日志为 debug 级别时可能不会显示在默认日志级别中。
4. 查看 `data/pb_webui/repeater_semantic_style/` 下的 `profiles.json`、`examples.jsonl` 和游标文件，区分“没有合格样本”和“任务未执行”。

「回复形态」不读取语义样本画像，而是由 `group_style_refresh` 根据群消息统计独立刷新，通常约 20 分钟一轮。语义样例有数据但回复形态为空，或二者更新时间不同，不代表同一条链路故障。

预算达到上限时，日志会记录软跳过；任务不会记为失败，也不会推进语义游标，下一天自动继续。LLM 请求失败或 retry 失败同样不会推进游标。

## 按现象检查

### `@` LLM 对话无响应

- `LLM_CHAT_ENABLED` 是否开启
- WebUI「AI 配置 → 接入」中 Provider、模型、密钥与 Base URL 是否测试成功
- Bot 日志是否出现 Provider 调用、工具循环或投递失败
- 不要先查 `:9099`、AI Runtime 或 callback；它们不在普通聊天路径上

### 媒体任务发出但无结果

- AI runtime 是否已接收任务
- callback 是否打回 Bot
- Bot 是否成功处理 callback

### 页面显示媒体服务离线

- AI runtime 进程是否运行
- Bot 到 AI 的地址配置
- 网络与端口是否可达

## 控制台接口

排前端或反代问题时可直接访问：

| 接口 | 用途 |
| --- | --- |
| `/pallas/api/auth/setup-status` | 是否仍处默认密钥 / 首次引导 |
| `/pallas/api/common-config/llm/runtime-overview` | health、模型、任务统计、conversation kernel |

## 记忆与 session

多轮 **session** 与群记忆由 **Bot 内核**落盘（PG / Mongo）；聊天不再经 AI 仓维护 session。

| 层级 | 位置 | 用途 |
|------|------|------|
| 会话窗口 | Bot `session_store`（PG / Mongo） | 群内多轮可见历史 |
| 超长摘要 | Bot session metadata `session_summary` | 窗口外压缩上下文 |
| 群记忆（teach / auto_episode） | Bot PG / Mongo `llm_memory_entry` | 「记住：」与启发式旧事；`LLM_VECTOR_RETRIEVE` 使用 real embedding 时由 Bot Provider 配置；`stub` 或 embedding 调用失败时实际回落关键词检索 |
| 关系便签 | Bot PG / Mongo | 对用户的稳定关系备注 |
| 知识源 | 插件声明 + `data/pallas_knowledge/` | FAQ / 本地文档块注入 |

### 群记忆 / RAG 开关

| 变量 | 默认 | 说明 |
|------|------|------|
| `LLM_MEMORY_RAG_ENABLED` | 开 | 群记忆读写与注入 |
| `LLM_VECTOR_RETRIEVE` | `hybrid` | 关键词+向量；真实向量由 Embedding 提供方决定，stub 或失败时回落关键词 |
| `LLM_EMBEDDING_PROVIDER` | （空=自动） | `stub` 占位 / `openai` 远程 / `local` 本机；空则按模型名推断 |
| `LLM_EMBEDDING_MODEL` | `stub` | 模型标识；`stub` 为占位。`openai` 且仍写 stub 时实际用 `text-embedding-3-small`；`local` 时可留 stub（默认 `BAAI/bge-small-zh-v1.5`） |
| `LLM_EMBEDDING_PROVIDER_ID` | （空） | Provider 名册 id；选中后走该线路的 base_url/密钥。空则回落对话主线 |
| `LLM_EMBEDDING_BASE_URL` / `API_KEY` | （空） | 可选手填；覆盖名册 / 对话主线 |
| `LLM_EMBEDDING_API_BACKENDS` | `[]` | 备线 JSON；由「Embedding 线路」面板维护 |

### 怎么开真实 Embedding

控制台：**AI 配置 → 接话 → 记忆**。

1. **群记忆检索**保持开；检索模式建议 `hybrid`（或 `embedding`）。
2. **向量提供方**选「远程（OpenAI 兼容）」；本机选「本机（fastembed）」并安装依赖（见下）。
3. 仅当向量提供方为「远程」时，在 **Embedding 线路**点 **添加网关** 选 Provider 或手填；本机 / 占位无需配线路。
4. 保存后点上方 **探测**：应显示「语义可用」。DeepSeek 官方多数无 `/embeddings`，改用兼容网关。
5. 换模型后旧记忆向量可能对不上，等后台回填或重新写入记忆。

本机依赖（用 pip 装包，不要对含 editable 插件的环境跑会裁剪依赖的 `uv sync --extra`）：

```bash
uv pip install 'fastembed>=0.5'
```

等价落盘（`data/pallas_config/webui.json` 或环境变量）：

```text
LLM_EMBEDDING_PROVIDER=openai
LLM_EMBEDDING_MODEL=text-embedding-3-small
LLM_EMBEDDING_PROVIDER_ID=<名册里的 id>
```

本机：

```text
LLM_EMBEDDING_PROVIDER=local
```

本机路径需要 **`REDIS_URL`（或分片协调用 Redis）** 与 **embed 辅进程**（`bot_embed`）：`uv run pallas run unified` / `restart` 在条件满足时会自动拉起；热路径经 Redis 队列，避免在 ingress 进程里加载 fastembed。无 Redis 时不会启辅进程，也不会在热路径做本机 embed。排障：`uv run pallas status`、`uv run pallas logs`（看 `data/pallas_embed/logs/embed.log`）。

| 变量 | 默认 | 说明 |
|------|------|------|
| `LLM_MEMORY_AUTO_EPISODE_ENABLED` | 开 | 有价值发言自动写入 episode |
| `LLM_KNOWLEDGE_SOURCES_ENABLED` | 开 | 知识源总闸 |
| `LLM_KNOWLEDGE_FILE_INGEST_ENABLED` | 开 | 扫描 `data/pallas_knowledge/` |
| `LLM_RELATIONSHIP_NOTES_ENABLED` | 开 | 关系备注 |

模型也可通过 tools `memory.search` / `memory.save` 主动检索与写入。控制台：`GET/POST /pallas/api/llm/conversation-kernel/memory`、`GET /pallas/api/llm/knowledge/sources`。

排障：会话「记不住」先查 `LLM_SESSION_ENABLED`、Provider 是否测通，以及数据库是否已初始化（PG 或 Mongo）。群记忆 / 关系便签同需对应开关与存储就绪；向量检索异常时回落关键词。

人物事实、观察队列、口癖与任务见控制台 **AI 观测**；分段说明见 [AI 扩展 · 观测与策略](/guide/ai#聊得起来之后ai-观测与对话策略)。

### 联网搜索不生效

群里「搜一下…」却说搜不了，或日志出现 `web_search_unconfigured`：

1. **AI 配置 → 接话 → 策略 → 联网搜索**：`WEB_SEARCH_API_URL` 与 `TAVILY_API_KEY` 是否都已填  
2. 地址是否为完整 URL（推荐 `https://api.tavily.com/search`，须含 `/search`）  
3. 同页 **允许调用工具**（`LLM_TOOLS_ENABLED`）是否开启  
4. 保存后是否已热载；仍无效时重启 Bot 再试  

推荐填法见 [联网搜索](/guide/ai#联网搜索)。

## callback（媒体 / RWKV）

媒体或遗留 RWKV 任务在 AI Runtime 成功，不等于群里一定能收到结果。中间还经过：

1. callback 回到 Bot
2. Bot 路由到正确上下文
3. 最终消息发送

「AI 端执行成功但群里没消息」时，同时查 Bot 侧路由与发送。普通 `@` 聊天不走 callback。

## 纯远端 API

未部署本地模型、仅用第三方 OpenAI 兼容 API 时，在 Bot WebUI「AI 配置 → 接入」配置 Provider、模型与密钥即可；不需要部署 Pallas-Bot-AI。

## 相关阅读

- [AI 扩展](/guide/ai)
- [AI Runtime 安装](/maintainer/install/ai-runtime)
- [排障](troubleshooting.md)
- [架构总览](/developer/architecture/overview)
- [FAQ](/deploy/faq)
