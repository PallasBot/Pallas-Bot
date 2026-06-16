# 连接 QQ / 协议端

Bot 本体不直接登录 QQ，需要通过 **OneBot v11 协议端**（推荐 NapCat）把消息转给牛牛。

## 方式一：控制台内建协议端（推荐）

1. 启动 Bot：`uv run nb run`
2. 浏览器打开 `http://<主机>:8088/protocol/console/`
3. 新建 NapCat 实例 → 扫码登录
4. 控制台 **协议端实例** 页显示在线即成功

## 方式二：自管 NapCat

在 NapCat 配置正向 WebSocket，指向：

```text
ws://<Bot主机>:8088/onebot/v11/ws
```

若 Bot 监听非本机，把 `<Bot主机>` 换成实际 IP 或域名。

## 验收

在已拉牛的群里发送：

```text
牛牛帮助
```

应收到帮助图或菜单回复。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| 协议端离线 | 看 NapCat 日志；确认端口与防火墙 |
| 在线但群无响应 | 确认牛已入群；看运行日志是否收到消息 |
| 多账号 | 控制台 **协议端实例** 管理多路连接 |

::: tip 下一步
装玩法插件见 [安装官方扩展](install-extensions.md)；日常改配置见 [Web 控制台](../common/webui/README.md)。
:::
