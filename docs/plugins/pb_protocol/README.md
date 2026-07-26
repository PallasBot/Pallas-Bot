# 协议端管理 `pb_protocol`

管理 NapCat / SnowLuma 协议端实例与连接配置。需要在网页里建号、启停协议端时安装本官方插件（与 [重新上号](../relogin_bot/README.md) 同属 `pallas-plugin-protocol`）。

**类型**：官方插件（需安装）

## 安装

控制台插件商店，或：

```bash
uv run pallas ext install pallas-plugin-protocol
```

## 用法

无群内用户口令。入口：

| 入口 | 说明 |
| --- | --- |
| `/pallas/protocol` | 协议端管理页 |
| 控制台侧栏 | 跳转到协议端管理 |

连接 QQ 的步骤见 [连接 QQ](../../guide/connect-qq.md)。

## 命令权限（代码默认）

无群内命令。

## 配置

控制台对应插件 / 协议端页面。示例键（以扩展仓为准）：

| 键 | 说明 |
| --- | --- |
| `pallas_protocol_enabled` | 是否加载协议端插件 |
| `pallas_protocol_webui_enabled` | 是否挂载协议端页面 |
| `pallas_protocol_instances_root` | 实例根目录 |
| `pallas_protocol_program_dir` | 协议端程序根目录 |
| `pallas_protocol_docker_onebot_host` | Docker 下写入 OneBot 客户端的主机名或 IP |

保存后写入 `data/pallas_config/webui.json`。

## 排障

| 现象 | 处理 |
| --- | --- |
| 账号无法启动 | 查实例日志、协议端版本与程序目录 |
| Bot 不回复 | 确认反向 WebSocket 已连到对应 hub / worker 端口 |
| 控制台登录失败 | 口令与主控制台共用；遗忘见 [FAQ](../../FAQ.md) |
| Docker 下 WS 连不上 | 检查反向 WS 主机名，不要默认写 Compose 服务名 |

## 源码

扩展仓 `pallas-plugin-protocol`。

仓库：[Plugin-Protocol](https://github.com/PallasBot/Plugin-Protocol)

## 相关链接

- [重新上号 relogin_bot](../relogin_bot/README.md)
- [连接 QQ](../../guide/connect-qq.md)
