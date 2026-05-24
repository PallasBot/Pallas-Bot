# repeater（牛牛复读）

学习群聊、智能回复与跟复读；定时主动发言；管理员可禁用指定内容；可选表情回应。

## 用户命令

| 口令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| 群内正常聊天 | 自动 | 学习后按相似度回复、连发跟复读 |
| @牛牛 回复「不可以」 | 群内 | 禁止被回复的那条内容 |
| 不可以发这个 | 群内 | 禁止自己最近一条被引用内容 |
| 撤回牛牛消息 | 自动 | 可将内容加入禁用 |

## 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `repeater.ban` | staff |
| `repeater.ban_latest` | staff |

## 配置

见 [`config.py`](../../../src/plugins/repeater/config.py)（`answer_threshold`、`repeat_threshold`、`speak_threshold`、`enable_reaction` 等）。多牛同群接话 fanout：`fanout_enabled` / `fanout_max_bots`；推荐 WebUI **插件 → repeater** 修改。协调牛只查一次 context，其余牛从 `message_pool` 轻量随机。入库前清洗见 [message_scrub](../../common/message_scrub/README.md)。

## 排障

| 现象 | 处理 |
| --- | --- |
| 从不说话 / 话太多 | 调阈值；确认未被「不可以」或封禁限制 |
| 多牛同群负载高 | `PALLAS_REPEATER_FANOUT_ENABLED=false` 或设 `PALLAS_REPEATER_FANOUT_MAX_BOTS` |
| 不复读 | 检查 `repeat_threshold` 与连续相同句次数 |

## 实现

[`src/plugins/repeater/`](../../../src/plugins/repeater/)
