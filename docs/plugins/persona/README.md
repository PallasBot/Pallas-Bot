# 接话行为（自动生长）

牛格由**学习**推导，不提供号主私聊口令或手动预设。

| 层级 | 来源 | 说明 |
| --- | --- | --- |
| 牛级 | `derive_persona_from_bot_id` | 各牛按 QQ 号略有差异，零配置 |
| 群级 | `group_config.style_profile` | 从本群 `message` / `answer` 统计自动推导，见 [group-style-persona](../../architecture/group-style-persona.md) |

架构详见 [persona-reply-style](../../architecture/persona-reply-style.md) · LLM / 4.0：[persona-llm-roadmap](../../architecture/persona-llm-roadmap.md)、[pallas-4.0-roadmap](../../architecture/pallas-4.0-roadmap.md)。

## 实现

内核 [`src/features/persona/`](../../../src/features/persona/) · 接入 [`src/plugins/repeater/`](../../../src/plugins/repeater/)
