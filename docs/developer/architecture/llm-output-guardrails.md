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
  落群成功后：会话回写 / auto_episode / repeater_feedback / reply_effect 评分
```

> 两层护栏里只有 ① 有重生成回路。输出过滤（⑥）命中后**只降级不重试**——换兜底文案，实在没有就静默。

## 护栏分层

两层护栏性质不同，先分清再查模块：

- **安全意识护栏（拦）**：内容本身有问题——泄提示词、自曝身份、人格崩坏、语料污染。命中后走退化逻辑（见[下一节](#决策与退化语义)）。
- **表现护栏（调形态）**：内容没问题，只是形态不合适——结构、长度、气泡拆分、@ 位置。只修形态，不拦安全。

### 安全意识护栏

由三个模块组成，各自独立判定：

**人设输出防火墙 · `persona_output_firewall.py`**

- 拦：提示词泄露、舞台指示、模型身份自曝、人格漂移、模板腔收尾——约 20 条正则加上下文锚点，共 9 类规则。
- 命中：带修正指令重生成一次（`max_retries=1`），仍命中回落 fallback → silent。
- 配置：`llm_persona_output_firewall`（dict，默认 `enabled: false`）。

**输出过滤 · `output_filter.py`**

- 拦：语料污染片段、CQ 码、续写残片、垫词整句、客服设定腔（硬拦）；尬聊垫话（软拦）。
- 命中：只降级不重试——换兜底文案，实在没有就静默。
- 配置：`llm_output_filter_enabled`（默认 `true`）+ `llm_output_filter_chat_hard_phrases` / `llm_output_filter_chat_soft_phrases` 词表；只作用于 chat profile（`LEGACY_LLM_CHAT_TASK_TYPES + CHAT_DRUNK`）。

**字符契约 · `structured_reply.py` 的 `validate_reply_chars`**

- 拦：坏 token、单条超 500 字、无正文。
- 内建校验，无独立开关。

### 表现护栏

由 `reply_postprocess.py`、`structured_reply.py` 的拆分逻辑与 `delivery.py` 的去重 / 节奏控制组成：

- JSON 契约校验：坏结构整条不回（fail-closed）
- 超长找干净断点压短，短回复按句末标点拆多气泡
- 去掉开头多余的 @；空回复兜底
- 错别字 / 句尾句号修正：`llm_reply_postprocess_enabled`（默认 `false`）
- 与近期回复去重、气泡间随机抖动

两个边界：

- 每条气泡没有独立权限；`@某人` / 引用装饰只作用于第一条气泡。
- `apply_reply_postprocess` 不影响反馈回写：`learned_reply_text` 用的是 postprocess 前的文本。

## 决策与退化语义

护栏最终把回复收敛到四态：

| 状态 | 何时 | 落到哪 |
| --- | --- | --- |
| `allow` | 全部通过 | 走 ⑤→⑪ 正常逐气泡投递 |
| `retry` | 防火墙命中且策略 `retry_then_fallback` | 带修正指令重生成一次，仍命中则下行 |
| `fallback` | 防火墙 / 过滤给出兜底文案 | 优先任务 `fallback_text`，无则内建；兜底文案也要过自检，不过则升 `silent` |
| `silent` | 兜底仍不过 / 无正文 / 未授权提及 token | 不投递，`suppress_empty_fallback=True` 防止被空回复兜底填回 |

三条补充：

- 防火墙 `severity=soft` 且仅命中 `roleplay_stage_direction` 时会放行。
- 空回复兜底在 `chat_empty_fallback.py`；`suppress_empty_fallback` 时跳过。
- 防火墙命中后 agent trace 会脱敏再落盘（`redact_agent_trace_for_firewall`）。

## 可观测契约

护栏命中已接进任务指标，与使用量共用同一条日汇总管道：

| 项 | 现状 |
| --- | --- |
| 拦截计数 | `task_metrics` 事件 `persona_firewall_hit` / `persona_firewall_retry` / `output_filter_block` / `reply_silenced`，埋点在 `kernel_runner.py` 防火墙判定与 `delivery.py` 过滤出口；随日汇总落 `llm_task_stats.json`，控制台 `GET /common-config/llm/task-stats` 可查 |
| 拦截日志 | 防火墙：`log_rate_limited("llm.persona_output_firewall")` + trace 字段 `persona_output_firewall`；输出过滤：`llm.output_filter.*`（orphan_particle / stage_direction / truncated / char_guard） |
| 使用量聚合 | `task_metrics.py` `record_bot_llm_task/route`（内存自增 → 日回落盘）、`token_metrics` / `provider_request_metrics` / `rag_metrics`（`llm_daily_stats.json`）→ `model_admin.fetch_llm_task_stats` → 控制台 |
| 逐任务 trace | `runtime_debug` 单条可看，无聚合 |

## 离线质量评测

用固定用例离线跑模型、量化回复质量，改提示词或换模型前后对比用。**匿名、不投递、不写记忆**。

::: warning 入口须知
独立脚本 `tools/run_llm_quality_eval.py`：不属于 `pallas` 命令族，也没有 WebUI / API 入口；结果 JSON 直接打到 stdout。
:::

### 跑法

```bash
uv run python tools/run_llm_quality_eval.py [--matrix default|anonymous] [--judge] [--write-baseline] [--system-prompt <file>]
```

| 参数 | 作用 |
| --- | --- |
| `--matrix anonymous` | 跑 78 例匿名矩阵（缺省 `default` 是 6 例速测） |
| `--judge` | 对每条回复追加一次 LLM 评审 |
| `--write-baseline` | 把本次结果追加进本地基线 JSONL，供后续对比 |
| `--system-prompt <file>` | 换用别的静态 system prompt 文件 |

### 用例

| 矩阵 | 规模 | 覆盖 |
| --- | --- | --- |
| `default` | 6 例 | 在线确认、短事实、情绪、接梗、叫早、直接回答 |
| `anonymous` | 3 persona × 26 场景 = 78 例 | 工具调用 / 记忆 / 隐私 / 边界 / 沉默判断等 |

### 评分

- **LLM 评审维度**（`--judge` 时输出，1–5 分）：grounded / naturalness / overexplained / persona_drift / memory_factuality / tool_faithfulness / silence_correctness
- **启发式回复效果分**（每次运行都给，不依赖 LLM）：`heuristic_reply_effect_scores` 给出 social / warmth / competence / appropriateness / uncanny_risk

::: info 运行约束
- 走 `complete_chat_message` 的默认 provider：temperature=0、预算 96 token（`task_token_budget("offline_quality_eval")`）、不挂工具。
- system prompt 静态读 `pallas/product/persona/at_chat_system_prompt.txt`，不读牛格与运行时数据。
- 未按 provider / model 分档，暂不支持 A/B 对比。
:::

### 基线与对比

基线由 `offline_quality_history.py` 落在 `pb_webui` plugin_data_dir 下的 `pallas_llm/quality_baselines.jsonl`：

| 函数 | 用途 |
| --- | --- |
| `record_quality_baseline` | 追加一次运行 |
| `summarize_quality_baseline` | 按 persona / scene / rule_id 聚合 |
| `compare_quality_baselines` | 标出分数回退与新增 rule_id |

## 后续阅读

- [LLM 输出路径](llm-output-path.md) · [Agent 生命周期](agent-lifecycle.md)
- [LLM 与 AI 运维](/maintainer/operate/llm-and-ai)
- [平台横切能力全景](cross-cutting-concerns.md) · [多牛协同面](multi-bot-collaboration.md)
