# relogin_bot（重新上号）

> **官方扩展**：`pallas-plugin-protocol`（与协议端管理同包）

号主重启协议端并收登录二维码；超管可创建新牛牛实例。

## 用户命令

| 口令 | 场景 | 说明 |
| --- | --- | --- |
| 牛牛重新上号 [QQ] | 私聊 | 号主重启本账号协议端 |
| 创建牛牛 … | 私聊 | 超管新建实例 |

## 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `relogin.relogin` | bot_moderator |
| `relogin.create` | superuser |

## 配置

依赖 `pallas_protocol` 与协议端发行包；见 [pallas_protocol](../pallas_protocol/README.md)。

## 排障

| 现象 | 处理 |
| --- | --- |
| 无二维码 | 查协议端日志与 `data/` 下二维码文件 |
| 无权限 | 确认在 `admins` 或超管 |

## 实现

[`src/plugins/relogin_bot/`](../../../src/plugins/relogin_bot/)
