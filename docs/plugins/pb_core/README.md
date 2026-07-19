<p align="center">
  <img src="../assets/brand-avatar.png" width="220" height="220" alt="牛牛核心">
</p>

<h1 align="center">牛牛核心 pb_core</h1>

<p align="center">查看牛牛状态，并使用常用管理入口。</p>

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
| `牛牛状态` | 群内 / 私聊 | 查看当前运行状态。 |
| `牛牛控制台` | 群内 / 私聊 | 查看网页入口。 |
| `牛牛插件` | 群内 / 私聊 | 查看当前插件列表。 |
| `牛牛更新` | 群内 / 私聊 | 查看更新情况。 |
| `牛牛重启` | 群内 / 私聊 | 重新启动牛牛。 |
| `牛牛添加号主 号主QQ… [牛 目标牛QQ]` | 私聊 | 默认为当前私聊牛添加号主；带 `牛 目标牛QQ` 时为指定牛初始化库配置并添加。 |

> 详细用法、限制条件和可用范围以帮助为主。

## 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `pb_core.status` | 仅超管 |
| `pb_core.console` | 仅超管 |
| `pb_core.plugins` | 仅超管 |
| `pb_core.update_check` | 仅超管 |
| `pb_core.restart` | 仅超管 |
| `pb_core.add_bot_admin` | 仅超管 |

## 配置项

> 可在控制台对应插件页中修改。

无独立用户配置；命令权限、冷却和运行环境相关行为主要由核心运行时和控制台控制。

## 排障

| 现象 | 处理 |
| --- | --- |
| 状态信息不全 | 检查当前进程角色、Git 环境和运行脚本是否可探测。 |
| 重启无效 | 确认当前部署环境支持调度重启脚本。 |

## 实现

源码位置：[`packages/pb_core/`](../../packages/pb_core/)

关键文件：

- [`__init__.py`](../../packages/pb_core/__init__.py)：注册核心管理命令和权限。
- [`handlers.py`](../../packages/pb_core/handlers.py)：处理状态、控制台入口、插件列表、更新和重启逻辑。

实现要点：

- 这组命令更偏运行管理，而不是普通用户功能。
- `牛牛状态` 和 `牛牛插件` 主要看当前进程视角，不等于全局所有部署实例。
- `牛牛重启` 会依赖外部脚本和当前运行环境，是否真的可用取决于部署方式；通过口令触发时，接收命令的牛牛在重新连上后会 **私聊通知触发者** 已上线（临时文件 `data/pb_core/restart_notify_pending.json`，10 分钟内有效）。

## 相关链接

- [Web 控制台](../pb_webui/README.md)
- [牛牛状态](../bot_status/README.md)
