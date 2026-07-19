<p align="center">
  <img src="../assets/brand-avatar.png" width="220" height="220" alt="申请管理">
</p>

<h1 align="center">申请管理 request_handler</h1>

<p align="center">处理好友申请和入群申请，并支持查看、审批和自动同意。</p>

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
| `查看好友申请` / `查看入群申请` | 私聊 | 查看待处理申请。 |
| `同意` / `拒绝` | 私聊 | 处理最新提醒或引用的那条申请。 |
| `同意好友 <QQ>` / `拒绝好友 <QQ>` | 私聊 | 按 QQ 处理单条好友申请。 |
| `同意入群 <群号>` / `拒绝入群 <群号>` | 私聊 | 按群号处理单条入群申请。 |
| `同意所有...` / `拒绝所有...` | 私聊 | 批量处理当前列表。 |
| `查看自动同意` / `开启或关闭自动同意...` | 私聊 | 查看或切换自动同意。 |

> 详细用法、限制条件和可用范围以帮助为主。

## 命令权限

默认按命令权限配置控制，代码默认等级是**号主**。

## 配置项

> 可在控制台对应插件页中修改。

申请管理相关配置见 [`packages/request_handler/config.py`](../../packages/request_handler/config.py)。

## 排障

| 现象 | 处理 |
| --- | --- |
| 没有提醒 | 检查插件是否被关闭，以及号主能否收到私聊。 |
| 同意 / 拒绝无效 | 快捷提醒可能已过期，先重新查看列表。 |

## 实现

源码位置：[`packages/request_handler/`](../../packages/request_handler/)

关键文件：

- [`__init__.py`](../../packages/request_handler/__init__.py)：注册元数据和权限。
- [`commands.py`](../../packages/request_handler/commands.py)：处理查看、审批和自动同意命令。
- [`startup.py`](../../packages/request_handler/startup.py)：注册事件监听和提醒流程。

实现要点：

- 这类申请操作主要走私聊，不建议依赖群内命令处理。
- 插件既支持对单条申请精确处理，也支持直接批量清空当前待处理列表。
- 自动同意开关是按本牛维度保存的，不是群级设置。

## 相关链接

- [命令权限说明](../common/cmd_perm/README.md)
