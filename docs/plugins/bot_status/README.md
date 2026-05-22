# bot_status（牛牛状态）

查询在线/离线牛牛；断线宽限期后发邮件通知；群内报数。

## 用户命令

| 口令 | 场景 | 说明 |
| --- | --- | --- |
| 牛牛在吗 | 群内或私聊 | 号主查状态；超管可看隐藏项 |
| 牛牛报数 / 牛牛出列 | 群内 | 在线牛牛依次报到 |
| 测试邮件 | 群内或私聊 | 超管测 SMTP |

## 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `bot_status.status` | bot_moderator |
| `bot_status.count` | everyone |
| `bot_status.test_mail` | superuser |

## 配置

[`config.py`](../../../src/plugins/bot_status/config.py)：`bot_status_smtp_*`、`bot_status_notice_email`、`bot_status_offline_grace_time`、`bot_status_list_mode`。

### `bot_status_list_mode`（牛牛在吗名册）

| 值 | 单进程 | 分片 |
| --- | --- | --- |
| `auto`（默认） | 本进程连接（`session`） | 协议端 enabled + registry（`fleet`） |
| `session` | 仅 `block` 维护的本进程已连接牛 | 仅**当前 worker** 已连接牛 |
| `fleet` | 协议端 `accounts.json` 中 enabled 账号 | 全集群名册 + `worker_presence.json` 在线态 |

配置示例：`BOT_STATUS_LIST_MODE=fleet`（单进程也想按配置账号列离线时）。

WebUI：**插件配置 → 牛牛状态**，保存后写入 `webui.json` 并热重载（无需重启 Bot）。

## 排障

| 现象 | 处理 |
| --- | --- |
| 收不到邮件 | 查 SMTP、号主 `@qq.com` 收件、固定通知邮箱 |
| 误报离线 | 调大 `offline_grace_time` |

## 实现

[`src/plugins/bot_status/`](../../../src/plugins/bot_status/)
