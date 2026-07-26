# MAA 远控 `maa`

在 QQ 里给已绑定的 MAA 设备下发任务并接收结果（截图等）。需要用牛牛远控明日方舟助手时安装本官方插件。

**类型**：官方插件（需安装）

## 安装

控制台插件商店，或：

```bash
uv run pallas ext install pallas-plugin-maa
```

上手顺序：配置对外访问地址 → 在 MAA 中填写帮助页 URL 与 QQ 标识 → 私聊绑定 → 群里发任务口令。

## 用法

| 口令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| `牛牛绑定MAA` | 私聊 | 绑定当前 QQ 到自己的 MAA 设备 |
| `牛牛MAA状态` | 私聊 / 群内 | 绑定情况、当前设备与队列 |
| `牛牛切换MAA设备` | 私聊 | 多台设备间切换远控目标 |
| `牛牛MAA设备名` | 私聊 | 设置设备别名 |
| `牛牛长草` / `牛牛作战` / `牛牛公招` / `牛牛基建` / `牛牛截图` / `牛牛停止` | 群内 | 常用远控任务 |
| `牛牛MAA任务 <type> [params]` | 群内 | 手动指定任务类型与参数 |
| `牛牛清空MAA队列` | 群内 | 清空当前选用设备队列 |

精确口令与「何人可用」以群内 **牛牛帮助** 为准。

## 命令权限（代码默认）

| 命令 ID | 默认等级 |
| --- | --- |
| `maa.bind` | 所有人 |
| `maa.switch_device` | 所有人 |
| `maa.device_alias` | 所有人 |
| `maa.control` | 所有人 |
| `maa.raw_task` | 所有人 |
| `maa.clear_queue` | 所有人 |
| `maa.status` | 所有人 |

可在控制台插件页或「命令权限」覆盖。面向用户的 usage 不要写死角色名。

## 配置

一般只需 **对外访问地址**（**通用配置 → 外部服务地址** 或插件页）。完整键以扩展仓 `pallas-plugin-maa` 的 `config.py` 为准。

| 键 | 默认 | 说明 |
| --- | --- |
| `maa_public_base_url` | 空 | 对外 HTTP 基址 |
| `maa_attach_screenshot` | true | 指令后附加截图 |
| `maa_combat_auto_prepare` | true | 作战前自动排队关卡设置 |

保存后写入 `data/pallas_config/webui.json`。

## 排障

| 现象 | 处理 |
| --- | --- |
| 未检测到轮询 | MAA 端点不可达或 URL 错误；多机部署须各实例共用 `data/` |
| 下发后无任务 | 未绑定或用户标识非 QQ；查 `牛牛MAA状态` |
| 队列有、MAA 无 | 设备 id 与「当前选用」不一致；可清空队列重试 |
| 截图失败 | 调大反代上传大小限制 |

## 源码

扩展仓 `pallas-plugin-maa`（`tasks.py`、`http_api.py`、`store.py` 等）。

仓库：[Plugin-Maa](https://github.com/PallasBot/Plugin-Maa) · 协议：[MAA 远程控制](https://docs.maa.plus/zh-cn/protocol/remote-control-schema.html)

## 相关链接

- [插件索引](../README.md)
- [命令权限](../../common/cmd_perm/README.md)
