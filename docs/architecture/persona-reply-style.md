# 接话行为（persona · 自动生长）

> 3.9+ 交付行为层与群风格；**4.0** 统一 LLM 语言层见 [persona-llm-roadmap](persona-llm-roadmap.md) 与 [pallas-4.0-roadmap](pallas-4.0-roadmap.md)。

## 目标与边界

| 做 | 不做 |
| --- | --- |
| per `bot_id` 自动派生（多牛略有差异） | 号主私聊 `牛牛接话`、手动预设 |
| per `group_id` 从本群语料统计推导（见 [group-style-persona](group-style-persona.md)） | 口癖种子、号主手写台词 |
| 复读选句加权、fanout 分化、`chaos_bias` 候选排序 | LLM 润色/兜底/生成（见 [LLM 路线图](persona-llm-roadmap.md)，默认关） |
| 独占活动局内少插话 | WebUI 手动调参表单（首版） |
| 群风格 LLM 契约导出 | 号主手写 preset 覆盖 |

**语言人设**（帕拉斯腔、固定口癖）留待 LLM 接入后与 `compile_persona_prompt` 统一；路线图见 [persona-llm-roadmap](persona-llm-roadmap.md)。

## 参数来源（优先级）

```
effective = derive_persona_from_bot_id(bot_id)
          × bot_config.persona.derived      # 跨群加权汇总，见下文
          × group style_profile.derived   # 群学习画像，见 group-style-persona.md
```

- `bot_config.persona`（`source=cross_group`）由该牛近期活跃群的 `style_profile` 加权汇总写入；样本不足时不产出 `derived`。
- 忽略历史号主手写写入的 `bot_config.persona`（`source` 非 `cross_group` 时不参与计算）。
- 无群画像或样本不足时，群倍率为中性 `1.0`。

## 跨群汇总（bot 级）

`src/features/persona/cross_group_profiler.py` / `cross_group_refresh.py`：

- 仅统计该 `bot_id` 在 7 天窗口内发过消息的群，且群已有 `style_profile.derived`。
- 单群权重：`sqrt(answer_count) × sqrt(message_count)`，上限 50；按 `updated_at` 7 天半衰期衰减。
- 至少 2 群且总权重 ≥ 15 才写出 `derived`；群风格刷新成功后标记相关 bot 为 dirty，与群刷新共用 20 分钟后台批次。

## 牛级自动派生

`src/features/persona/auto.py`：按 `bot_id` 对 `tone`、`reply_bias`、`speak_bias`、`length_pref` 做确定性派生，无需配置。

## 内核 `src/features/persona/`

| 模块 | 职责 |
| --- | --- |
| `model.py` | `ResolvedPersona`（含 `chaos_bias`、`cross_group_bias_mul` 预留） |
| `auto.py` | `derive_persona_from_bot_id` |
| `loader.py` | `resolve_persona(bot_id, group_id?)` + 缓存 |
| `scorer.py` | 阈值缩放、选句权重、`chaos` / `freshness` / `low_info` |
| `group_profiler.py` | 群统计与 `style_profile` 推导 |
| `cross_group_profiler.py` | 跨群 `style_profile` 加权汇总为 `bot_config.persona` |
| `cross_group_refresh.py` | bot dirty 标记 + 定时刷新 |
| `group_style_refresh.py` | dirty 标记 + 定时刷新 |
| `compile_group_style.py` | `compile_group_style_snapshot` / `compile_group_style_prompt`（LLM 契约） |

## 复读接入

- `responder._context_find_with_pool`：`scaled_answer_threshold`、`message_weight_multiplier`、`answer_popularity_multiplier`、`freshness_multiplier(..., persona=...)`
- `responder.pick_fanout_plan(bundle, bot_id)`：按 `bot_id ^ hash(keywords)` 分化
- `speaker.speak`：`scaled_speak_threshold`；`_pick_speak_message` 按牛格加权选热门 topic / 句长；`activity_gate.blocks_proactive_speak`
- `activity_gate`：决斗/卧底期间接话阈值 ×`activity_reply_bias`；**跟复读不受影响**

## 测试

- `tests/features/test_persona.py` — 派生、scorer、群合并
- `tests/features/test_persona_fanout.py` — fanout 分化
- `tests/features/test_group_profiler.py` — 群统计
- `tests/features/test_group_style_refresh.py` — 刷新流程
- `tests/features/test_compile_group_style.py` — LLM 契约导出

## 后续

1. ~~群风格自动学习~~ → [group-style-persona](group-style-persona.md)（已交付）
2. ~~更细候选排序（`chaos_bias`）~~、~~群风格 LLM 契约~~（已交付）
3. **LLM 接入**：[persona-llm-roadmap](persona-llm-roadmap.md)（4.0：`compile_persona_prompt`、fallback/polish、运行时）
4. WebUI 群画像只读展示
5. **AI 通道**：MCP + 插件 metadata 工具调用（4.0+，见 [arknights-knowledge-mcp](arknights-knowledge-mcp.md)）

## 相关路径

- 群学习：[group-style-persona.md](group-style-persona.md)
- LLM 路线图：[persona-llm-roadmap.md](persona-llm-roadmap.md)
- 4.0 总览：[pallas-4.0-roadmap.md](pallas-4.0-roadmap.md)
- 复读：`src/plugins/repeater/`
