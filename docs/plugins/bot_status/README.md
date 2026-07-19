<p align="center">
  <img src="../assets/brand-avatar.png" width="220" height="220" alt="牛牛状态">
</p>

<h1 align="center">牛牛状态 bot_status</h1>

<p align="center">查看牛牛在线情况、报数，并在离线时发送邮件提醒。</p>

<p align="center">
  <img alt="官方插件" src="https://img.shields.io/badge/%E5%AE%98%E6%96%B9%E6%8F%92%E4%BB%B6-FE7D37">
  <img alt="控制台插件商店" src="https://img.shields.io/badge/%E6%8E%A7%E5%88%B6%E5%8F%B0-%E6%8F%92%E4%BB%B6%E5%95%86%E5%BA%97-4EA94B">
  <img alt="安装命令" src="https://img.shields.io/badge/uv%20run%20pallas%20ext%20install%20pallas--plugin--bot--status-586069">
  <img alt="版本 4.0.0" src="https://img.shields.io/badge/%E7%89%88%E6%9C%AC-4.0.0-2563EB">
</p>

## 安装方式

可在控制台插件商店安装，或执行 `uv run pallas ext install pallas-plugin-bot-status`。

## 怎么使用

| 口令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| `牛牛在吗` | 群内 / 私聊 | 查看在线或离线情况。 |
| `牛牛报数` / `牛牛出列` | 群内 | 在线牛牛依次报到。 |
| `测试邮件` | 群内 / 私聊 | 测试邮件通知是否可用。 |

> 详细用法、限制条件和可用范围以帮助为主。

## 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `bot_status.status` | 号主 |
| `bot_status.count` | 所有人 |
| `bot_status.test_mail` | 仅超管 |

## 配置项

> 可在控制台对应插件页中修改。

牛牛状态常用配置包括 SMTP、通知邮箱、离线宽限时间，以及 `在吗` 名册范围。

| 键 | 说明 |
| --- | --- |
| `bot_status_list_mode` | 控制 `在吗` 和名册的统计范围 |

## 排障

| 现象 | 处理 |
| --- | --- |
| 收不到邮件 | 检查 SMTP 配置和收件邮箱。 |
| 误报离线 | 适当调大离线宽限时间。 |

## 实现

源码位置：官方插件扩展仓 `pallas-plugin-bot-status`

关键文件：

- 扩展仓 `src/pallas_plugin_bot_status/__init__.py`：注册命令、权限和帮助元数据。
- 在线状态统计文件：负责汇总在线情况与名册展示。
- 邮件通知文件：负责离线通知和测试邮件发送。

实现要点：

- `牛牛在吗` 与 `牛牛报数` 的目标不同，一个偏状态查看，一个偏群内点名。
- 多牛部署时，名册范围受配置影响，不一定只看当前进程。
- 邮件提醒只是兜底能力，能否送达取决于 SMTP 和收件设置。

## 相关链接

- [命令权限说明](../common/cmd_perm/README.md)
- [牛牛状态插件仓库](https://github.com/TogetsuDo/pallas-plugin-bot-status)
