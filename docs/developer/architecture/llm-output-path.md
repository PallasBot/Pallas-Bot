# LLM 输出路径

本页标出普通聊天与接话的代码入口，方便改接线。用户向说明见 [LLM 对话与复读](/guide/llm-and-repeater)。

普通 `@` 聊天走 Bot Provider，在 Bot 进程内完成；不要为这条路径增加 Pallas-Bot-AI / `:9099` / HTTP callback。媒体与遗留 RWKV 另见 [Agent 生命周期](agent-lifecycle.md) 与运维文档。

## 两条出口

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

普通聊天在 Bot 进程内执行：`submit_chat_task` 安排 `kernel_runner`。通常由后者调用 Provider、运行工具循环，并通过 `pallas/product/llm/delivery.py` 的 `deliver_llm_chat_result` 交给既有投递入口；若 semantic style 给出通过相关性与近期回复去重的 `direct_candidate`，并通过滚动窗口 15% 配额，kernel 会直接投递该真实语料而不调用 Provider。该判断不对语料内容作额外价值判断。Repeater 日常接话自身不创建 LLM 任务。

工具循环会在模型提出 tool call 后执行工具、将结果追加回上下文并继续补全。默认工具集会按场景选择；延迟公开的工具可由 `tools.find` 发现，并在后续轮次加入可调用集合。延迟完成的外部工具只派发任务；任务结果由其自身通道回传，不阻塞当前 LLM 回复。

## LLM 输出管线

![LLM 输出管线与表达数据粒度](/assets/llm-output-path.svg)

`@` 对话在 Bot 进程内完成：Provider 返回文本后，从生成到发进群依次经过：

| 步骤 | 位置 | 说明 |
| --- | --- | --- |
| 表达语料直投 | `kernel_runner.py` | 表达库 `direct_candidate` 通过去重与配额时直接投递真实语料，跳过 Provider |
| 生成 + 工具循环 | `complete_with_tool_loop` | 模型提 tool call → 执行工具 → 结果回填上下文继续补全 |
| 人设输出防火墙 | `pallas/product/llm/persona_output_firewall.py` | 命中规则可带修正指令重试，或回落 fallback |
| JSON 契约解析 | `structured_reply.py` `parse_structured_reply` | 期望 `reply_segments` 数组逐条成气泡；纯文本退化单段 |
| 输出过滤 | `output_filter.py` | 语料污染词、续写残片、角色 / 形态守卫 |
| 短气泡兜底拆分 | `reply_postprocess.py` `split_short_reply_segments` | short 取向但只有单段时，按句末标点 / 换行拆成多气泡 |
| 轻量后处理 | `apply_reply_postprocess` | 错别字、句尾句号 |
| 多气泡投递 | `delivery.py` `deliver_llm_callback_success` | 逐条发送，气泡间按上句长度叠加随机抖动（0.5~3.5s，模拟真人节奏） |
| 学习回写 | 会话 / `behavior_store` / `expression_learn` / `repeater_feedback` / `auto_episode` | 投递成功后写历史、行为与表达 |

## 表达数据粒度

| 数据 | 存储 | 粒度 | 影响 |
| --- | --- | --- | --- |
| 表达风格锚点 / 例句 | `repeater_semantic_style.py`（`profiles.json`） | **每 bot × 每群** 独立（key `bot_id:group_id:scene`） | 注入「群表达指导」block；重置命令只清本 bot 本群 |
| 回复画像（气泡数 / 节奏 / 长度） | group config `style_profile`（`group_profiler.py`） | **群维度共享** | 决定 `reply_shape` 的段数、节奏与长度取向 |

同群不同 bot 的表达指导互不共享；回复画像是群统计，同群所有 bot 共用。WebUI 管理入口见 `packages/pb_webui/llm_product_api.py`。

## 关键锚点

| 步骤 | 位置 |
| --- | --- |
| Repeater 候选与投递 | `packages/repeater/responder.py`、`packages/repeater/handlers/message.py` |
| LLM 群级表达指导 | `pallas/product/llm/repeater_semantic_style.py` |
| 表达库存取 / 学习 | `pallas/product/persona/expression_*.py` |
| 进程内投递 | `pallas/product/llm/delivery.py`（`deliver_llm_chat_result`）；`kernel_runner.py` 调用 delivery |
| 媒体 / HTTP callback 壳 | `pallas/core/platform/ai_callback/runner.py`（薄壳，复用 delivery） |
| 配置键 | `pallas/product/llm/config.py`；WebUI 段见 `env_sections.py`（侧栏 **AI 配置**） |

## 约束

- 怒气门控发生在 direct runtime 与 matcher 之前。静默不是丢弃入站消息：消息仍持久化并带 `suppressed_by_rage=true`，但不会被视为 Bot 已回复，也不会进入 LLM、工具或 Repeater 处理。
- 攻击增量由攻击词数量、短窗口连续攻击次数和当前怒气共同决定；75 分进入静默，低于 75 才恢复。静默期间不重复累积怒气、不重复扣好感、不延长截止时间。

- 日常接话只使用 Repeater 语料，不调用 LLM 生成、选句、润色或拼接。
- `@`、follow-up 与工具回合独立走 `llm_chat`。
- Repeater 学到的群级表达可以只读注入 `llm_chat`；其中有界 `direct_candidate` 仅替代本次 `llm_chat` Provider 补全，不反向控制 Repeater 候选与投递。
- 在线链路不再存在 Repeater 的 select、polish 或 fallback LLM 任务。
- 表达库当前是**单群**；跨群另开任务，不要默认同库检索。

## 后续阅读

- [LLM 输出护栏与离线评测](llm-output-guardrails.md)
- [Bot 内置 Agent 生命周期](agent-lifecycle.md)
- [架构总览](overview.md)
- [LLM 与 AI 运维](/maintainer/operate/llm-and-ai)
