# 连接 QQ

> 目标：让 Bot 上线 QQ，群内能收到并回复消息
> 准备：Bot 已运行，能打开 `http://<Bot主机>:8088/pallas/`；一个 OneBot V11 协议端（NapCat / SnowLuma / 自建）
> 完成之后：协议端账号在线，群里发 **牛牛帮助** 能出图

Pallas-Bot 通过 OneBot V11 反向 WebSocket 接收 QQ 消息。控制台可托管 NapCat / SnowLuma，也可连接已部署好的任意 OneBot V11 协议端。端口以 `config/pallas.toml` 的 `[bootstrap] port` 为准。

## 连接地址

协议端需要主动连接：

```text
ws://<Bot主机>:8088/onebot/v11/ws
```

- 协议端与 Bot 在同一主机且都不在隔离容器中，可用 `127.0.0.1`。
- 协议端在另一台主机或另一容器中，填写它能访问到的 Bot 地址，不能照抄 `127.0.0.1`。
- 分片部署应连接实际承载账号的 worker 端口，不连接 hub。

## 方式一：由控制台托管协议端

打开 `http://<Bot主机>:8088/pallas/protocol`，使用与主控制台相同的登录密钥：

1. 新建账号并选择 NapCat 或 SnowLuma。
2. 选择本机进程或 Docker Runtime，按页面提示安装、拉取镜像和启动。
3. 扫码登录 QQ，等待账号状态变为在线。

协议端缺失或镜像拉取会进入页面中的安装任务，可查看实时进度与失败日志。

### Docker Bot 的额外授权

官方 Bot 镜像已包含 Docker CLI，但默认不挂载 Docker socket。只有需要控制台创建、更新 NapCat / SnowLuma 容器时，才在可信环境取消 Compose 中这一行的注释：

```yaml
- /var/run/docker.sock:/var/run/docker.sock
```

`docker.sock` 接近宿主机 root 权限。此授权只用于协议端 Runtime；Bot 不用它更新自身，也不管理 PostgreSQL、Redis、Ollama 或 AI 服务。页面会分别提示 CLI 缺失、socket 未挂载、权限不足或 Docker daemon 不可达。

## 方式二：连接外置 OneBot V11

若 NapCat、Lagrange、LLOneBot 或其他 OneBot V11 实现已由外部管理：

1. 在协议端启用反向 WebSocket。
2. URL 填本页开头的 `/onebot/v11/ws` 地址。
3. 启动连接并登录 QQ。

连接成功后，账号会自动出现在 Pallas WebUI 的账号列表中，并标记为“外置账号”。外置账号的安装、升级、扫码和进程生命周期仍由原协议端负责；Pallas 只显示连接状态并使用该连接收发消息。

## 验收

把 Bot 拉进测试群并发送：

```text
牛牛帮助
```

收到帮助图即表示 QQ、OneBot V11、Bot 和数据库链路正常。

## 按现象排查

| 现象 | 先检查 |
| --- | --- |
| 打不开协议端管理页 | Bot 是否运行、8088 是否放行 |
| Docker Runtime 无法创建或更新 | 页面中的 Docker 能力状态和安装任务日志 |
| 外置账号未出现 | 协议端反向 WS URL、网络可达性和协议端日志 |
| 已连接但群里无响应 | 账号是否在群、Bot 日志是否收到事件、插件是否启用 |
| 分片账号离线 | 是否连接了对应 worker，而非 hub |

下一步：[安装插件](install-plugins.md)。
