# Bot 内置 Agent 生命周期

Pallas-Bot 的普通 LLM 聊天在 Bot 进程内完成。本文说明维护者修改这条路径时的职责边界和排查入口。

用户侧的配置和能力选择见 [LLM 对话、媒体与 AI Runtime](/guide/ai-runtime-choice)。

## 一次对话如何执行

![Pallas-Bot LLM Agent 生命周期：触发判定、上下文装配、本轮决策、kernel、输出护栏、投递与异步沉淀](/assets/agent-lifecycle-overview.svg)

| 环节 | 责任 | 主要位置 |
| --- | --- | --- |
| 消息入口 | 将 `@` 聊天或接话请求转换为 LLM 任务 | `packages/llm_chat/`、`packages/repeater/` |
| 任务决策 | 根据场景、开关和抽签决定是否进入生成路径 | `pallas/product/llm/kernel/` |
| 上下文装配 | 组织会话、人格、记忆和知识上下文 | `pallas/product/llm/assembler/context.py` |
| 工具装配 | 按场景选择工具，携带已激活的延迟工具 | `pallas/product/llm/assembler/tools.py`、`tools/registry.py` |
| 工具循环 | 执行 tool call，将结果回填给模型继续生成 | `pallas/product/llm/tool_loop.py` |
| 投递与追踪 | 发送结果，并记录状态、工具调用和拒绝原因 | `pallas/product/llm/delivery.py`、`kernel_runner.py`、`runtime_debug.py` |
| 回复后沉淀 | 异步写入会话、表达与记忆数据 | `pallas/product/llm/memory/`、`pallas/product/persona/` |

`Pallas-Bot-AI` 不参与这条普通聊天路径。它负责媒体任务和遗留 RWKV；不要为普通 `@` 聊天增加 AI Runtime callback。

## 工具与可见性

工具注册表保存名称、参数、能力标签和可见性。默认工具集只包含当前场景需要的能力，避免把所有工具放进每次求。

| `visibility` | 控制台文案 | 行为 |
| --- | --- | --- |
| `visible`（默认） | 相关即带 / 话题相关就带上 | 意图域命中后随场景注入 |
| `deferred` | 触发才带 / 说到触发词才带上 | 仅自身 hints 命中，或经 `tools.find` 激活后注入 |

盘点口语（如「你会啥」「有哪些…」）会额外打开查询通道：注入 `tools.find`，并对命中域内的只读/清单类工具本轮忽略 deferred，避免空口编造能力。插件可在 `llm_command_tool_row` 声明 `capabilities=["read_only"]`；未声明时按工具名（list/search/…）启发式推断。

模型需要低频能力时，可以调用 `tools.find`。匹配到的延迟工具会加入本轮后续调用，并在短时间内保留给同一会话范围。副作用工具仍经过既有安全和确认策略；被拦截的原因会写入运行追踪。

