# Core 与扩展

能力归属：core、官方插件或社区插件。不以「写起来方便」决定归属。

## 三层

| 层 | MUST 放入 | MUST NOT |
| --- | --- | --- |
| Core | 全部署形态依赖的运行时；cmd_perm / help / 热载 / 分片；产品底盘（语料、ingress、多牛协同等） | 独立玩法、可按需安装的媒体能力、强垂直外部集成 |
| Official Extension | 官方长期维护、可独立 PyPI 安装的玩法或能力包 | 平台共性（应回 core） |
| Community Extension | 第三方、站点定制、实验功能 | 伪装成平台默认能力 |

## Core 准入（满足任一条 → 优先 core）

1. 无此能力，平台无法正常启动或治理
2. 所有站点默认应具备
3. 被大量插件复用，且不适合作为可选依赖
4. 直接定义产品底盘语义

示例：插件加载与治理、WebUI 后端、命令权限与 cooldown、分片 / ingress、核心 help、`pb_core` / `pb_webui` 类能力。

## Official Extension 准入

满足多数条目 → 官方插件，不进 core：

- 独立玩法或外部服务集成
- 可按需安装 / 升级
- 需要独立 semver、README、PyPI

示例包：`duel`、`who_is_spy`、`maa`、`draw`、`dream`、`ai_media` 及协议相关扩展包。

## Community 准入

- 维护者不在主仓核心团队
- 与特定站点 / 群体 / 外部系统强耦合
- 尚未决定是否进入官方生态

## 判定表

| 问题 | Yes → | No → |
| --- | --- | --- |
| 没有它平台能否成立？ | Core | 继续 |
| 是否所有站点默认拥有？ | Core | Extension |
| 是否显著增加 core 发布 / 测试负担？ | Extension | 继续 |
| 是否适合独立安装与文档？ | Extension | 再评估 |

## 禁止回退

| 回退 | 后果 |
| --- | --- |
| 大一统 core | 破坏分层边界，发布与测试不可控 |
| 插件自造权限 / 冷却 / 配置页 / 热载 / 帮助 | 治理与 WebUI 分叉 |

平台共性统一走 core 提供的入口；玩法走扩展仓。

## 与治理的关系

| 层 | 结构约束 | 分发 |
| --- | --- | --- |
| Core | Golden Plugin + 强元数据 | 随主仓 |
| Official | 元数据 + `activation_policy` + PyPI | 独立仓 |
| Community | 公开 `pallas.api.*` + README / 索引 | Git / 本地 / 商店 |

顺序：归属层 → 目录与发布路径 → 代码。

## 相关

- [架构总览](overview.md)
- [发布](/developer/plugin-development/publishing)
- [Golden Plugin](/developer/plugin-development/golden-plugin)
