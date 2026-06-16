# 群风格画像（group style persona · 自动学习）

从本群最近语料的**本机已学习**记录里，自动推导 `repeater` 的群级接话画像，并与 [persona-reply-style](persona-reply-style.md) 的 bot 基础人格合并。统计层不接 LLM；导出契约供 [LLM 路线图](persona-llm-roadmap.md) 使用。

## 当前范围

- 数据来源只用**本机**已学习语料：`message` 与 `Context.answers`（**不含**共享语料 Composite，见 [LLM 路线图 · 与共享语料的关系](persona-llm-roadmap.md#与共享语料的关系)）。
- 画像按 `group_id` 落到 `group_config.style_profile`。
- 影响 `repeater` 的接话/主动发言倾向、长度偏好、`chaos_bias` 选句权重。
- 开关是 `bot_config.group_style_enabled`，按 bot 独立启用；默认开启。

### 采样口径（实现）

| 字段 | 窗口 |
| --- | --- |
| `Context.answers` | 最近 7 天（`list_answers_for_group_since`） |
| `message` | 最近 **32 条**群内消息（`find_recent_in_group(limit=32)`），再按 7 天 cutoff 过滤 |

message 采用轻量采样以降低刷新成本；answer 用完整 7 天窗口。若需与文档「全量 7 天 message」对齐，可单独 PR 扩展。

## 数据结构

`style_profile` 当前包含以下字段：

```json
{
  "version": 1,
  "updated_at": 1710000000,
  "sample": {
    "window_hours": 168,
    "message_count": 420,
    "answer_count": 85,
    "distinct_answer_keywords": 40
  },
  "raw": {
    "avg_plain_len": 18.5,
    "p50_plain_len": 12,
    "p90_plain_len": 42,
    "msgs_per_hour_active": 6.2,
    "local_answer_ratio": 0.2,
    "repeat_chain_rate": 0.08
  },
  "derived": {
    "reply_bias_mul": 1.12,
    "speak_bias_mul": 1.03,
    "length_pref": "short",
    "chaos_bias": 0.18
  }
}
```

当 `message_count < 30` 或 `answer_count < 5` 时，只保留 `sample` 与 `raw`，不产出 `derived`。

## 刷新流程

1. `repeater` 学习成功后，`Learner.learn()` 将当前群标记为 dirty。
2. `src/features/persona/group_style_refresh.py` 维护脏群集合（进程内；分片下各 worker 独立标记）。
3. `repeater` 启动时绑定后台刷新任务，每 20 分钟批量处理一次脏群（每批最多 32 群）。
4. 刷新成功后写回 `group_config.style_profile`，并清空 persona 缓存。

按需刷新，不在每条消息上实时重算。分片下可能多 worker 重复刷新同一群，写库幂等。

## 生效方式

`resolve_persona(bot_id, group_id)` 会先生成 bot 基础人格，再在满足以下条件时叠加群画像：

- 传入了 `group_id`
- 当前 bot 的 `group_style_enabled=true`
- 对应群有足够样本的 `style_profile.derived`

当前合并规则：

- `reply_bias_mul` 乘到 `reply_bias`
- `speak_bias_mul` 乘到 `speak_bias`
- `length_pref` 直接覆盖基础偏好
- `chaos_bias` 直接覆盖基础值，并参与 `scorer` 选句（见 [persona-reply-style](persona-reply-style.md)）

## LLM 契约导出

`src/features/persona/compile_group_style.py`：

| API | 用途 |
| --- | --- |
| `compile_group_style_snapshot(profile)` | 稳定 JSON（`ready` / `signals` / `hints`） |
| `compile_group_style_prompt(profile)` | 可嵌入 LLM system 的中文摘要 |

待 `compile_persona_prompt` 总装 bot 格 + 群格，见 [persona-llm-roadmap](persona-llm-roadmap.md)。

## 接入点

- `src/plugins/repeater/responder.py`：接话阈值与选句权重。
- `src/plugins/repeater/speaker.py`：主动发言阈值。
- `src/plugins/repeater/learner.py`：学习成功后标脏。

## 后续方向

- WebUI 展示群画像只读详情（可复用 `compile_group_style_snapshot`）
- ~~更细的候选排序偏好~~（`chaos_bias` 已接入 scorer）
- ~~LLM 结构化输入~~（`compile_group_style_*` 已交付；总装见 LLM 路线图）