WebUI 可覆盖单工具的描述、hints 与可见性（**AI 配置 → 接话 → 工具**）。联网搜索工具 `web.search` 依赖 `WEB_SEARCH_API_URL` 与 `TAVILY_API_KEY`，见 [AI 扩展 · 联网搜索](/guide/ai#联网搜索)。

新增工具优先复用注册表与能力标签，不要绕过工具循环直接在消息入口执行。

## 记忆和检索

上下文装配会按开关读取会话、群记忆、关系便签和知识源。检索模式由 `effective_vector_retrieve_mode` 决定：

- 配置 `stub` embedding，或 embedding 调用失败时，使用关键词检索。
- 配置并成功调用真实 embedding 时，才使用向量或混合检索。

这是运行时降级策略，不应把配置中的 `hybrid` 直接当成实际检索方式。排障时查看运行追踪和 [LLM 与 AI 运维](/maintainer/operate/llm-and-ai)。

### 接话触发的上下文差异

非 `@` 接话（无 to_me）走感知判定后才进入生成路径。感知触发方式（`speak_trigger`）不同，会话与时间线注入也有差：

| speak_trigger | 触发场景 | 群聊时间线注入 |
| --- | --- | --- |
| `followup` | `@` 后限时窗口内同人补话 | 8 条 |
| `mention` | 消息含牛牛别名 | 8 条 |
| `alias` | 别名硬触发 | 8 条 |
| `ambient` | 无人提及，环境感知抽签接话 | 4 条（短时间线，防话痨偏题） |

`to_me` 及上述硬触发均注入完整群聊时间线；`ambient` 感知接话只注入最近 4 条短时间线，其余上下文（会话、记忆、关系、知识）组装与 `to_me` 一致。实现见 `packages/llm_chat/chat_message.py` 的 `build_recent_group_timeline_context` 调用。

### 观察队列、人物事实与口癖

除传统群记忆条目外，运行时还可维护：

| 能力 | 用途 | 控制台 |
| --- | --- | --- |
| 观察队列 | 待整理的候选片段，供后续沉淀 | AI 观测 → 人物 |
| 人物事实 | 群内稳定偏好；跨群复用需同意 | AI 观测 → 人物 |
| 表情包习惯 | 确定性统计群友发送的图片表情，跨阈值后沉淀为「常用表情包：caption」人物事实（`source="sticker_habit"`），随人物事实注入与展示 | AI 观测 → 人物 |
| 关系便签与好感度 | 对用户的稳定关系备注；好感度分档注入对话、低好感度提高静默概率。正文来源：人工教导、规则观察句式、以及好感度 LLM 兜底顺带归纳的稳定特征句（仅限当前消息直接表达的身份/称呼/偏好/关系事实，经确定性准入拦截推断与人格评判，与好感度强弱解耦） | AI 观测 → 人物 |
| 教学写入防线 | 记忆/关系便签写入前过下流词表 + 贬损教学审查（`vulgar_lexicon.memory_guidance_block_reason`）；裸「记住XX」教学变体拒沉淀；同用户教学式消息短窗累计触发相加热冷却（`teach.py`） | — |
| 怒气与静默 | 按 `(bot, group, user)` 短期累积攻击压力；达到阈值后在统一 ingress 静默，但仍保留时间线消息 | AI 观测 → 人物 |
| 任务编排 | 提醒、周期与异步调研；结果只回群 | AI 观测 → 任务 |

HTTP 契约见 [Agent Platform API](/common/webui/api/09-agent-platform)。主要代码：`pallas/product/llm/memory/`、`sticker_habit.py`、`orchestration/`、`persona/`。

表情包习惯是独立于 LLM 归纳的确定性沉淀管线：bot 进程每 30 分钟增量扫描 `message` 表（按 `(time, message_id)` 复合游标），把消息里的 CQ:image 码（与采集同源截断）join `image_cache` 取 `content_hash`，累加进 `user_sticker_stat`（按 `(group_id, user_id, content_hash)` 唯一，不带 bot 维度）；跨过 `llm_sticker_habit_min_count` 的最爱图经 `sticker_label` 的 caption 投影为人物事实，归属每群解析出的语义采集 bot，未标注的图主动借用 realtime 标注预算补标。`send_count` 是「可归因发送次数下界」（图片采集限流、下载失败、缓存周期清理均造成漏计）；QQ 商城表情（mface）暂不计入。

怒气、好感和自动牛格是三个并行状态：怒气是可衰减的短期惩罚，好感是长期关系，自动牛格是账号级表达指纹。攻击事件可以按确定性规则降低好感，但不会修改牛格；好感也不会反向增加怒气。静默区分“收消息、记录消息、处理消息、回复消息”：静默消息仍写入会话和群时间线并标记 `suppressed_by_rage`，但不执行命令、工具、LLM、Repeater 或其它回复副作用。

## 修改后的验证

| 改动 | 优先验证 |
| --- | --- |
| 上下文、工具装配 | `tests/product/llm/test_context_assembler.py`、`test_tool_assembler.py` |
| 工具循环或发现 | `tests/product/llm/test_tool_discovery_loop.py`、相关工具测试 |
| 检索或 embedding | `tests/features/test_embedding_client.py`、`test_vector_retrieve_backend.py` |
| 投递、会话或接话 | `tests/features/test_llm_client.py`、`test_conversation_kernel.py`、`tests/plugins/repeater/` |

完成局部验证后，执行仓库约定的 Ruff 检查。完整的入口与投递接线见 [LLM 输出路径](llm-output-path.md)。
