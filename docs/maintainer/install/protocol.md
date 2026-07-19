# 协议端

把 QQ 账号接入 Pallas-Bot。4.0 一般通过官方插件 `pallas-plugin-protocol` 管理，并在 WebUI 提供控制台页。

## 两层职责

| 层 | 职责 |
| --- | --- |
| `Pallas-Bot` | 接收 OneBot 事件、运行插件、WebUI 与治理 |
| 协议端 | 登录 QQ、维护账号实例、向 Bot 发起反向 WebSocket |

- 协议端异常 ≠ Bot 本体异常
- Bot 正常启动 ≠ QQ 账号已接入
- 分片时，协议端须连到正确的 worker，不要默认连 hub

## 何时查协议端

- 新号接入后，控制台显示账号不在线
- 协议端实例能启动，但 Bot 不收消息
- 分片切换后，部分账号连错 worker
- Docker 下反向 WS 一直连不上

## 接入链路

```text
QQ / 协议端实例
  -> OneBot 反向 WebSocket
  -> Pallas worker 或单进程 Bot
  -> 插件与运行时
```

::: warning
分片时：

- hub：WebUI、注册表、协议端管理与部分回调
- worker：接消息、跑大部分插件逻辑
- 协议端实例里每个账号的 `ws_url` 必须指向所属 worker 端口
:::

## 接入顺序

1. 确认本体与 WebUI 已启动
2. 安装并启用 `pallas-plugin-protocol`
3. 在协议端管理页创建或导入实例
4. 核对实例程序目录、实例根目录和登录方式
5. 让账号连到正确的反向 WS 地址
6. 在 Bot 侧确认 `/pallas/api/bots` 或控制台在线状态已更新

::: warning
分片部署不要跳过第 5 步。账号连到 hub 端口时，通常拿不到预期的群消息处理结果。
:::

## 常查三项

### 1. 协议端实例是否在线

- 协议端实例日志
- 账号登录状态
- 实例程序目录是否正确

实例未真正跑起来时，不要先怀疑 Bot 侧插件。

### 2. 反向 WS 地址是否正确

单进程：连到当前 Bot 监听地址即可。

分片时核对：

- `data/pallas_shard/registry.json` 中的 worker 端口
- 协议端实例中的 `ws_url`
- `PALLAS_SHARD_WS_HOST` 或 Docker 下的可达主机名

账号属于哪个 worker，就连到哪个 worker。hub 负责治理与聚合，不替所有账号接 OneBot 消息。

### 3. Bot 侧是否收到连接

- hub / worker 日志
- 控制台账号在线状态
- 分片 registry 与协议端同步结果

日志里没有连接建立记录时，继续查协议端与网络，不要先改插件逻辑。

## Docker 常见错误

- 容器内外主机名不一致，协议端写了错误的 WS 主机
- 只映射了 hub 端口，未映射实际 worker 端口
- Compose 服务名在协议端侧不可达，却被写成对外地址

::: tip
先确认协议端容器或宿主机能访问目标 worker 端口，再确认写入实例配置的地址与实际网络拓扑一致。
:::

## 排障顺序

1. 协议端实例是否启动成功
2. QQ 账号是否已登录并保持在线
3. 反向 WS 地址是否正确
4. 分片 registry 与账号归属是否一致
5. worker 日志里是否看到连接建立与事件进入

## 避免

- 未确认 WS 连通就怀疑命令权限或插件故障
- 分片场景只看 hub 日志、不看具体 worker
- 看到 WebUI 能打开就以为协议端已接好

## 相关阅读

- [协议端管理插件](/plugins/pb_protocol)
- [连接 QQ](../../guide/connect-qq.md)
- [分片部署](/maintainer/deploy/sharded)
- [排障](/maintainer/operate/troubleshooting)
