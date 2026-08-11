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
       → 原始候选检索、人格加权、过滤与去重
       → Repeater 直接投递原语料
```

普通聊天在 Bot 进程内执行：`submit_chat_task` 安排 `kernel_runner`。通常由后者调用 Provider、运行工具循环，并通过 `pallas/product/llm/delivery.py` 的 `deliver_llm_chat_result` 交给既有投递入口；若 semantic style 给出通过相关性与近期回复去重的 `direct_candidate`，并通过滚动窗口 15% 配额，kernel 会直接投递该真实语料而不调用 Provider。该判断不对语料内容作额外价值判断。Repeater 日常接话自身不创建 LLM 任务。

工具循环会在模型提出 tool call 后执行工具、将结果追加回上下文并继续补全。默认工具集会按场景选择；延迟公开的工具可由 `tools.find` 发现，并在后续轮次加入可调用集合。延迟完成的外部工具只派发任务；任务结果由其自身通道回传，不阻塞当前 LLM 回复。

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

- 日常接话只使用 Repeater 语料，不调用 LLM 生成、选句、润色或拼接。
- `@`、follow-up 与工具回合独立走 `llm_chat`。
- Repeater 学到的群级表达可以只读注入 `llm_chat`；其中有界 `direct_candidate` 仅替代本次 `llm_chat` Provider 补全，不反向控制 Repeater 候选与投递。
- 在线链路不再存在 Repeater 的 select、polish 或 fallback LLM 任务。
- 表达库当前是**单群**；跨群另开任务，不要默认同库检索。

## 后续阅读

- [Bot 内置 Agent 生命周期](agent-lifecycle.md)
- [架构总览](overview.md)
- [LLM 与 AI 运维](/maintainer/operate/llm-and-ai)
