# request_handler

处理 **好友申请** 与 **入群邀请**：私聊通知号主（`admins`），支持按条同意/拒绝、引用审批消息快捷同意；可选轮询「被过滤」好友申请并提醒。依赖协议端支持 NapCat 等扩展 API（如 `get_doubt_friends_add_request`）。

## 权限

- 审批类命令：**该牛牛的 `admins`** 或 **超级用户**（`SUPERUSER`）。
- 未配置 `admins` 时，提醒会发给超级用户，避免无人收件。

## 配置

完整字段见 [`src/plugins/request_handler/config.py`](../../../src/plugins/request_handler/config.py)。

| 配置项 | 说明 |
|--------|------|
| `request_handler_notify_superusers` | 是否在通知列表中保留超级用户（默认不向超管重复推送）。 |
| `request_handler_poll_doubt_friends` | 是否每 4 小时轮询被过滤好友申请并提醒（默认开启）。 |

## 常用命令（私聊为主）

- `查看好友申请` / `查看入群邀请`
- `同意`：处理该牛牛**最新一条**审批提醒；或**引用**某条提醒后发送 `同意` / `好` / 留空
- `同意好友 <QQ>` / `拒绝好友 <QQ>`
- `同意所有好友` / `拒绝所有好友`
- `同意入群 <群号>` / `拒绝入群 <群号>` / `同意所有入群`
- `查看自动同意` / `开启自动同意好友` / `关闭自动同意好友` / `开启自动同意入群` / `关闭自动同意入群`（写入 `BotConfig`）

帮助系统里可用 `牛牛开启 request_handler` / `牛牛关闭 request_handler` 控制是否推送申请提醒。

## 排障

| 现象 | 说明 |
|------|------|
| 收不到提醒 | 确认本插件未被帮助系统关闭；号主是否可收私聊；协议端是否正常上报请求事件。 |
| 「同意」无效 | 审批提醒超过约 7 天会过期；请用 `查看好友申请` 或带 QQ/群号的命令。 |
| 被过滤好友相关 API 报错 | 当前协议端可能不支持对应接口，可关闭 `request_handler_poll_doubt_friends` 或升级协议端。 |

实现见 [`src/plugins/request_handler/__init__.py`](../../../src/plugins/request_handler/__init__.py)。
