# 牛牛状态 `bot_status`

查看牛牛在线情况、报数，并可在离线时发邮件提醒。需要「在吗 / 报数」或离线邮件时安装本官方插件。

**类型**：官方插件（需安装）

## 安装

控制台插件商店，或：

```bash
uv run pallas ext install pallas-plugin-bot-status
```

## 用法

| 命令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| `牛牛在吗` | 群内 / 私聊 | 在线或离线情况 |
| `牛牛报数` / `牛牛出列` | 群内 | 在线牛依次报到 |
| `测试邮件` | 群内 / 私聊 | 测试邮件通知 |

精确命令与「何人可用」以群内 **牛牛帮助** 为准。

## 命令权限（代码默认）

| 命令 ID | 默认等级 |
| --- | --- |
| `bot_status.status` | 号主 |
| `bot_status.count` | 所有人 |
| `bot_status.test_mail` | 仅超管 |

实际生效等级以控制台「命令权限」为准。面向用户的 usage 不要写死角色名。

## 配置

控制台对应插件页。常用项含 SMTP、通知邮箱、离线宽限时间，以及 `在吗` 名册范围。

| 键 | 说明 |
| --- | --- |
| `bot_status_list_mode` | 控制 `在吗` 和名册的统计范围 |

保存后写入 `data/pallas_config/webui.json`。

## 排障

| 现象 | 处理 |
| --- | --- |
| 收不到邮件 | 检查 SMTP 与收件邮箱 |
| 误报离线 | 适当调大离线宽限时间 |

## 源码

扩展仓 `pallas-plugin-bot-status`。

仓库：[Plugin-Bot-Status](https://github.com/PallasBot/Plugin-Bot-Status)

## 相关链接

- [命令权限](../../common/cmd_perm/README.md)
- [牛牛核心 pb_core](../pb_core/README.md)
