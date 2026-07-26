# Bot 内置 Agent 生命周期

Pallas-Bot 的普通 LLM 聊天在 Bot 进程内完成。本文说明维护者修改这条路径时的职责边界和排查入口。

用户侧的配置和能力选择见 [LLM 对话、媒体与 AI Runtime](/guide/ai-runtime-choice)。

## 一次对话如何执行

```text
消息入口
  → 任务决策
  → 上下文与工具装配
  → Provider 调用和工具循环
  → 投递结果与运行追踪
```

| 环节 | 责任 | 主要位置 |
| --- | --- | --- |
| 消息入口 | 将 `@` 聊天或接话请求转换为 LLM 任务 | `packages/llm_chat/`、`packages/repeater/` |
| 任务决策 | 根据场景、开关和抽签决定是否进入生成路径 | `pallas/product/llm/kernel/` |
| 上下文装配 | 组织会话、人格、记忆和知识上下文 | `pallas/product/llm/assembler/context.py` |
| 工具装配 | 按场景选择工具，携带已激活的延迟工具 | `pallas/product/llm/assembler/tools.py`、`tools/registry.py` |
| 工具循环 | 执行 tool call，将结果回填给模型继续生成 | `pallas/product/llm/tool_loop.py` |
| 投递与追踪 | 发送结果，并记录状态、工具调用和拒绝原因 | `kernel_runner.py`、`runtime_debug.py` |

`Pallas-Bot-AI` 不参与这条普通聊天路径。它负责媒体任务和遗留 RWKV；不要为普通 `@` 聊天增加 AI Runtime callback。

## 工具与延迟发现

工具注册表保存名称、参数、能力标签和可见性。默认工具集只包含当前场景需要的能力，避免把所有工具放进每次请求。

模型需要低频能力时，可以调用 `tools.find`。匹配到的延迟工具会加入本轮后续调用，并在短时间内保留给同一会话范围。副作用工具仍经过既有安全和确认策略；被拦截的原因会写入运行追踪。

新增工具优先复用注册表与能力标签，不要绕过工具循环直接在消息入口执行。

## 记忆和检索

上下文装配会按开关读取会话、群记忆、关系便签和知识源。检索模式由 `effective_vector_retrieve_mode` 决定：

- 配置 `stub` embedding，或 embedding 调用失败时，使用关键词检索。
- 配置并成功调用真实 embedding 时，才使用向量或混合检索。

这是运行时降级策略，不应把配置中的 `hybrid` 直接当成实际检索方式。排障时查看运行追踪和 [LLM 与 AI 运维](/maintainer/operate/llm-and-ai)。

## 修改后的验证

| 改动 | 优先验证 |
| --- | --- |
| 上下文、工具装配 | `tests/product/llm/test_context_assembler.py`、`test_tool_assembler.py` |
| 工具循环或发现 | `tests/product/llm/test_tool_discovery_loop.py`、相关工具测试 |
| 检索或 embedding | `tests/features/test_embedding_client.py`、`test_vector_retrieve_backend.py` |
| 投递、会话或接话 | `tests/features/test_llm_client.py`、`test_conversation_kernel.py`、`tests/plugins/repeater/` |

完成局部验证后，执行仓库约定的 Ruff 检查。完整的入口与投递接线见 [LLM 输出路径](llm-output-path.md)。
