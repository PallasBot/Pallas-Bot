# LLM 输出路径

用户向说明见 [`docs/guide/llm-and-repeater.md`](../../guide/llm-and-repeater.md)。本文只标代码入口，方便改接线。

## 两条出口

```text
群消息
 ├─ @ / to_me → packages/llm_chat/chat_message.py
 │     persona +【表达参考】→ LLM 生成 → AI callback
 │
 └─ 非 @ 接话 → packages/repeater/handlers/message.py
       resolve_scene_tier → opportunity → decide_llm_attempt
       → maybe_submit_repeater_corpus_llm（强：select → polish → polish_lite）
       → 失败 / 未抽中 → 原语料发出
       → 成功 → AI callback（feedback + 表达学习）
```

## 关键锚点

| 步骤 | 位置 |
| --- | --- |
| 强弱场景 / 抽签 | `packages/repeater/opportunity_gate.py`（`resolve_scene_tier`、`decide_llm_attempt`） |
| 接话提交管线 | `pallas/product/llm/polish_lite.py`（`maybe_submit_repeater_corpus_llm`） |
| 接话人格 + 表达注入 | `pallas/product/llm/repeater_persona_context.py` |
| `@` 表达注入 | `packages/llm_chat/chat_message.py`（`build_llm_chat_expression_suffix`） |
| 表达库存取 / 学习 | `pallas/product/persona/expression_*.py` |
| 成功回调写回 | `pallas/core/platform/ai_callback/runner.py`（feedback + `note_expression_from_utterance`） |
| 配置键 | `pallas/product/llm/config.py`；WebUI 段见 `env_sections.py` |

## 约束

- 日常接话主出口仍是**语料**
- `eligible_for_writeback` / 语料 auto_promote 偏向 **strong**；fallback 不是主写回源。
- 表达库当前是**单群**；跨群另开任务，不要默认同库检索。
