# repeater（牛牛复读）

群内 **学习对话**、按相似度与重复度 **自动回复** 与 **复读**；定时 **主动发言**；管理员可 **禁止** 指定内容；可选 **表情回应**（消息表情 / 概率回应 / 跟随他人回应）。

## 行为概要

- 学习群消息并持久化（阈值与保存策略见配置）。
- 相同消息连续出现达到阈值时复读。
- 管理员：`回复某条消息` 后发 `不可以` 禁止该内容；`不可以发这个` 禁止自己最近一条被引用的内容；撤回牛牛消息可加入禁用列表。
- 表情回应：受 `enable_reaction` 等开关控制。

## 配置

调参见 [`src/plugins/repeater/config.py`](../../../src/plugins/repeater/config.py)（如 `answer_threshold`、`repeat_threshold`、`speak_threshold`、持久化间隔与条数、`enable_reaction` 等）。

## 依赖与关联

- **take_name** 依赖本插件的 `MessageStore` 从各群取随机消息；未加载复读时不应依赖夺舍相关能力。

## 排障

| 现象 | 说明 |
|------|------|
| 从不说话或话太多 | 调整 `answer_threshold`、`speak_threshold` 等；确认未被 `不可以` 或封禁逻辑限制。 |
| 复读不触发 | 检查 `repeat_threshold`、是否同一文本连续次数足够。 |

实现见 [`src/plugins/repeater/__init__.py`](../../../src/plugins/repeater/__init__.py)。
