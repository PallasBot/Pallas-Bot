# LLM 输出护栏与离线评测

本页补全 [LLM 输出路径](llm-output-path.md) 的「输出护栏」细节：从模型生成到进群的每一道过滤、命中后的退化语义，以及离线质量评测的用法。面向改动护栏链路、接线新过滤器、或要跑评测的开发者。

一句话模型：**护栏分两层——安全意识护栏（拦）与表现护栏（不拦安全、只调形态）**；命中后按 `allow / retry / fallback / silent` 四态收敛，最终由 `deliver_llm_callback_success` 逐气泡投递，写路径全部有回归点可观测。

## 判定顺序（从生成到进群）

```text
Provider 输出 / direct_candidate 直投
  └─ ① persona_output_firewall（kernel_runner.run_kernel_chat_job）
  │      硬规则命中 → retry（修正指令重生成，max_retries=1）→ 仍命中 → fallback → silent
  │      配置：llm_persona_output_firewall（默认 off）
  └─ ② decision.action == "silent" → suppress_empty_fallback=True（防空兜底填回）
  ▼ delivery.deliver_llm_callback_success（投递出口）
  │  ③ should_suppress_llm_duplicate_reply（与近期回复去重）
  │  ④ extract_sticker_marker（贴纸指令）
  │  ⑤ parse_structured_reply（JSON 契约 → 气泡数组，fail-closed）
  │  ⑥ resolve_output_filtered_chat_reply（段级清洗 + 硬/软拦词表 + fallback/静默）
  │      配置：llm_output_filter_enabled（默认 on）
  │  ⑦ split_short_reply_segments（short 取向单段 → 按句末标点拆 3 段）
  │  ⑧ strip_leading_self_at_mentions（开头 @ 自己 → 去）
  │  ⑨ chat_empty_fallback（空回复兜底；suppress_empty_fallback 时跳过）
  │  ⑩ apply_reply_postprocess（错别字/句尾句号，llm_reply_postprocess_enabled 默认 off）
  │  ⑪ replace_mention_tokens（未授权提及 token → 静默）
  ▼ 多气泡逐条投递（气泡间 0.5~3.5s 随机抖动）
  落群成功后：会话回写 / auto_episode / expression_learn / repeater_feedback / reply_effect 评分
```

> 和人设防火墙不同，输出过滤命中后**只降级不重试**（fallback 文案 → 静默）；只有 ① 有重生成回路。

## 护栏分层语义

| 层 | 模块 | 拦什么 | 配置 |
| --- | --- | --- | --- |
| 安全意识护栏 | `persona_output_firewall.py` | 提示词泄露、舞台指示、模型身份自曝、人格漂移（约 30 条正则 + 上下文锚点） | `llm_persona_output_firewall`（dict，默认 `enabled: false`） |
| | `output_filter.py` | 语料污染片段/CQ 码、垫词整句、客服设定腔（硬拦）、尬聊垫话（软拦） | `llm_output_filter_enabled`（默认 `true`）+ `*_chat_hard_phrases` / `*_chat_soft_phrases` 词表 |
| | `structured_reply.py` `validate_reply_chars` | 坏 token、超长（500 字）、无正文 | 内建 |
| 表现护栏 | `reply_postprocess.py`、`structured_reply.py` 拆分、`delivery.py` 去重/节奏 | 气泡形态、写错别字、句尾句号、@ 位置 —— 不拦安全 | `llm_reply_postprocess_enabled`（默认 `false`） |

- 输出过滤只作用于 chat profile（`LEGACY_LLM_CHAT_TASK_TYPES + CHAT_DRUNK`）。
- 每条气泡无独立权限；`@某人`/引用装饰只作用于第一条。
- `apply_reply_postprocess` 不影响反馈回写：`learned_reply_text` 用 postprocess 前文本。

## 决策与退化语义

护栏最终把回复收敛到四态：

| 状态 | 何时 | 落到哪 |
| --- | --- | --- |
| `allow` | 全部通过 | 走 ⑤→⑫ 正常投递 |
| `retry` | 防火墙 hit 且策略 `retry_then_fallback` | 带修正指令重生成一次，仍命中则下行 |
| `fallback` | 防火墙/过滤兜底文案 | 优先任务 `fallback_text`，无则内建；fallback 也须过自检，否则升 `silent` |
| `silent` | 兜底仍不过 / 无正文 / 未授权 token | 不投递，`suppress_empty_fallback=True` 防止被空回复兜底填回 |

