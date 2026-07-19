<p align="center">
  <img src="../assets/brand-avatar.png" width="220" height="220" alt="牛牛帮助">
</p>

<h1 align="center">牛牛帮助 help</h1>

<p align="center">查看功能说明，并管理本群常用插件开关。</p>

<p align="center">
  <img alt="本体 core" src="https://img.shields.io/badge/%E6%9C%AC%E4%BD%93%20core-4B5563">
  <img alt="默认加载" src="https://img.shields.io/badge/%E9%BB%98%E8%AE%A4%E5%8A%A0%E8%BD%BD-4EA94B">
  <img alt="版本 4.0.0" src="https://img.shields.io/badge/%E7%89%88%E6%9C%AC-4.0.0-2563EB">
</p>

## 安装方式

默认加载，无需单独安装。

## 怎么使用

| 口令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| `牛牛帮助` | 群内 / 私聊 | 查看插件总览与开关状态。 |
| `牛牛帮助 <插件名或序号>` | 群内 / 私聊 | 查看单个插件功能表。 |
| `牛牛帮助 <插件> <功能序号或名称>` | 群内 / 私聊 | 查看某条功能详情。 |
| `牛牛开启 / 牛牛关闭 <插件名或序号>` | 群内 | 开关单个插件。 |
| `牛牛开启全部功能 / 牛牛关闭全部功能` | 群内 | 批量开关本群功能。 |

> 详细用法、限制条件和可用范围以帮助为主。

## 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `help.help` | 所有人 |
| `help.plugin_enable` | 群管或号主 |
| `help.plugin_disable` | 群管或号主 |
| `help.plugin_enable_all` | 群管或号主 |
| `help.plugin_disable_all` | 群管或号主 |

## 配置项

> 可在控制台对应插件页中修改。

牛牛帮助的样式、忽略名单和自定义视觉项见 [`packages/help/config.py`](../../packages/help/config.py)。视觉相关资料还可参考 [VISUAL.md](../../packages/help/VISUAL.md)。

## 排障

| 现象 | 处理 |
| --- | --- |
| 帮助图生成失败 | 检查样式配置、素材路径和日志输出。 |
| 开关看起来没生效 | 确认操作的是当前群，且目标插件没有额外独立开关。 |

## 实现

源码位置：[`packages/help/`](../../packages/help/)

关键文件：

- [`__init__.py`](../../packages/help/__init__.py)：注册帮助元数据、命令权限和帮助菜单结构。
- [`commands.py`](../../packages/help/commands.py)：处理帮助查询和群内开关命令。
- [`config.py`](../../packages/help/config.py)：定义帮助图样式和相关配置。

实现要点：

- 帮助系统不是静态文案列表，而是根据各插件 `PluginMetadata` 和命令权限动态生成内容。
- 本群开关会作用于群级功能可见性和实际启用状态。
- 帮助图还承担“谁能用”“在哪用”“怎么触发”的统一展示职责。

## 相关链接

- [命令权限说明](../common/cmd_perm/README.md)
- [文档结构模板](../TEMPLATE.md)
