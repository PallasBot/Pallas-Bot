# bot_status（牛牛状态）

> **官方扩展**：`pallas-plugin-bot-status`（`uv sync --extra plugins-bot-status`）

查询牛牛在线情况；断线过久可发邮件；群内报数、出列。

## 用户命令

| 口令 | 场景 | 说明 |
| --- | --- | --- |
| 牛牛在吗 | 群内或私聊 | 号主查在线/离线 |
| 牛牛报数 / 牛牛出列 | 群内 | 在线牛牛依次报到 |
| 测试邮件 | 群内或私聊 | 超管测邮件通知 |

## 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `bot_status.status` | bot_moderator |
| `bot_status.count` | everyone |
| `bot_status.test_mail` | superuser |

## 配置

WebUI **插件 → 牛牛状态**：SMTP、通知邮箱、离线多久算掉线、`在吗` 名册范围等。

| `bot_status_list_mode` | 通俗说明 |
| --- | --- |
| `auto`（默认） | 单牛看本机；多牛看协议端登记的名册 |
| `session` | 只看当前进程连着的牛 |
| `fleet` | 按协议端 enabled 账号列名册 |
| `connected` | 列曾经连上过 WebSocket 的牛 |

## 排障

| 现象 | 处理 |
| --- | --- |
| 收不到邮件 | 查 SMTP、收件邮箱 |
| 误报离线 | 调大离线宽限时间 |

## 实现

[`src/plugins/bot_status/`](../../../src/plugins/bot_status/)
