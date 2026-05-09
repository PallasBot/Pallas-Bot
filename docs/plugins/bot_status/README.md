# bot_status（牛牛状态查询）

汇总 **当前进程内已连接** 的 Bot 与近期离线记录，支持群内查询；在 **断线宽限期** 后仍离线则发 **邮件** 通知。可选接收 NapCat `bot_offline`、Lagrange `BotOfflineEvent` 等协议端离线事件并立即走通知逻辑。

## 依赖

- **`BotConfig`**：离线通知按该牛牛的 **`admins` 推导邮箱**（见下）；`牛牛在吗` 要求发令者 QQ **落在当前应答牛牛的 `admins` 列表**（与 `is_admin_of_bot` 一致，**不含**仅凭 `SUPERUSER` 自动放行）。
- **`block` 插件**：若已记录多 Bot 连接集合，状态列表会以其为「应出现的牛牛」并集当前在线/离线缓存；未启用时以当前在线与离线缓存为准。
- **`nonebot_plugin_apscheduler`**：断线后的延迟校验任务。

## 配置

环境变量走 NoneBot 全局配置（`.env` 等），字段定义见 [`src/plugins/bot_status/config.py`](../../../src/plugins/bot_status/config.py)。

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `bot_status_smtp_user` | `""` | SMTP 登录账号 |
| `bot_status_smtp_password` | `""` | SMTP 密码或授权码 |
| `bot_status_smtp_server` | `""` | SMTP 主机 |
| `bot_status_smtp_port` | `465` | SMTP 端口 |
| `bot_status_notice_email` | `""` | 固定收件人（与号主邮件并列发送离线通知） |
| `bot_status_offline_grace_time` | `30` | 协议 `disconnect` 后等待秒数，到期仍无连接再发邮件，减轻闪断误报 |

`.env` 中有示例注释块可参考。

## 号主邮件说明

离线邮件除发给 `bot_status_notice_email` 外，还会按该牛牛的 **`admins` 的 QQ 号** 构造 **`{qq}@qq.com`** 作为收件人。若号主不用 QQ 邮箱，需在实现层外另行约定或改代码。

未配置 `admins` 时，可用仓库内 [`tools/config/config.mongodb`](../../../tools/config/config.mongodb) 等方式为对应牛牛写入号主。

## 命令与权限

| 命令 | 场景 | 权限 / 说明 |
|------|------|-------------|
| `牛牛在吗` | 群或私聊 | 发令者须在 **当前 Bot 的 `admins`**；群内 **10 秒** 冷却 |
| `牛牛报数` / `牛牛出列` | **仅群聊** | 无额外权限；对本群 **在线且在群内** 的各牛牛依次发报到消息；群内 **10 秒** 冷却 |
| `测试邮件` | 群或私聊 | **超级用户**（`SUPERUSER`）；群内同样走冷却；用于校验 SMTP 与 `bot_status_notice_email` |

## 排障

| 现象 | 说明 |
|------|------|
| `牛牛在吗` 无反应 | 发令者不在该牛牛的 `admins`（超级用户若未写入 `admins` 也会失败）；或处于群冷却窗口。 |
| 离线无邮件 | 检查五项 SMTP 与 `notice_email` 是否齐全；日志中是否有「Mail configuration incomplete」；是否在宽限期内已重连。 |
| 号主收不到邮件 | 当前逻辑固定为 `{admin_qq}@qq.com`，非 QQ 邮箱不会命中。 |
| `测试邮件` 不可用 | 需在环境配置中设置 `SUPERUSERS` 等，使当前账号为超级用户。 |

实现见 [`src/plugins/bot_status/__init__.py`](../../../src/plugins/bot_status/__init__.py)（调度与命令）、[`bot_monitor.py`](../../../src/plugins/bot_status/bot_monitor.py)、[`mail_notifier.py`](../../../src/plugins/bot_status/mail_notifier.py)。
