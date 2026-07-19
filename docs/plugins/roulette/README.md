<p align="center">
  <img src="../assets/brand-avatar.png" width="220" height="220" alt="牛牛轮盘">
</p>

<h1 align="center">牛牛轮盘 roulette</h1>

<p align="center">在群里启动踢人或禁言轮盘，并支持救援和补枪。</p>

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
| `牛牛轮盘` / `牛牛轮盘踢人` / `牛牛轮盘禁言` | 群内 | 启动轮盘。 |
| `牛牛开枪` | 群内 | 参与轮盘。 |
| `牛牛救一下 [@用户]` | 群内 | 尝试解禁。 |
| `牛牛补一枪 [@用户]` | 群内 | 追加禁言。 |

> 详细用法、限制条件和可用范围以帮助为主。

## 命令权限

以当前代码和控制台命令权限配置为准。

## 配置项

> 可在控制台对应插件页中修改。

轮盘相关配置见 [`packages/roulette/config.py`](../../packages/roulette/config.py)。

## 排障

| 现象 | 处理 |
| --- | --- |
| 无法启动 | 确认牛牛有群管理权限。 |
| 行为太随机 | 这是设计行为，醉酒时会更明显。 |

## 实现

源码位置：[`packages/roulette/`](../../packages/roulette/)

关键文件：

- [`__init__.py`](../../packages/roulette/__init__.py)：注册轮盘元数据。
- [`commands.py`](../../packages/roulette/commands.py)：处理开枪、救援和补枪流程。
- [`config.py`](../../packages/roulette/config.py)：定义玩法相关配置。

实现要点：

- 轮盘依赖群管理能力，没权限时即使命令触发也无法完成实际动作。
- 醉酒状态会影响轮盘表现，因此和喝酒系统存在联动。
- 玩法不是单次回复，而是一个在群里持续推进的小流程。

## 相关链接

- [牛牛喝酒](../drink/README.md)
