<p align="center">
  <img src="../assets/brand-avatar.png" width="220" height="220" alt="自动夺舍">
</p>

<h1 align="center">自动夺舍 take_name</h1>

<p align="center">随机模仿群友名片，并在特定状态下更活跃。</p>

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
| `定时任务` | 自动 | 随机模仿群友名片。 |
| `牛牛醉酒` | 自动 | 可能更频繁地“夺舍”改名。 |

> 详细用法、限制条件和可用范围以帮助为主。

## 命令权限

无用户口令。

## 配置项

> 可在控制台对应插件页中修改。

无独立 `config.py`；通常通过插件开关和相关行为配置控制。

## 排障

| 现象 | 处理 |
| --- | --- |
| 从不改名 | 概率本来就不高，也要确认插件没有被关闭。 |
| 改名失败 | 确认牛牛有修改群名片权限。 |

## 实现

源码位置：[`packages/take_name/`](../../packages/take_name/)

关键文件：

- [`__init__.py`](../../packages/take_name/__init__.py)：注册自动夺舍元数据。
- [`handlers.py`](../../packages/take_name/handlers.py)：处理改名时机和目标选择。
- [`startup.py`](../../packages/take_name/startup.py)：注册定时任务与运行时联动。

实现要点：

- 夺舍是自动行为，不依赖用户主动发命令。
- 群聊语料和当前群环境会影响模仿对象和行为概率。
- 醉酒状态可能提高行为活跃度，因此和喝酒系统有关联。

## 相关链接

- [牛牛喝酒](../drink/README.md)
- [牛牛复读](../repeater/README.md)
