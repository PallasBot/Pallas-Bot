# LLM 输出路径

本页标出普通聊天与接话的代码入口，方便改接线。用户向说明见 [LLM 对话与复读](/guide/llm-and-repeater)。

普通 `@` 聊天走 Bot Provider，在 Bot 进程内完成；不要为这条路径增加 Pallas-Bot-AI / `:9099` / HTTP callback。媒体与遗留 RWKV 另见 [Agent 生命周期](agent-lifecycle.md) 与运维文档。

## 两条出口

```text
群消息
 ├─ @ / to_me → packages/llm_chat/chat_message.py
 │     persona +【表达参考】→ client.submit_chat_task
 │
 └─ 非 @ 接话 → packages/repeater/handlers/message.py
       resolve_scene_tier → opportunity → decide_llm_attempt
       → maybe_submit_repeater_corpus_llm
       → 失败 / 未抽中 → 原语料发出
       → 成功 → kernel_runner → tool_loop.complete_with_tool_loop
                    → delivery.deliver_llm_chat_result → Bot 内投递 / feedback + 表达学习
```

普通聊天与接话均在 Bot 进程内执行：`submit_chat_task` 安排 `kernel_runner`，后者调用 Provider、运行工具循环，并通过 `pallas/product/llm/delivery.py` 的 `deliver_llm_chat_result` 交给既有投递入口。

工具循环会在模型提出 tool call 后执行工具、将结果追加回上下文并继续补全。默认工具集会按场景选择；延迟公开的工具可由 `tools.find` 发现，并在后续轮次加入可调用集合。延迟完成的外部工具只派发任务；任务结果由其自身通道回传，不阻塞当前 LLM 回复。

## 关键锚点

| 步骤 | 位置 |
| --- | --- |
| 强弱场景 / 抽签 | `packages/repeater/opportunity_gate.py`（`resolve_scene_tier`、`decide_llm_attempt`） |
| 接话提交管线 | `pallas/product/llm/polish_lite.py`（`maybe_submit_repeater_corpus_llm`） |
| 接话人格 | `pallas/product/llm/repeater_persona_context.py` |
| 表达库存取 / 学习 | `pallas/product/persona/expression_*.py` |
| 进程内投递 | `pallas/product/llm/delivery.py`（`deliver_llm_chat_result`）；`kernel_runner.py` 调用 delivery |
| 媒体 / HTTP callback 壳 | `pallas/core/platform/ai_callback/runner.py`（薄壳，复用 delivery） |
| 配置键 | `pallas/product/llm/config.py`；WebUI 段见 `env_sections.py`（侧栏 **AI 配置**） |

## 约束

- 日常接话主出口仍是**语料**
- `eligible_for_writeback` / 语料 auto_promote 偏向 **strong**；fallback 不是主写回源。
- 表达库当前是**单群**；跨群另开任务，不要默认同库检索。

## 后续阅读

- [Bot 内置 Agent 生命周期](agent-lifecycle.md)
- [架构总览](overview.md)
- [LLM 与 AI 运维](/maintainer/operate/llm-and-ai)
