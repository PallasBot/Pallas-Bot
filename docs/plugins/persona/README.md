# 接话行为 `persona`

说明接话学习出来的牛格、群风格与行为差异如何生效。不是独立可「安装开关」的玩法插件：平时接话由 [复读](../repeater/README.md) 消费这些画像；`@牛牛` LLM 对话路径也会带上牛格与群味。

**类型**：随主仓提供（无独立安装步骤）

## 安装

随主仓提供，无独立安装步骤。

## 用法

无单独口令。接话时的语气、长度、活跃度与群内风格会按学习结果自动生效。

若要调接话频率等，改 [repeater](../repeater/README.md) 插件配置；LLM 对话总闸见 [llm_chat](../llm_chat/README.md) / [AI 扩展](../../guide/ai.md)。

## 命令权限（代码默认）

无。

## 配置

无独立插件页。主要受接话学习结果、群画像与相关通用配置影响。

## 排障

| 现象 | 处理 |
| --- | --- |
| 每只牛说话区别不明显 | 需足够学习数据后，牛级差异与群风格才会显现 |
| 某群风格不贴近本群 | 检查本群学习数据与接话能力是否被关闭 |
| 想了解为何这样回 | 先看 repeater 帮助与相关架构文档；persona 解释来源，不单独处理消息 |

## 源码

- 行为逻辑：[`pallas/product/persona/`](../../../pallas/product/persona/)
- 接入：[`packages/repeater/`](../../../packages/repeater/)

要点：牛级差异由 `bot_id` 确定性派生；群级风格来自本群学习到的 message / answer，不是写死模板。

## 相关链接

- [复读 repeater](../repeater/README.md)
- [`@牛牛` 与复读](../../guide/llm-and-repeater.md)
- [LLM 输出路径](../../developer/architecture/llm-output-path.md)
- [LLM 与 AI 运维](../../maintainer/operate/llm-and-ai.md)
