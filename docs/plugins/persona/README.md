<p align="center">
  <img src="../assets/brand-avatar.png" width="220" height="220" alt="接话行为">
</p>

<h1 align="center">接话行为 persona</h1>

<p align="center">说明接话学习出来的牛格、群风格和行为差异是怎么生效的。</p>

<p align="center">
  <img alt="本体 core" src="https://img.shields.io/badge/%E6%9C%AC%E4%BD%93%20core-4B5563">
  <img alt="默认提供" src="https://img.shields.io/badge/%E9%BB%98%E8%AE%A4%E6%8F%90%E4%BE%9B-4EA94B">
  <img alt="版本 4.0.0" src="https://img.shields.io/badge/%E7%89%88%E6%9C%AC-4.0.0-2563EB">
</p>

## 安装方式

随主仓提供，无独立安装步骤。

## 怎么使用

这里没有单独口令。接话时的语气、长度、活跃度和群内风格会按学习结果自动生效。

> 详细用法、限制条件和可用范围以帮助为主。

## 命令权限

无。

## 配置项

> 可在控制台对应插件页中修改。

`persona` 本身没有独立插件页，主要受接话学习结果、群画像和相关通用配置影响。

## 排障

| 现象 | 处理 |
| --- | --- |
| 感觉每只牛说话区别不明显 | 需要先有足够学习数据，牛级差异和群风格才会逐步显现。 |
| 某群接话风格不贴近本群 | 检查本群学习数据是否足够，以及接话相关能力是否被关闭。 |
| 想了解为什么会这样回复 | 先看 `repeater` 帮助和相关架构文档，`persona` 负责解释行为来源，不单独处理消息。 |

## 实现

源码位置：

- 行为逻辑：[`pallas/product/persona/`](../../pallas/product/persona/)
- 接入入口：[`packages/repeater/`](../../packages/repeater/)

关键文件：

- [`pallas/product/persona/auto.py`](../../pallas/product/persona/auto.py)：按 `bot_id` 派生基础牛格差异。
- [`pallas/product/persona/loader.py`](../../pallas/product/persona/loader.py)：合并牛级特征与群风格画像。
- [`pallas/product/persona/compile_group_style.py`](../../pallas/product/persona/compile_group_style.py)：把群内学习结果整理成可用画像。
- [`packages/repeater/__init__.py`](../../packages/repeater/__init__.py)：把这些画像接到实际接话逻辑里。

实现要点：

- 牛级差异来自 `bot_id` 的确定性派生，不需要手工给每只牛单独配置。
- 群级风格来自本群学习到的 `message` 和 `answer` 数据，不是写死模板。
- 群聊表达习惯不只看长短和活跃度；高频触发词、群梗和接梗倾向也会参与塑形。
- `persona` 影响的是接话行为和风格，不是一个独立可调用插件。
- `persona` 不只影响平时接话；当你 `@牛牛` 闲聊时，统一 LLM 路径也会继续吃到牛格与群味。

## 相关链接

- [复读插件](../repeater/README.md)
- [`@牛牛`、复读接话与 LLM 的关系](../../guide/llm-and-repeater.md)
- [架构总览](../../developer/architecture/overview.md)
- [LLM 与 AI 运维](../../maintainer/operate/llm-and-ai.md)
