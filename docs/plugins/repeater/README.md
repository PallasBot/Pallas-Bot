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

见 [`config.py`](../../../src/plugins/repeater/config.py)（`answer_threshold`、`repeat_threshold`、`speak_threshold`、`enable_reaction` 等）。多牛同群 fanout 默认关，分片/多牛需协调接话时在 WebUI **插件 → repeater** 开 `fanout_enabled` 或设 `fanout_max_bots`。入库前清洗见 [message_scrub](../../common/message_scrub/README.md)。

### 群风格自动生长

- 开关位置：WebUI **实例 / Bot 配置** 中的 `启用群风格自动生长`，默认开启。
- 作用范围：按 bot 生效，不是全局 repeater 配置。
- 数据来源：仅使用该群最近 7 天内、已经被 repeater 学会的语料。
- 当前影响：自动调整该 bot 在该群的接话频率、主动发言频率，以及粗粒度长度偏好。
- 无需手动调参：开启后由系统自动统计并写入 `group_config.style_profile`。

## 排障

| 现象 | 处理 |
| --- | --- |
| 从不说话 / 话太多 | 调阈值；确认未被「不可以」或封禁限制 |
| 多牛同群负载高 | `PALLAS_REPEATER_FANOUT_ENABLED=false` 或设 `PALLAS_REPEATER_FANOUT_MAX_BOTS` |
| 不复读 | 检查 `repeat_threshold` 与连续相同句次数 |

## 实现

[`src/plugins/repeater/`](../../../src/plugins/repeater/)
