<p align="center">
  <img src="../assets/brand-avatar.png" width="220" height="220" alt="牛牛黑名单">
</p>

<h1 align="center">牛牛黑名单 blacklist</h1>

<p align="center">维护全局拉黑和本群屏蔽名单。</p>

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
| `牛牛拉黑` / `牛牛屏蔽` + QQ 或 `@` | 私聊 | 添加全局用户拉黑。 |
| 同上 | 群内 | 添加本群用户屏蔽。 |
| `牛牛拉黑群` / `牛牛屏蔽群` + 群号 | 私聊 | 拉黑指定群。 |
| `牛牛解禁` / `牛牛取消拉黑` + 目标 | 私聊 / 群内 | 解除用户拉黑或屏蔽。 |
| `牛牛解禁群` / `牛牛取消拉黑群` | 私聊 / 群内 | 解除群拉黑。 |

> 详细用法、限制条件和可用范围以帮助为主。

## 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `blacklist.add` | 群管或号主 |
| `blacklist.remove` | 群管或号主 |

## 配置项

> 可在控制台对应插件页中修改。

无独立插件配置；数据主要保存在用户和群配置中。

## 排障

| 现象 | 处理 |
| --- | --- |
| 仍然收到消息 | 确认操作的是全局拉黑、本群屏蔽还是群拉黑，对应范围不同。 |
| 好友申请没被拦 | 只有全局用户拉黑会直接拒绝好友申请。 |

## 实现

源码位置：[`packages/blacklist/`](../../packages/blacklist/)

关键文件：

- [`__init__.py`](../../packages/blacklist/__init__.py)：注册拉黑与解禁元数据。
- [`commands.py`](../../packages/blacklist/commands.py)：处理用户和群的增删逻辑。

实现要点：

- 私聊和群内的行为范围不一样，私聊更偏全局，群内更偏当前群。
- 插件会分别处理用户拉黑、群拉黑和本群屏蔽三种名单。
- 名单命中后会直接影响后续消息处理和部分申请行为。

## 相关链接

- [命令权限说明](../common/cmd_perm/README.md)
