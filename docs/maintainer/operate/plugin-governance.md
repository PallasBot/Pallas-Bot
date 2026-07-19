# 插件治理

## 四个维度

| 维度 | 含义 |
| --- | --- |
| 安装 | 包是否在当前环境 |
| 可见 | 是否出现在帮助体系 |
| 可用 | 当前实例是否真正能跑 |
| 生效方式 | 配置 / 元数据 / 安装后如何生效 |

「没生效」通常只偏其中一层。

## 治理能力

| 能力 | 作用 |
| --- | --- |
| 帮助可见性 | 是否在帮助体系展示；≠ 是否禁用 |
| 全局禁用 | 当前实例整体不可用 |
| 命令权限 | 谁能触发某条命令；≠ 插件整体可用性 |
| cooldown | 频率限制；≠ 权限系统 |
| `reload_policy` | 配置 / 元数据 / 代码变更如何生效 |
| `activation_policy` | 安装、更新、启停后的激活动作 |

常见 `activation_policy`：

- 可直接热加载
- 需要 worker 重启
- 需要整套重启

另见：单插件治理页、命令权限覆盖、cooldown 展示与覆盖、插件配置页。

## 治理入口

| 入口 | 用途 |
| --- | --- |
| 插件列表 | 是否存在、metadata、基本状态 |
| 单插件治理页 | 指令摘要、禁用 / 可见、perm / cooldown、`activation_policy` |
| 通用配置与权限矩阵 | 跨插件权限覆盖、全局行为、WebUI 与代码默认是否一致 |

## 按现象检查

### 安装了，但帮助里看不到

- 帮助可见性
- 插件 metadata
- 是否被全局禁用

### 帮助里能看到，但实际不能用

- 命令权限覆盖
- cooldown
- 是否仍被禁用
- 当前部署是否加载了该插件

### 配置改了，但行为不变

- 插件是否接了 WebUI 配置
- `reload_policy` 是否支持当前变更直接生效
- 改的是配置、元数据还是代码

### 分片下 WebUI 显示不对

- hub 聚合接口
- worker metadata / capabilities 是否汇总
- 是否误把 hub 本地状态当成全局状态

## 约束

- 「帮助可见」≠「插件可用」
- 「安装成功」≠「运行态已生效」
- 分片下治理数据以 hub 聚合结果为准

## 相关 API

- `/pallas/api/plugins`
- `/pallas/api/plugins/capabilities`
- `/pallas/api/plugins/{plugin_name}/governance`
- `/pallas/api/plugins/help-menu-visibility`
- `/pallas/api/plugins/global-disable`

## 相关阅读

- [命令权限](command-permissions.md)
- [运维 API](/maintainer/reference/api)
- [开发者侧插件治理概览](/developer/architecture/plugin-governance)
- [热重载分级](/developer/plugin-development/reload-and-activation)
