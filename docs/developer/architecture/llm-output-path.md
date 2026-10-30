# LLM 输出路径

本页说明 MaiBot 接管后的输出边界，并保留旧内置 LLM 聊天的实现索引。[LLM 对话与复读](/guide/llm-and-repeater) 中的非 LLM 复读能力仍保留，旧 LLM 聊天入口不再启用。

## 当前输出边界

聊天 agent 由独立 MaiBot 承担：群消息先经过 Pallas ingress 的权限、审核与命令分类，命令仍在 Pallas 执行；桥范围内的聊天仅采集并转发，MaiBot 文本回投再经桥校验和 Pallas 发送队列。桥关闭、断线、配置无效或范围外时不回退旧 agent。协议及限制见 [统一消息入口](message-runtime.md#实验性-maibot-桥默认关闭)。

旧 LLM/酒后聊天 matcher 和 LLM direct handler 不再注册；纯语料主动发言、Repeater direct/复读接话、自动表情、跟图及 fanout RPC 保留，沿用现有开关与桥归属抑制以避免重复回复。`submit_chat_task`、kernel 聊天调度与 RWKV 聊天入口拒绝旧 LLM 生成。`llm_chat`、`ollama`、`chat` 任务拒绝新登记；历史任务回调原子领取后终止，不查找 Bot、不写入聊天结果、不调用媒体钩子或发送成功/失败回复。

共享 Provider、Embedding、贴纸标注、媒体助手及显式命令工具仍保留。绘图、歌曲和 TTS 沿原媒体 callback 投递。旧工具 HTTP 入口不再默认注册，不能充当 MaiBot 工具网关。详见 [Agent 生命周期](agent-lifecycle.md)。

### 共享 Provider 结果与用量

`complete_chat_message` 的成功消息可包含 `_provider_usage`：`prompt_tokens`、`completion_tokens`、`cache_read_tokens`、`cache_write_tokens` 和按这些归一化桶求和的 `total_tokens`。元数据属于该次请求结果，不依赖全局 observer；已有 Pallas 记账路径仍只记录一次，消费方不得因读取结果再次记账。缺少可解析计数时不附加该字段，明确的零计数与缺失不同；记账失败不丢弃已解析的结果用量，但也不表示账本已持久化成功。

标准 OpenAI 输入计数中的缓存读取部分从普通输入桶中扣除；Anthropic Messages 的 `input_tokens` 本身不含缓存读写，按显式协议保留。未文档化的供应方 cache-write 字段可能与输入重叠，不推断其额外计费语义。此结果接口不等同于 MaiBot Provider 插件、旧聊天日限额或完整 Agent 生命周期已接线。

### MaiBot 原生模型与预算

首次受管启动将旧模型、凭据及可映射的任务主备迁入 MaiBot，后续请求直接使用 MaiBot 原生客户端，不经 Pallas Provider HTTP 或 SDK 代理插件。原生 WebUI 的模型及插件管理保留，不再持续同步旧 Pallas 配置。

重试、模型选择、用量及预算遵循 MaiBot 原生行为；旧 Pallas 的每日额度、整轮 HTTP 尝试次数、时限和 key 轮换不会自动成为 MaiBot 的治理规则。多 key 迁为原生候选，`sequential` 每次从首项开始、失败才切换，不等价旧轮换。需要控制费用时应在原生配置或供应商侧设置，不能依赖 Pallas 的旧聊天开关/预算。

远程文本 Embedding 可迁为原生配置，本地进程内后端和 stub 不伪装成原生服务。MaiBot 记忆的向量空间与数据生命周期随后由其原生实现负责；更换模型不代表旧向量已重建。Pallas 保留自身媒体、标注与检索所需的共享 Provider/Embedding，两边配置及记账不再持续联动。

## 出口总闸

Pallas 共享 LLM 出口（`complete_chat_message`、`fetch_embeddings_sync`）仍受 `pallas.product.llm.availability.llm_calls_enabled` 约束：`LLM_CHAT_ENABLED` 为关，或 `llm_chat` 插件被全实例禁用时，不发请求。保留能力的后台循环与 work/embed 辅进程仍遵守各自作用域门禁。该开关不再启用旧聊天 agent，也不控制独立 MaiBot 的模型请求；不要为了退役旧聊天将它强制关闭而误伤 Embedding 或标注。治理细节见 [插件治理](plugin-governance.md)。

## 历史内置聊天实现（已退役）

下面的 LLM 流程、输出管线、telemetry、表达注入和预算记录仅供后续源码/数据清理时定位依赖，不是当前 LLM 运行流程；其中非 LLM Repeater 语料检索、投递与原始消息采集仍在使用。MaiBot 不自动继承旧 LLM 行为；历史数据不会自动删除或迁移。共享路由与媒体工具的保留不意味着旧 LLM 生成入口可重新启用。

### 原有两条出口

```text
群消息
 ├─ 统一 ingress 怒气门控 → 记录时间线；静默时停止后续副作用
 │  └─ @ / to_me → packages/llm_chat/chat_message.py
 │     persona +【表达参考】→ client.submit_chat_task
 │
 └─ 非 @ 接话 → packages/repeater/handlers/message.py
       → 原始候选检索、人格加权、过滤与去重
       → Repeater 直接投递原语料
```

普通聊天在 Bot 进程内执行：`submit_chat_task` 安排 `kernel_runner`。入口提交与异步 kernel 启动时检查总开关及 bot/群作用域；Provider 请求前后、工具执行前后、persona retry 前后和投递前也复核，避免排队或生成期间关闸后继续产生副作用。跳过时记录原因并清理任务；工具副作用已开始则只标记边界，不声称可回滚。通常由 kernel 调用 Provider、运行工具循环，并通过 `pallas/product/llm/delivery.py` 的 `deliver_llm_chat_result` 交给既有投递入口；若 semantic style 给出通过相关性与近期回复去重的 `direct_candidate`，并通过滚动窗口 15% 配额，kernel 会直接投递该真实语料而不调用 Provider。该判断不对语料内容作额外价值判断。Repeater 日常接话自身不创建 LLM 任务。

Repeater 回放入站消息时优先将 OneBot `original_message`（入站结构快照）序列化为 CQ；`get_message()` 返回的可变 `message` 可能已被预处理器修改。学习与 message outbox、扇出 payload 和全局消息记录共用这一原始结构，保留 Markdown、mface、mention 与 reply 字段。历史答案只在回复记录前跳过已确认无效的空 Markdown / 不可用 mface 整条消息；合法后续答案与未知扩展段仍保留，主动发言则在选择和去重记录前过滤同类无效句子。

工具循环会在模型提出 tool call 后执行工具、将结果追加回上下文并继续补全。默认工具集会按场景选择；延迟公开的工具可由 `tools.find` 发现，并在后续轮次加入可调用集合。查询工具有单轮调用预算、重复参数去重和最终回答阶段；副作用工具成功后才允许静默。延迟完成的外部工具只派发任务；任务结果由其自身通道回传，不阻塞当前 LLM 回复。

显式查询超过 3 秒且已经开始实际工具调用时，kernel 最多发送一次“我查一下。”进度气泡；发送前重新检查 live 开关。该气泡不写入会话历史、表达学习或最终答案上下文。

普通 `llm_chat` 单轮生成共享一个预算对象（`pallas/product/llm/turn_budget.py`）：从 kernel 开始生成计时（deadline 锚在 job 起始，不在首次 provider 调用另起时钟），限制墙钟时长与真实 HTTP 尝试次数（`llm_chat_turn_timeout_sec`、`llm_chat_turn_max_http_attempts`）。候选准备、provider 补全、工具续轮、final、persona retry 与内联工具（如 `chat.recent_summary` 的工具内模型调用，经 `ToolInvokeContext` 运行期透传）都经同一对象计数，换密钥 / 换 provider / required→auto 不重置；provider 每个协议在真正 `client.post` 前领取一次并把 httpx 分阶段超时钳到剩余。预算耗尽时不再发起新请求：deadline 前已启动的工具允许正常收尾并保留结果，门禁或 provider 等待期间到期的工具不会被启动；只有当本 turn 动作全部成功完成且无截断时，才复用已取得的 `chat.reply`，否则诚实静默，persona firewall 不再触发重试。未开放 / 被拒 / 失败的动作，以及后台受理（queued、尚未真正执行）都不算完成，会保守地抑制既有完成话术；后台受理结果与既有 durable 续行机制保留，不被取消。该时限不是整轮硬墙钟上限，工具收尾与取消清理可以超过，不计入队列、前置上下文与投递；后台 durable 记忆等独立异步任务不继承该预算、也不被父轮停止取消。

## 历史 LLM 输出管线

![LLM 输出管线与表达数据粒度](/assets/llm-output-path.svg)

`@` 对话在 Bot 进程内完成：Provider 返回文本后，从生成到发进群依次经过：

| 步骤 | 位置 | 说明 |
| --- | --- | --- |
| 表达语料直投 | `kernel_runner.py` | 表达库 `direct_candidate` 通过去重与配额时直接投递真实语料，跳过 Provider |
| 生成 + 工具循环 | `complete_with_tool_loop` | 模型提 tool call → 执行工具 → 结果回填上下文继续补全 |
| 人设输出防火墙 | `pallas/product/llm/persona_output_firewall.py` | 命中规则可带修正指令重试，或回落 fallback |
| JSON 契约解析 | `structured_reply.py` `parse_structured_reply` | 期望 `reply_segments` 数组逐条成气泡；纯文本退化单段 |
| 输出过滤 | `output_filter.py` | 语料污染词、续写残片、角色 / 形态守卫、长度硬闸（由 reply_shape 的 p50 段长推导 `reply_max_length`，超限找干净断点压短，否则回落 fallback） |
| 短气泡兜底拆分 | `reply_postprocess.py` `split_short_reply_segments` | short 取向但只有单段时，按句末标点 / 换行拆成多气泡 |
| 轻量后处理 | `apply_reply_postprocess` | 错别字、句尾句号 |
| 多气泡投递 | `delivery.py` `deliver_llm_callback_success` | 每个气泡发送前复核 live 开关；返回 `DeliveryOutcome`，`sent` / `partial` / `failed` / `silent` 由真实回执推导。部分发送保留已发事实且不写完整会话历史；气泡间按上句长度叠加随机抖动（0.5~3.5s） |
| 学习回写 | 会话 / `behavior_store` / `repeater_feedback` / `auto_episode` | 投递成功后写历史、行为与表达 |

发送队列的 `errors` 与 `errors_by_operation` 统计每次失败的适配器调用；重试后最终成功仍会保留先前失败次数。`message`、`interaction`、`other` 分桶用于区分正文投递、表情 / 戳一戳等互动和未分类 API，不等价于最终投递结果；`DeliveryOutcome` 仍按真实回执判断。

LLM 回调的文本发送会用异步上下文标记来源，供 `BaseBot.on_called_api` 的普通表情跟随后续任务继承；结构化表情走同一来源标记。LLM 来源在取图前及缓存读取后、实际发图前复核共享出口门禁。视觉表情任务将可选 `delivery.llm_origin` 持久化，work handler 与最终 dispatcher 继续检查；关闸时以固定原因落为 `failed`，不伪报 `sent`。缺少来源标记的既有视觉任务和 Repeater 发送保持原行为。

## 历史 LLM turn telemetry

LLM turn telemetry 从消息进入 `llm_chat` handler 后开始，以随机 `turn_id` 关联 `ingress`、speak perception、reply gate、necessity、submit、Provider、output 和 delivery 各阶段。Provider 保持空可用输出校验，并仅按协议结构把失败归为固定类别；拒绝、纯思考、截断、失败、无输出及未知原因不会把上游正文写入事件或作为 Bot 答复。首期不覆盖完全未匹配 `llm_chat` rule 的入站消息，也不改变任何门控、生成或投递决策。

事件写入独立的 `data/pb_webui/llm_telemetry/` JSONL 文件，并由按日 report 聚合。事件只保留固定 allowlist、文本形态与长度分桶，以及运行时 HMAC hash；不写入用户消息、Bot 回复、prompt、异常正文或原始 Bot/群/用户/消息 ID。`turn_id` 会随异步 TaskManager metadata 贯穿到 Provider 和 callback delivery。数值延迟分别表示上下文装配、每次 Provider 请求、任务登记至首条成功发送的文本气泡（不含进度泡）及投递入口至最后一次文本气泡发送尝试；发送队列等待目前无法按 LLM 请求拆分，保持未知。旧事件缺少新字段时不回填为 0。

可用 `uv run python tools/report_llm_latency.py --day YYYY-MM-DD` 只读汇总 JSONL 的样本数与 P50/P95；Provider 以每次请求尝试计数（重试单独计样），其他已接线指标以事件计数。脚本不调用或覆写线上按日报告。

Telemetry 是 best-effort 的旁路观测：写 key、序列化、目录或文件失败时只记录限频运维日志，不阻断聊天。完整 prompt 和消息内容仍属于独立的 runtime snapshot/trace 调试路径，不能把两类数据混为同一份报告。

## 历史表达数据粒度

| 数据 | 存储 | 粒度 | 影响 |
| --- | --- | --- | --- |
| 表达风格锚点 / 例句 | `repeater_semantic_style.py`（`profiles.json`） | **每 bot × 每群** 独立（key `bot_id:group_id:scene`） | 注入「群表达指导」block；重置命令只清本 bot 本群 |
| 回复画像（气泡数 / 节奏 / 长度） | group config `style_profile`（`group_profiler.py`） | **群维度共享** | 决定 `reply_shape` 的段数、节奏与长度取向；其 p50 段长再参与推导 `reply_max_length` 硬上限 |

同群不同 bot 的表达指导互不共享；回复画像是群统计，同群所有 bot 共用。WebUI 管理入口见 `packages/pb_webui/llm_product_api.py`。

## 历史 Prompt 组装

at-chat 系统提示词 `pallas/product/persona/at_chat_system_prompt.txt` 只承载背景 / 输出边界 / 群聊边界等不变原则，不再内嵌具体对话示范；接话的差异化由语义风格按 **bot × 群** 注入（见上表「群表达指导」「真人接话参考」）。`ChatPromptAssembler`（`pallas/product/llm/assembler/chat_prompt.py`）按变化频率从低到高依次组装：persona 核心 → 群表达指导 / 真人接话参考（随 profile 有数据才注入）→ 近期上下文（检索块 → 群时间线）→ reply_shape（回复形状与输出契约）→ turn policy → 当前时间 → 工具上下文，使支持前缀缓存的 Provider 可命中更长的稳定前缀。

## 任务路由与模型选择

Pallas 共享任务路由仍经 `resolve_endpoint_candidates_for_task(task)`（`pallas/product/llm/providers_store.py`）取提供方候选；下表也保留了旧聊天任务名，存在配置不表示任务仍会被调用。MaiBot 配置同步仅转换已支持的配置，不复用 Pallas 的运行期路由：

```text
routing.tasks[task]                       → 主提供方（WebUI 任务编排写入）
routing.task_backups[task]                → 全任务备用（可含 backup model）
routing.tier_backups[high|low]            → 档位备用（low 含记忆与后台任务）
routing.chain_fallback                    → 其余提供方兜底
provider.task_models[task] / default_model → 该提供方下的具体模型
```

任务分两类：

| 类别 | 任务 | 说明 |
| --- | --- | --- |
| high | `llm_chat`、`drunk` | WebUI「高级任务」主备 |
| low | `affect_refine`、`turn_decision`、`memory_episode`、`memory_person_facts`、`memory_ip_knowledge`、`memory_graph_extract`、`memory_graph_hiergraph`、`memory_session_summary`、`memory_tool_summary`、`llm.relationship.affinity`、`repeater.semantic_style` | WebUI「低级任务」主备 |
| 独立 | `sticker_vision` | 「全任务」视图单独指定；无配置时回落到提供方 `default_model` |

后台与记忆任务调用频次远高于对话且无需强模型，因此并入低档：在 WebUI 改一次低档主备即可全部生效；没有独立配置时仍回落到提供方 `default_model`。

## 关键锚点

| 步骤 | 位置 |
| --- | --- |
| Repeater 候选与投递 | `packages/repeater/responder.py`、`packages/repeater/handlers/message.py` |
| LLM 群级表达指导 | `pallas/product/llm/repeater_semantic_style.py`（注入消费）；`pallas/product/llm/group_insight_processor.py`（从 message 表重建成对样本，批量标注落盘） |
| 表达库存取 / 学习 | `pallas/product/persona/expression_*.py` |
| 进程内投递 | `pallas/product/llm/delivery.py`（`deliver_llm_chat_result`）；`kernel_runner.py` 调用 delivery |
| 媒体 / HTTP callback 壳 | `pallas/core/platform/ai_callback/runner.py`（薄壳，复用 delivery） |
| 配置键 | `pallas/product/llm/config.py`；WebUI 段见 `env_sections.py`（侧栏 **AI 配置**） |

群洞察的调度、8 个候选对的批量含义、持久化游标、预算和记忆层批量边界见[群洞察与语义风格指导器](group-insight-semantic-style.md)。

## AI 回调与内部 IPC 鉴权边界

- **服务身份**：AI→Bot 的 `/callback/*` 继续校验 AI Bearer（`ai_extension.json` 的 token，或 `PALLAS_AI_API_TOKEN` / `TTS_API_TOKEN`）；空配置拒绝、常量时间比较。旧 `/pallas/api/internal/llm/tools/execute` 不再默认注册，其历史鉴权代码不是 MaiBot 工具接入。见 `pallas/core/platform/ai_callback/ai_bearer.py`。
- **旧聊天终止**：内部登记认证后，旧聊天类型返回 HTTP 410 `legacy_agent_retired`；晚到回调在领取旧任务后返回 HTTP 200 `{"message":"ok","status":"legacy_agent_retired"}`，不进入旧投递。任务类型按去空白和小写精确区分，不将包含 `chat` 的整个语音任务集合一并禁用。
- **内部 IPC**：work aux→Bot 的任务登记/删除（`/pallas/api/internal/ai/tasks*`）强制 `X-Pallas-Internal-Token`，由共享根密钥 `data/pallas_console/session_secret.bin` 按固定用途标签 HMAC-SHA256 派生（`internal_auth.py`），根密钥不下发 AI/浏览器；loopback 仅纵深防御。
- **解析前有界**：`boundary_guard.py` 对上述入口先 header 鉴权、再按实际 ASGI receive 字节累计，超限 413（Content-Length 仅快速拒绝，chunked 同样有界）；JSON 2MiB、回调单文件 64MiB、字段/文本/trace/history 另有限额，初值可用 repo 设置覆盖。鉴权相关 header（`Authorization` / `X-Pallas-Internal-Token` / `X-Pallas-Api-Key`）重复出现视为歧义直接 400；畸形或超长 Content-Length 记 400/413，不做无界 `int()`。
- **原子领取与终态**：有 Redis 协调时，登记、领取、取消各自用单个短 Lua 脚本原子完成——登记在同一次调用内检查终态、比较不可变绑定与受保护内容（`song_id`/来源消息段）后创建；领取一次完成取记录、删键与写终态（无独立门，空记录不触碰键）；取消写终态并删键。同一 ID 至多领取一次、终态在 TTL 内不得复活；协调已启用但不可用（client 缺失/读写异常）统一抛 `AiTaskRedisError` 映射 503，不静默降级。无协调 unified 仍在本地锁内领取并即落终态。
- **协调意图与健康分离**：任务路径以配置意图判定是否必须走 Redis（`coord_redis_configured`：mode 非 `false` 且有 URL），ping 健康（`coord_redis_enabled`）只决定该次调用能否成功，不用它决定本地权威；要求协调而不可用时登记/领取/取消一律失败关闭，本地已有记录也不获胜。其他 coord 消费者仍按「配置 + ping」做可用性降级。
- **pending 查询纯读**：待处理任务查询（song 绑定 peek、hub 路由、tools 上下文）缺失或过期返回「未找到」，不写终态、不取消该 ID；读取故障抛 `AiTaskRedisError`，在 song peek / hub / tools 边界映射 503（不降级为 404/500），且不产生写。取消只有在共享终态提交成功后才确认成功（DELETE 失败映射 503），失败后本地不落终态。
- **hub→worker 转发**：hub 先认证/校验/限字节再转发，只构造必需 auth header、不转 Cookie/Forwarded，`trust_env=False` 且不跟随重定向；worker 侧同样校验 AI Bearer，保留 413 等不可重试状态。

## 历史内置生成约束

- 怒气门控发生在 direct runtime 与 matcher 之前。静默不是丢弃入站消息：消息仍持久化并带 `suppressed_by_rage=true`，但不会被视为 Bot 已回复，也不会进入 LLM、工具或 Repeater 处理。
- 攻击增量由攻击词数量、短窗口连续攻击次数和当前怒气共同决定；75 分进入静默，低于 75 才恢复。静默期间不重复累积怒气、不重复扣好感、不延长截止时间。

- 日常接话只使用 Repeater 语料，不调用 LLM 生成、选句、润色或拼接。
- `@`、follow-up 与工具回合独立走 `llm_chat`。
- Repeater 学到的群级表达可以只读注入 `llm_chat`；其中有界 `direct_candidate` 仅替代本次 `llm_chat` Provider 补全，不反向控制 Repeater 候选与投递。
- 在线链路不再存在 Repeater 的 select、polish 或 fallback LLM 任务。
- 表达库当前是**单群**；跨群另开任务，不要默认同库检索。

## 后续阅读

- [LLM 输出护栏与离线评测](llm-output-guardrails.md)
- [Agent 生命周期与旧链路退役](agent-lifecycle.md)
- [架构总览](overview.md)
- [LLM 与 AI 运维](/maintainer/operate/llm-and-ai)
