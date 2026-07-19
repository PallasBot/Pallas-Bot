<p align="center">
  <img src="../assets/brand-avatar.png" width="220" height="220" alt="牛牛喝酒">
</p>

<h1 align="center">牛牛喝酒 drink</h1>

<p align="center">让牛牛喝酒、醒酒，并影响它接下来的表现。</p>

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
| `牛牛喝酒` / `牛牛干杯` / `牛牛继续喝` | 群内 | 增加醉酒度，可能睡着。 |
| `牛牛醒一醒` / `牛牛别喝了` | 群内 | 立即醒酒，做梦时也会一并醒梦。 |

> 详细用法、限制条件和可用范围以帮助为主。

## 命令权限

| 命令 ID | 默认等级 | 说明 |
| --- | --- | --- |
| `drink.drink` | 所有人 | 牛牛喝酒 / 牛牛干杯 / 牛牛继续喝 |
| `drink.sober_up` | 所有人 | 牛牛醒一醒 / 牛牛别喝了 |

可在 WebUI 插件页或「通用配置 → 命令权限」覆盖。

## 配置项

> 可在控制台对应插件页中修改。

无独立 `config.py`；醉酒状态和相关冷却主要走运行时状态管理。

## 排障

| 现象 | 处理 |
| --- | --- |
| 喝酒无反应 | 群冷却内可能静默，先看日志和发送是否成功。 |
| 多牛只有一只反应 | 检查多牛部署和消息路由。 |
| 一直不醒 | 发送 `牛牛醒一醒`，或等待自动清醒。 |

## 实现

源码位置：[`packages/drink/`](../../packages/drink/)

关键文件：

- [`__init__.py`](../../packages/drink/__init__.py)：注册喝酒和醒酒元数据。
- [`handlers.py`](../../packages/drink/handlers.py)：处理醉酒度变化和触发逻辑。
- [`startup.py`](../../packages/drink/startup.py)：注册运行时联动。

实现要点：

- 喝酒是很多行为插件的前置状态，会影响聊天、做梦、轮盘和夺舍等表现。
- 多牛同群时，各只牛牛的醉酒状态是独立保存的。
- 醒酒不仅会清醉酒度，还可能顺带结束做梦等联动状态。

## 相关链接

- [牛牛做梦](../dream/README.md)
- [酒后聊天](../chat/README.md)