- 防火墙 `severity=soft` 且仅命中 `roleplay_stage_direction` 时会放行。
- 空回复兜底：`chat_empty_fallback.py`；被 `suppress_empty_fallback` 跳过。
- 人设防火墙命中后 agent trace 会脱敏再落盘（`redact_agent_trace_for_firewall`）。

## 可观测契约

| 项 | 现状 |
| --- | --- |
| 拦截日志 | firewall：`log_rate_limited("llm.persona_output_firewall")` + trace 字段 `persona_output_firewall`；output_filter：`llm.output_filter.*`（orphan_particle / stage_direction / truncated / char_guard） |
| 拦截计数 | **无**计数器、无聚合、无面板；`task_metrics._EVENTS` 无 firewall / output_filter / silenced 事件 |
| 使用量聚合 | `task_metrics.py` `record_bot_llm_task/route`（内存自增 → 日回落盘 `llm_task_stats.json`）、`token_metrics` / `provider_request_metrics` / `rag_metrics`（`llm_daily_stats.json`）→ `model_admin.fetch_llm_task_stats` → 控制台 `GET /common-config/llm/task-stats` |
| 逐任务 trace | `runtime_debug` 单条可看，无聚合 |

平台化第一步即补齐计数器（见下），复用既有日汇总管道即可免费获得面板数据。

## 离线质量评测

- 入口：`tools/run_llm_quality_eval.py`（`uv run python tools/run_llm_quality_eval.py [--system-prompt ...] [--judge] [--matrix default|anonymous] [--write-baseline]`，输出 JSON 到 stdout）。**非 `pallas` 命令族，无 WebUI/API 入口**。
- 用例：`DEFAULT_OFFLINE_QUALITY_CASES`（6 例）+ `ANONYMOUS_QUALITY_MATRIX`（3 persona × 22 场景 = 66 例，覆盖 tool / memory / 隐私 / 边界）。
- 评分：`_QUALITY_SCORE_KEYS`（grounded / naturalness / overexplained / persona_drift / memory_factuality / tool_faithfulness / silence_correctness，1-5）+ 启发式 `heuristic_reply_effect_scores`（reply_effect：social / warmth / competence / appropriateness / uncanny_risk）。可选 `--judge` 用 LLM 当裁判。
- 运行时：`run_configured_offline_quality_eval` 走 `complete_chat_message`，temperature=0、预算 96 token；**匿名、不投递、不写记忆**；system prompt 静态读 `pallas/product/persona/at_chat_system_prompt.txt`。
- 基线：`offline_quality_history.py` 落 `pb_webui/plugin_data_dir()/pallas_llm/quality_baselines.jsonl`；`record_quality_baseline` / `summarize_quality_baseline`（按 persona/scene/rule_id 聚合）/ `compare_quality_baselines`（分数回退 + 新增 rule_id）。
- 评测入口透传默认 provider；未按 provider/model 分档。

## 平台化待办

与全架构调研（2026-08-20）的 P1 里程碑「LLM 输出护栏与离线评测平台化」对应：

| 待办 | 方案 |
| --- | --- |
| 护栏拦截统计 | `task_metrics._EVENTS` 增补 `output_hard_block / output_soft_retry / output_fallback / output_silenced / persona_firewall_retry / persona_firewall_fallback / persona_firewall_silent`，在 `resolve_output_filtered_chat_reply` 与 kernel decision 处埋点 → 复用日汇总 + task-stats 面板 |
| 评测 CLI | `pallas console eval` 包装 `tools/run_llm_quality_eval.py` |
| 评测 WebUI | 控制台挂 `GET/POST /pallas/api/common-config/llm/quality-eval`（放 `llm_ops_api.py` 或独立 `quality_eval_api.py`），复用 offline_quality_eval + history；面板入「AI 配置 → 输出」 |
| 评测按 provider | `run_configured_offline_quality_eval` 增加 provider 参数走 `providers_store` 解析，支持 A/B 对比 |
| 默认值闭环 | 人设防火墙默认 `off`；如需随新装即生效，需评估默认开并配套误伤率观测 |

## 后续阅读

- [LLM 输出路径](llm-output-path.md) · [Agent 生命周期](agent-lifecycle.md)
- [LLM 与 AI 运维](/maintainer/operate/llm-and-ai)
- [平台横切能力全景](cross-cutting-concerns.md) · [多牛协同面](multi-bot-collaboration.md)