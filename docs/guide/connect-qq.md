# 连接 QQ

```text
QQ  ←→  NapCat  ←→  Pallas-Bot  ←→  数据库
```

::: tip
先保证 Pallas-Bot 已经在跑，并能打开网页控制台。端口以 `pallas.toml` 的 `[bootstrap] port` 为准，默认 **8088**。
:::

## 1. 打开协议端管理

| 页面 | 地址 |
| --- | --- |
| 协议端管理 | `http://<主机>:8088/pallas/protocol` |
| Web 控制台 | `http://<主机>:8088/pallas/` |
| OneBot WebSocket | `ws://<主机>:8088/onebot/v11/ws` |

本机 `<主机>` 填 `127.0.0.1`；远程填服务器 IP 或域名。

## 2. 【推荐】控制台新建 NapCat

1. 打开协议端页，用和控制台**同一密码**登录
2. 点 **新建实例** → 选 **NapCat** → 扫码
3. 等实例变成 **在线**（WS 一般是 `ws://127.0.0.1:8088/onebot/v11/ws`）

协议端显示在线、控制台能看到 Bot、群里能收到消息——就连上了。

::: details Docker 里用「Docker 模式」拉 NapCat
需给 `pallasbot` 挂载 `/var/run/docker.sock`（见 compose 注释）。挂载 sock 有安全风险，仅建议可信内网。
:::

## 3. 自己装 NapCat（备选）

按 [NapCat 文档](https://napneko.github.io/) 安装并登录，添加 **反向 WebSocket**（由 NapCat 连到 Bot），URL 填：

```text
ws://<Bot主机>:8088/onebot/v11/ws
```

::: tip
Bot 和 NapCat 不在同一台时，**不要**写 `127.0.0.1`，写 Bot 那台对 NapCat 可达的地址。
:::

## 4. 群里试一下

牛进群后发：

```text
牛牛帮助
```

能出帮助图就说明 Pallas-Bot 已在群里正常工作。也可以发 `牛牛` 测打招呼（多只牛同群可能齐回）。

## 常见问题

| 现象 | 先看 |
| --- | --- |
| 打不开协议端页 | Bot 是否在跑、端口是否放行 |
| 协议端离线 | NapCat 日志；重启实例 |
| 在线但群无反应 | 牛是否在群；运行日志有没有进消息 |
| 要多只 QQ | 再建实例，或部署多只牛 |

## 你已经连上 QQ

▶ [安装插件](install-plugins.md)
