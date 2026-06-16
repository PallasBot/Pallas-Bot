# 连接 QQ / 协议端

::: tip 先知道这件事
Pallas-Bot **不直接登录 QQ**。  
消息路径是：`QQ ←→ NapCat（协议端）←→ Pallas-Bot ←→ 数据库`。
:::

## 默认地址（按 `pallas.toml` 的 port）

| 页面 | 地址 |
| --- | --- |
| 协议端管理 | `http://<主机>:8088/protocol/console/` |
| Web 控制台 | `http://<主机>:8088/pallas/` |
| OneBot WebSocket | `ws://<主机>:8088/onebot/v11/ws` |

`<主机>` 本机填 `127.0.0.1`，远程填服务器 IP 或域名。

---

## 方式一：用控制台管 NapCat（推荐）

**前提**：已 `uv run nb run`，且能打开 `/pallas/`。

1. 打开 `http://<主机>:8088/protocol/console/`  
2. 登录（口令与 `/pallas/` 相同，见启动日志）  
3. 点击 **新建实例** / **添加协议端**  
4. 选择 **NapCat**，按页面提示扫码登录 QQ  
5. 确认实例列表里状态为 **在线**，且 WebSocket 指向 Bot（一般为 `ws://127.0.0.1:8088/onebot/v11/ws`）

**如何确认成功**：

- 协议端页：实例 **在线**  
- Web 控制台首页：能看到 **在线 Bot**  
- QQ 群：发 `牛牛帮助` 有回复  

::: details Docker 里用「Docker 模式」拉 NapCat
需在 `docker-compose.yml` 给 `pallasbot` 服务挂载 `/var/run/docker.sock`（compose 注释里有说明）。  
**注意**：挂载 docker.sock 有安全风险，仅建议在可信内网使用。
:::

---

## 方式二：自己装 NapCat

1. 按 [NapCat 文档](https://napneko.github.io/) 安装并登录 QQ  
2. 在 NapCat 里添加 **正向 WebSocket 客户端**  
3. URL 填：

```text
ws://<Bot主机>:8088/onebot/v11/ws
```

Bot 与 NapCat **不在同一台机器**时，`<Bot主机>` 必须是 NapCat 能访问到的 IP，不能写 `127.0.0.1`（除非同机）。

**如何确认成功**：NapCat 显示 WS 已连接；群内 `牛牛` 或 `牛牛帮助` 有回复。

---

## 验收口令

在**已拉牛进群**的群里发送：

```text
牛牛帮助
```

正常会返回帮助图（列出本群可用功能）。

也可发 `牛牛` 测打招呼（若开了全员同响，多只牛可能一起回）。

---

## 常见问题

| 现象 | 怎么处理 |
| --- | --- |
| 打不开协议端页 | 检查 Bot 是否在跑、端口是否放行、防火墙 |
| 协议端离线 | 看 NapCat 容器/进程日志；重启实例 |
| 在线但群无反应 | 确认牛在群里；看 **运行日志** 有没有收到群消息 |
| 要多只 QQ | 在协议端页建多个实例，或部署多只牛 |

---

▶ 下一步：[安装插件](install-plugins.md) · [使用指南](../user/README.md)
